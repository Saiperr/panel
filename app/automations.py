"""Tareas automáticas: un disparador (horario o caída de una aplicación) y una acción.

Disparadores: {"kind":"interval","minutes":N} · {"kind":"daily","time":"HH:MM"} · {"kind":"weekly","days":[0-6],"time":"HH:MM"} (0 = lunes)
              {"kind":"down","app":id,"minutes":N}
Acciones:     {"kind":"container","op":"restart|start|stop","name":"..."} · {"kind":"http","method":"GET|POST","url":"..."} · {"kind":"prune"}
"""
import re, json, time, threading, datetime as dt, urllib.request, urllib.error

from .core import q, one, ex, now, stamp
from . import dockerapi, metrics

COOLDOWN = 30 * 60      # una tarea por caída no se repite antes de media hora
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def validate(trig, action):
    k = trig.get("kind")
    if k == "interval":
        trig = dict(kind=k, minutes=max(1, min(int(trig.get("minutes", 0)), 43200)))
    elif k in ("daily", "weekly"):
        if not TIME_RE.match(str(trig.get("time", ""))):
            raise ValueError("Hora no válida")
        t = dict(kind=k, time=trig["time"])
        if k == "weekly":
            t["days"] = sorted({int(d) for d in trig.get("days", []) if 0 <= int(d) <= 6})
            if not t["days"]:
                raise ValueError("Elige al menos un día")
        trig = t
    elif k == "down":
        if not one("SELECT id FROM apps WHERE id=?", (int(trig.get("app", 0)),)):
            raise ValueError("Elige una aplicación vigilada")
        trig = dict(kind=k, app=int(trig["app"]), minutes=max(1, min(int(trig.get("minutes", 2)), 1440)))
    else:
        raise ValueError("Disparador no válido")
    k = action.get("kind")
    if k == "container":
        if action.get("op") not in dockerapi.OPS:
            raise ValueError("Operación no válida")
        action = dict(kind=k, op=action["op"], name=dockerapi.find(str(action.get("name", "")))["name"])
    elif k == "http":
        url = str(action.get("url", "")).strip()
        if not re.match(r"^https?://[^\s]{3,400}$", url) or action.get("method") not in ("GET", "POST"):
            raise ValueError("Dirección web no válida")
        action = dict(kind=k, method=action["method"], url=url)
    elif k == "prune":
        action = dict(kind=k)
    else:
        raise ValueError("Acción no válida")
    return trig, action


def next_run(trig, after=None):
    after = after or now()
    k = trig["kind"]
    if k == "interval":
        return (after + dt.timedelta(minutes=trig["minutes"])).isoformat(timespec="seconds")
    if k in ("daily", "weekly"):
        h, m = map(int, trig["time"].split(":"))
        for add in range(8):
            d = (after + dt.timedelta(days=add)).replace(hour=h, minute=m, second=0, microsecond=0)
            if d > after and (k == "daily" or d.weekday() in trig["days"]):
                return d.isoformat(timespec="seconds")
    return None


def execute(action):
    k = action["kind"]
    if k == "container":
        return f"{dockerapi.action(action['name'], action['op'])}: {action['op']} hecho"
    if k == "prune":
        n, freed = dockerapi.prune_images()
        return f"{n} imágenes borradas, {freed / 1048576:.0f} MB liberados"
    req = urllib.request.Request(action["url"], method=action["method"], data=b"" if action["method"] == "POST" else None, headers={"User-Agent": "SaiperrNexo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}")


def run(auto, by="automático"):
    try:
        ok, msg = True, execute(json.loads(auto["action"]))
    except Exception as e:
        ok, msg = False, str(e)[:200] or e.__class__.__name__
    t = stamp()
    ex("UPDATE automations SET last_run=?, last_ok=?, last_msg=? WHERE id=?", (t, int(ok), msg, auto["id"]))
    ex("INSERT INTO runs(auto_id,name,at,ok,msg,by) VALUES(?,?,?,?,?,?)", (auto["id"], auto["name"], t, int(ok), msg, by))
    ex("DELETE FROM runs WHERE id <= (SELECT MAX(id) FROM runs) - 500")
    return ok, msg


def _tick():
    t = now()
    for a in q("SELECT * FROM automations WHERE enabled=1"):
        trig = json.loads(a["trig"])
        if trig["kind"] == "down":
            recent = a["last_run"] and (t - dt.datetime.fromisoformat(a["last_run"])).total_seconds() < COOLDOWN
            if not recent and metrics.down_for(trig["app"]) >= trig["minutes"] * 60:
                run(a)
        elif not a["next_run"]:
            ex("UPDATE automations SET next_run=? WHERE id=?", (next_run(trig, t), a["id"]))
        elif dt.datetime.fromisoformat(a["next_run"]) <= t:
            ex("UPDATE automations SET next_run=? WHERE id=?", (next_run(trig, t), a["id"]))   # antes de ejecutar: si la tarea reinicia el panel no se repite en bucle
            run(a)


def _loop():
    time.sleep(20)
    while True:
        try:
            _tick()
        except Exception:
            pass
        time.sleep(20)


def start():
    threading.Thread(target=_loop, daemon=True).start()
