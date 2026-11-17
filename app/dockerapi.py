"""Cliente mínimo de la API de Docker por el socket Unix, sin dependencias.

Solo expone las operaciones que usa el panel: listar, iniciar/parar/reiniciar, registros, resumen y consumo.
Las referencias a contenedores se resuelven siempre contra la lista real, nunca se pasan tal cual a la ruta.
"""
import os, json, time, socket, struct, threading, http.client, urllib.parse
from concurrent.futures import ThreadPoolExecutor

SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
SELF = os.environ.get("HOSTNAME", "")          # dentro de Docker, el nombre de host es el id corto del contenedor
OPS = ("start", "stop", "restart")


class DockerError(Exception):
    pass


class _Conn(http.client.HTTPConnection):
    def __init__(self, timeout):
        super().__init__("docker", timeout=timeout)

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(SOCK)
        self.sock = s


def call(method, path, params=None, timeout=10, raw=False):
    if params:
        path += "?" + urllib.parse.urlencode(params)
    c = _Conn(timeout)
    try:
        c.request(method, path)
        r = c.getresponse()
        data = r.read()
    except (OSError, http.client.HTTPException) as e:
        raise DockerError(f"Docker no responde ({e.__class__.__name__})")
    finally:
        c.close()
    if r.status >= 400:
        try:
            msg = json.loads(data).get("message", "")
        except ValueError:
            msg = ""
        raise DockerError(msg or f"Docker devolvió {r.status}")
    if raw:
        return data
    return json.loads(data) if data else None


def available():
    return os.path.exists(SOCK)


def containers():
    out = []
    for c in call("GET", "/containers/json", {"all": 1}):
        labels = c.get("Labels") or {}
        ports = sorted({(p.get("PublicPort"), p.get("PrivatePort"), p.get("Type")) for p in c.get("Ports") or [] if p.get("PublicPort")})
        name = (c.get("Names") or ["/?"])[0].lstrip("/")
        out.append(dict(id=c["Id"][:12], name=name, image=c.get("Image", ""), image_id=c.get("ImageID", ""), state=c.get("State", ""),
                        status=c.get("Status", ""), created=c.get("Created", 0), project=labels.get("com.docker.compose.project") or "",
                        ports=[dict(public=a, private=b, proto=t) for a, b, t in ports], self=bool(SELF) and c["Id"].startswith(SELF)))
    return sorted(out, key=lambda x: (x["project"] or x["name"], x["name"]))


def find(ref):
    for c in containers():
        if ref in (c["id"], c["name"]):
            return c
    raise DockerError("No existe ese contenedor")


def action(ref, op):
    if op not in OPS:
        raise DockerError("Operación no permitida")
    c = find(ref)
    if c["self"] and op == "stop":
        raise DockerError("No se puede parar el propio panel desde el panel")
    call("POST", f"/containers/{c['id']}/{op}", {"t": 10} if op != "start" else None, timeout=90)
    return c["name"]


def logs(ref, tail=200):
    c = find(ref)
    data = call("GET", f"/containers/{c['id']}/logs", {"stdout": 1, "stderr": 1, "tail": max(1, min(int(tail), 2000)), "timestamps": 0}, timeout=20, raw=True)
    if len(data) >= 8 and data[0] in (0, 1, 2) and data[1:4] == b"\0\0\0":   # flujo multiplexado: cabecera de 8 bytes por trozo
        out, i = [], 0
        while i + 8 <= len(data):
            n = struct.unpack(">I", data[i + 4:i + 8])[0]
            out.append(data[i + 8:i + 8 + n]); i += 8 + n
        data = b"".join(out)
    return data[-400_000:].decode("utf-8", "replace")


def inspect(ref):
    """Resumen del contenedor. No incluye las variables de entorno porque suelen llevar contraseñas."""
    c = find(ref)
    d = call("GET", f"/containers/{c['id']}/json")
    st, hc = d.get("State", {}), d.get("HostConfig", {})
    return dict(id=c["id"], name=c["name"], image=d.get("Config", {}).get("Image", ""), created=d.get("Created", ""), state=st.get("Status", ""),
                started=st.get("StartedAt", ""), restarts=d.get("RestartCount", 0), health=(st.get("Health") or {}).get("Status", ""),
                restart_policy=(hc.get("RestartPolicy") or {}).get("Name", ""), project=c["project"], ports=c["ports"],
                networks=sorted((d.get("NetworkSettings", {}).get("Networks") or {}).keys()),
                mounts=[dict(src=m.get("Source") or m.get("Name", ""), dst=m.get("Destination", ""), rw=m.get("RW", False)) for m in d.get("Mounts") or []],
                command=" ".join((d.get("Config", {}).get("Entrypoint") or []) + (d.get("Config", {}).get("Cmd") or []))[:300])


def top(ref):
    c = find(ref)
    d = call("GET", f"/containers/{c['id']}/top")
    return d.get("Titles", []), d.get("Processes", [])


def images():
    used = {}
    for c in containers():
        used[c["image_id"]] = used.get(c["image_id"], 0) + 1
    out = [dict(id=i["Id"].split(":")[-1][:12], tags=[t for t in i.get("RepoTags") or [] if t != "<none>:<none>"], size=i.get("Size", 0),
                created=i.get("Created", 0), used=used.get(i["Id"], 0)) for i in call("GET", "/images/json")]
    return sorted(out, key=lambda x: -x["size"])


def volumes():
    vols = (call("GET", "/volumes") or {}).get("Volumes") or []
    return sorted((dict(name=v["Name"], driver=v.get("Driver", ""), project=(v.get("Labels") or {}).get("com.docker.compose.project", "")) for v in vols),
                  key=lambda x: x["name"])


def networks():
    return sorted((dict(name=n["Name"], driver=n.get("Driver", ""), scope=n.get("Scope", ""),
                        subnet=", ".join(c.get("Subnet", "") for c in (n.get("IPAM") or {}).get("Config") or [])) for n in call("GET", "/networks")),
                  key=lambda x: x["name"])


def prune_images():
    d = call("POST", "/images/prune", {"filters": json.dumps({"dangling": ["true"]})}, timeout=120)
    return len(d.get("ImagesDeleted") or []), d.get("SpaceReclaimed", 0)


def version():
    try:
        return call("GET", "/version").get("Version", "")
    except DockerError:
        return ""


# ---------- consumo por contenedor ----------
# Solo se muestrea mientras alguien mira la sección (touch() reciente), para no gastar CPU en balde.
_stats, _prev, _seen, _slock = {}, {}, 0.0, threading.Lock()


def _one(cid):
    try:
        s = call("GET", f"/containers/{cid}/stats", {"stream": "false", "one-shot": "true"}, timeout=6)
        cpu, mem = s.get("cpu_stats", {}), s.get("memory_stats", {})
        used = max(mem.get("usage", 0) - (mem.get("stats") or {}).get("inactive_file", 0), 0)
        return cid, (cpu.get("cpu_usage", {}).get("total_usage", 0), cpu.get("system_cpu_usage", 0), cpu.get("online_cpus", 1) or 1, used, mem.get("limit", 0))
    except (DockerError, ValueError, AttributeError):
        return cid, None


def _loop():
    pool = ThreadPoolExecutor(max_workers=8)
    while True:
        time.sleep(8)
        if time.time() - _seen > 20:
            _prev.clear()
            continue
        try:
            ids = [c["id"] for c in containers() if c["state"] == "running"]
            cur, view = dict(pool.map(_one, ids)), {}
            for cid, v in cur.items():
                p = _prev.get(cid)
                if not v:
                    continue
                pct = None
                if p and v[1] > p[1]:
                    pct = round(max(v[0] - p[0], 0) / (v[1] - p[1]) * v[2] * 100, 1)
                view[cid] = dict(cpu=pct, mem=v[3], limit=v[4])
            _prev.clear(); _prev.update({k: v for k, v in cur.items() if v})
            with _slock:
                _stats.clear(); _stats.update(view)
        except Exception:
            pass


def stats():
    global _seen
    _seen = time.time()
    with _slock:
        return dict(_stats)


def start():
    if available():
        threading.Thread(target=_loop, daemon=True).start()
