"""Lectura de métricas del servidor desde /proc y /sys, sin dependencias externas.

Un hilo toma una muestra cada INTERVAL segundos y otro comprueba los servicios cada SVC_EVERY.
`snapshot()` devuelve la última muestra; `history()` las últimas HIST muestras para las gráficas.
"""
import os, re, json, time, socket, threading, collections, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

from .core import q, one, ex

PROC = os.environ.get("HOST_PROC", "/host/proc")
PASSWD = os.environ.get("HOST_PASSWD", "/host/passwd")
HOSTNAME_FILE = os.environ.get("HOST_HOSTNAME", "/host/hostname")   # el del servidor; /proc daría el del contenedor
SERVICES_FILE = os.environ.get("SERVICES_FILE", "/data/services.json")
NET_DEV = os.environ.get("NET_DEV", f"{PROC}/1/net/dev")   # red del servidor, no la del contenedor
DISK_PATHS = os.environ.get("DISKS", "Sistema (/)=/data")
INTERVAL, SVC_EVERY, HIST, TOP = 2.0, 15, 150, 12
CLK, PAGE = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
SKIP_IF = re.compile(r"^(lo|veth|br-|docker|virbr)")
WHOLE_DISK = re.compile(r"^(sd[a-z]+|vd[a-z]+|hd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")

_lock = threading.Lock()
_latest, _hist = {}, collections.deque(maxlen=HIST)
_services, _svc_state = [], {}
_started = False


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


# ---------- lecturas ----------
def _cpu_times():
    out = {}
    for line in _read(f"{PROC}/stat").splitlines():
        if not line.startswith("cpu"):
            break
        p = line.split()
        v = [int(x) for x in p[1:9]]
        out[p[0]] = (sum(v), v[3] + v[4], v[4])   # total, inactivo (idle+iowait), iowait
    return out


def _mem():
    m = {}
    for line in _read(f"{PROC}/meminfo").splitlines():
        k, _, v = line.partition(":")
        try:
            m[k] = int(v.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    total, avail = m.get("MemTotal", 0), m.get("MemAvailable", 0)
    st, sf = m.get("SwapTotal", 0), m.get("SwapFree", 0)
    return dict(total=total, used=total - avail, avail=avail, pct=round((total - avail) / total * 100, 1) if total else 0,
                cached=m.get("Cached", 0) + m.get("Buffers", 0), swap_total=st, swap_used=st - sf)


def _temps():
    """Sensores de /sys/class/hwmon; el principal es la temperatura del encapsulado de la CPU."""
    out, base = [], "/sys/class/hwmon"
    try:
        hw = sorted(os.listdir(base))
    except OSError:
        hw = []
    for h in hw:
        d = f"{base}/{h}"
        name = _read(f"{d}/name").strip() or h
        try:
            files = sorted(f for f in os.listdir(d) if re.fullmatch(r"temp\d+_input", f))
        except OSError:
            continue
        for f in files:
            try:
                c = int(_read(f"{d}/{f}").strip()) / 1000
            except ValueError:
                continue
            if not 0 < c < 150:
                continue
            label = _read(f"{d}/{f[:-6]}_label").strip()
            out.append(dict(chip=name, name=label or name, c=round(c, 1)))
    main = next((s["c"] for s in out if s["chip"] == "coretemp" and s["name"].lower().startswith("package")), None)
    if main is None:
        main = next((s["c"] for s in out if s["chip"] in ("coretemp", "k10temp", "zenpower", "cpu_thermal")), None)
    if main is None and out:
        main = max(s["c"] for s in out)
    return dict(main=main, sensors=out)


def _net_raw():
    out = {}
    for line in _read(NET_DEV).splitlines()[2:]:
        name, _, rest = line.partition(":")
        name, p = name.strip(), rest.split()
        if len(p) >= 9 and not SKIP_IF.match(name):
            out[name] = (int(p[0]), int(p[8]))
    return out


def _diskio_raw():
    r = w = 0
    for line in _read(f"{PROC}/diskstats").splitlines():
        p = line.split()
        if len(p) >= 10 and WHOLE_DISK.match(p[2]):
            r += int(p[5]) * 512; w += int(p[9]) * 512
    return r, w


def _disks():
    out = []
    for item in DISK_PATHS.split(","):
        name, _, path = item.partition("=")
        try:
            s = os.statvfs(path.strip())
        except OSError:
            continue
        total, free = s.f_blocks * s.f_frsize, s.f_bavail * s.f_frsize
        used = total - s.f_bfree * s.f_frsize
        out.append(dict(name=name.strip(), total=total, used=used, free=free, pct=round(used / (used + free) * 100, 1) if used + free else 0))
    return out


def _battery():
    base = "/sys/class/power_supply"
    try:
        items = os.listdir(base)
    except OSError:
        return None
    bat = next((i for i in sorted(items) if i.startswith("BAT")), None)
    if not bat:
        return None
    try:
        pct = int(_read(f"{base}/{bat}/capacity").strip())
    except ValueError:
        return None
    ac = next((_read(f"{base}/{i}/online").strip() for i in sorted(items) if _read(f"{base}/{i}/type").strip() == "Mains"), "")
    return dict(pct=pct, status=_read(f"{base}/{bat}/status").strip(), ac=ac == "1" if ac else None)


_users, _users_at = {}, 0


def _user(uid):
    global _users, _users_at
    if time.time() - _users_at > 300:
        _users = {}
        for line in _read(PASSWD).splitlines():
            p = line.split(":")
            if len(p) > 2 and p[2].isdigit():
                _users[int(p[2])] = p[0]
        _users_at = time.time()
    return _users.get(uid, str(uid))


def _procs_raw():
    """pid -> (ticks de CPU, memoria residente, nombre, uid, hilos)."""
    out = {}
    try:
        pids = [d for d in os.listdir(PROC) if d.isdigit()]
    except OSError:
        return out
    for pid in pids:
        s = _read(f"{PROC}/{pid}/stat")
        try:
            r = s.rindex(")")
            f = s[r + 2:].split()
            uid = os.stat(f"{PROC}/{pid}").st_uid
            out[int(pid)] = (int(f[11]) + int(f[12]), int(f[21]) * PAGE, s[s.index("(") + 1:r], uid, int(f[17]))
        except (ValueError, IndexError, OSError):
            continue
    return out


def _cmd(pid, comm):
    c = _read(f"{PROC}/{pid}/cmdline").replace("\0", " ").strip()
    return c[:160] if c else f"[{comm}]"


# ---------- servicios ----------
# Las comprobaciones viven en la tabla `apps`. La primera vez se importan del services.json del panel anterior.
def load_services():
    global _services
    rows = q("SELECT * FROM apps ORDER BY id")
    if not rows and not one("SELECT 1 AS x FROM settings WHERE k='_apps_imported'"):
        try:
            with open(SERVICES_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = []
        for s in data if isinstance(data, list) else []:
            if isinstance(s, dict) and s.get("name") and s.get("target") and s.get("type") in ("http", "tcp"):
                ex("INSERT INTO apps(name,kind,target,link) VALUES(?,?,?,?)", (s["name"], s["type"], s["target"], s.get("link") or ""))
        ex("INSERT OR REPLACE INTO settings(k,v) VALUES('_apps_imported','1')")
        rows = q("SELECT * FROM apps ORDER BY id")
    _services = [dict(id=r["id"], name=r["name"], type=r["kind"], target=r["target"], link=r["link"] or "", project=r["project"] or "") for r in rows][:60]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _check(svc):
    t0 = time.monotonic()
    ok, detail = False, ""
    try:
        if svc["type"] == "tcp":
            host, _, port = svc["target"].rpartition(":")
            with socket.create_connection((host, int(port)), timeout=3):
                ok, detail = True, "puerto abierto"
        else:
            req = urllib.request.Request(svc["target"], headers={"User-Agent": "panel-saiperr/1.0"})
            try:
                with _opener.open(req, timeout=4) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code                     # redirecciones y 4xx: el servicio responde
            ok, detail = code < 500, f"HTTP {code}"
    except Exception as e:
        detail = (getattr(e, "reason", None) and str(e.reason)) or e.__class__.__name__
    return ok, round((time.monotonic() - t0) * 1000), detail[:80]


def _svc_loop():
    pool = ThreadPoolExecutor(max_workers=8)
    while True:
        try:
            load_services()
            res = list(pool.map(_check, _services))
            now = time.time()
            with _lock:
                for s, (ok, ms, detail) in zip(_services, res):
                    st = _svc_state.setdefault(s["id"], {"since": now, "ok": ok, "hist": collections.deque(maxlen=40)})
                    if st["ok"] != ok:
                        st["since"] = now
                    st.update(ok=ok, ms=ms, detail=detail, checked=now)
                    st["hist"].append(1 if ok else 0)
                for k in [k for k in _svc_state if k not in {s["id"] for s in _services}]:
                    _svc_state.pop(k, None)
        except Exception:
            pass
        time.sleep(SVC_EVERY)


def _services_view():
    out = []
    for s in _services:
        st = _svc_state.get(s["id"])
        d = dict(id=s["id"], name=s["name"], link=s["link"], kind=s["type"], target=s["target"], project=s["project"])
        if st:
            d.update(ok=st["ok"], ms=st["ms"], detail=st["detail"], since=round(st["since"]), hist=list(st["hist"]))
        out.append(d)
    return out


def services():
    with _lock:
        return _services_view()


def down_for(app_id):
    """Segundos que lleva caída una comprobación (0 si funciona o aún no se ha comprobado)."""
    with _lock:
        st = _svc_state.get(app_id)
        return time.time() - st["since"] if st and not st["ok"] else 0


def recheck():
    load_services()


# ---------- muestreo ----------
def _loop():
    cpu0, net0, io0, pr0, t0 = _cpu_times(), _net_raw(), _diskio_raw(), _procs_raw(), time.monotonic()
    model = next((l.split(":", 1)[1].strip() for l in _read(f"{PROC}/cpuinfo").splitlines() if l.startswith("model name")), "")
    while True:
        time.sleep(INTERVAL)
        try:
            cpu1, net1, io1, pr1, t1 = _cpu_times(), _net_raw(), _diskio_raw(), _procs_raw(), time.monotonic()
            el = max(t1 - t0, 0.001)

            def pct(k, idx=1):
                a, b = cpu0.get(k), cpu1.get(k)
                if not a or not b or b[0] == a[0]:
                    return 0.0
                busy = (b[idx] - a[idx]) / (b[0] - a[0]) * 100
                return round(max(0.0, min(100.0, 100 - busy if idx == 1 else busy)), 1)

            cores = [pct(k) for k in sorted((k for k in cpu1 if k != "cpu"), key=lambda x: int(x[3:]))]
            ifaces, rx, tx = [], 0.0, 0.0
            for name, (r, w) in sorted(net1.items()):
                a = net0.get(name, (r, w))
                rr, ww = max(r - a[0], 0) / el, max(w - a[1], 0) / el
                ifaces.append(dict(name=name, rx=round(rr), tx=round(ww), rx_total=r, tx_total=w))
                if not name.startswith(("tailscale", "wg", "tun")):   # los túneles ya cuentan en la interfaz física
                    rx += rr; tx += ww
            procs = []
            for pid, (ticks, rss, comm, uid, thr) in pr1.items():
                old = pr0.get(pid)
                c = max(ticks - old[0], 0) / CLK / el * 100 if old and old[2] == comm else 0.0
                procs.append((pid, round(c, 1), rss, comm, uid, thr))
            mem = _mem()

            def view(rows):
                return [dict(pid=p, cpu=c, mem=m, mem_pct=round(m / mem["total"] * 100, 1) if mem["total"] else 0, name=n,
                             user=_user(u), cmd=_cmd(p, n)) for p, c, m, n, u, _ in rows]

            temp = _temps()
            load = _read(f"{PROC}/loadavg").split()
            up = _read(f"{PROC}/uptime").split()
            snap = dict(
                t=round(time.time(), 1), interval=INTERVAL,
                host=dict(name=_read(HOSTNAME_FILE).strip() or _read(f"{PROC}/sys/kernel/hostname").strip(), kernel=_read(f"{PROC}/sys/kernel/osrelease").strip(),
                          uptime=float(up[0]) if up else 0, cpu_model=model, cores=len(cores),
                          load=[float(x) for x in load[:3]] if len(load) >= 3 else [], procs=len(procs),
                          threads=sum(p[5] for p in procs)),
                cpu=dict(pct=pct("cpu"), iowait=pct("cpu", 2), cores=cores),
                mem=mem, temp=temp,
                net=dict(rx=round(rx), tx=round(tx), ifaces=ifaces),
                disk=dict(mounts=_disks(), read=round(max(io1[0] - io0[0], 0) / el), write=round(max(io1[1] - io0[1], 0) / el)),
                battery=_battery(),
                procs=dict(cpu=view(sorted(procs, key=lambda p: (-p[1], -p[2]))[:TOP]), mem=view(sorted(procs, key=lambda p: -p[2])[:TOP])),
            )
            with _lock:
                _latest.clear(); _latest.update(snap)
                _hist.append(dict(t=snap["t"], cpu=snap["cpu"]["pct"], mem=mem["pct"], temp=temp["main"], rx=snap["net"]["rx"], tx=snap["net"]["tx"]))
            cpu0, net0, io0, pr0, t0 = cpu1, net1, io1, pr1, t1
        except Exception:
            time.sleep(1)


def start():
    global _started
    if _started:
        return
    _started = True
    load_services()
    threading.Thread(target=_loop, daemon=True).start()
    threading.Thread(target=_svc_loop, daemon=True).start()


def snapshot():
    with _lock:
        d = dict(_latest)
        d["services"] = [s for s in _services_view() if "ok" in s]
        return d


def history():
    with _lock:
        return list(_hist)
