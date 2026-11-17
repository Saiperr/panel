"""Consola restringida: no hay intérprete de órdenes detrás, solo esta lista cerrada de comandos."""
import shlex, datetime as dt

from .core import ROLES, now
from . import dockerapi, metrics, netinfo, files

HELP = """Comandos disponibles:
  docker ps                  contenedores y su estado
  docker logs <nombre> [n]   últimas n líneas de registro (100 por defecto)
  docker top <nombre>        procesos dentro de un contenedor
  docker images              imágenes y tamaño
  docker stats               consumo por contenedor
  docker start|stop|restart <nombre>
  apps                       estado de las aplicaciones vigiladas
  uptime · free · df · ps    carga, memoria, disco y procesos del servidor
  ip                         interfaces de red y tráfico
  ports                      puertos a la escucha
  ping <host>                tres pings a un equipo
  ls [ruta] · cat <ruta>     archivos de la carpeta del servidor (solo lectura)
  date · whoami · clear · help"""


def _b(n):
    for u in ("B", "K", "M", "G", "T"):
        if n < 1024 or u == "T":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024


def _table(rows):
    if not rows:
        return "(vacío)"
    w = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in rows)


def run(line, user):
    try:
        a = shlex.split(line)
    except ValueError:
        return "Comillas sin cerrar."
    if not a:
        return ""
    cmd, arg = a[0], a[1:]
    s = metrics.snapshot()
    try:
        if cmd == "help":
            return HELP
        if cmd == "whoami":
            return f"{user['username']} ({user['role']})"
        if cmd == "date":
            return now().strftime("%A %d/%m/%Y %H:%M:%S") + " (Europe/Madrid)"
        if cmd == "uptime":
            h = s["host"]
            return f"encendido {dt.timedelta(seconds=int(h['uptime']))} · carga {' '.join(f'{x:.2f}' for x in h['load'])} · {h['procs']} procesos"
        if cmd == "free":
            m = s["mem"]
            return _table([("", "total", "usado", "disponible", "caché"), ("Mem:", _b(m["total"]), _b(m["used"]), _b(m["avail"]), _b(m["cached"])),
                           ("Swap:", _b(m["swap_total"]), _b(m["swap_used"]), _b(m["swap_total"] - m["swap_used"]), "")])
        if cmd == "df":
            return _table([("Disco", "Tamaño", "Usado", "Libre", "Uso")] + [(d["name"], _b(d["total"]), _b(d["used"]), _b(d["free"]), f"{d['pct']}%") for d in s["disk"]["mounts"]])
        if cmd == "ps":
            return _table([("PID", "USUARIO", "%CPU", "MEM", "ORDEN")] + [(p["pid"], p["user"], p["cpu"], _b(p["mem"]), p["cmd"][:90]) for p in s["procs"]["cpu"]])
        if cmd == "ip":
            return _table([("INTERFAZ", "BAJADA/s", "SUBIDA/s", "RECIBIDO", "ENVIADO")] + [(i["name"], _b(i["rx"]), _b(i["tx"]), _b(i["rx_total"]), _b(i["tx_total"])) for i in s["net"]["ifaces"]])
        if cmd == "ports":
            return _table([("PUERTO", "ALCANCE", "SERVICIO")] + [(p["port"], "local" if p["local"] else "red", p["owner"] or "-") for p in netinfo.ports()["listening"]])
        if cmd == "apps":
            return _table([("ESTADO", "APLICACIÓN", "RESPUESTA")] + [("ok" if x["ok"] else "CAÍDA", x["name"], f"{x['ms']} ms · {x['detail']}") for x in s["services"]])
        if cmd == "ping":
            return netinfo.ping(arg[0]) if len(arg) == 1 else "Uso: ping <host>"
        if cmd == "ls":
            d = files.listing(arg[0] if arg else "")
            return _table([("d" if i["dir"] else "-", _b(i["size"]) if not i["dir"] else "", dt.datetime.fromtimestamp(i["mtime"]).strftime("%d/%m/%Y %H:%M"), i["name"] + ("/" if i["dir"] else "")) for i in d["items"]])
        if cmd == "cat":
            if len(arg) != 1:
                return "Uso: cat <ruta>"
            v = files.view(arg[0])
            return "(archivo binario)" if v["binary"] else v["text"] + ("\n… (recortado)" if v["truncated"] else "")
        if cmd == "docker":
            return _docker(arg, user)
    except (dockerapi.DockerError, files.FileError, ValueError) as e:
        return f"Error: {e}"
    except (KeyError, IndexError):
        return "Todavía no hay datos; prueba en unos segundos."
    return f"{cmd}: comando no permitido. Escribe «help» para ver la lista."


def _docker(a, user):
    sub = a[0] if a else ""
    if sub == "ps":
        return _table([("NOMBRE", "ESTADO", "IMAGEN", "PUERTOS")] + [(c["name"], c["status"], c["image"][:44], ",".join(str(p["public"]) for p in c["ports"]) or "-") for c in dockerapi.containers()])
    if sub == "images":
        return _table([("IMAGEN", "TAMAÑO", "EN USO")] + [((i["tags"] or [i["id"]])[0], _b(i["size"]), "sí" if i["used"] else "no") for i in dockerapi.images()])
    if sub == "stats":
        st, cs = dockerapi.stats(), {c["id"]: c["name"] for c in dockerapi.containers()}
        if not st:
            return "Recogiendo datos; repite el comando en unos segundos."
        return _table([("NOMBRE", "%CPU", "MEMORIA")] + [(cs.get(k, k), "-" if v["cpu"] is None else v["cpu"], _b(v["mem"])) for k, v in sorted(st.items(), key=lambda kv: -kv[1]["mem"])])
    if sub == "logs" and len(a) in (2, 3):
        return dockerapi.logs(a[1], int(a[2]) if len(a) == 3 and a[2].isdigit() else 100).rstrip() or "(sin registros)"
    if sub == "top" and len(a) == 2:
        titles, rows = dockerapi.top(a[1])
        return _table([titles] + rows)
    if sub in dockerapi.OPS and len(a) == 2:
        if ROLES[user["role"]] < ROLES["operador"]:
            return "Tu rol no puede iniciar ni parar contenedores."
        return f"{dockerapi.action(a[1], sub)}: {sub} hecho"
    return "Uso: docker ps | logs <nombre> [n] | top <nombre> | images | stats | start|stop|restart <nombre>"
