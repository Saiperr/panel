"""Red del servidor: dispositivos vistos (tabla ARP), puertos a la escucha y equipos de Tailscale."""
import os, re, json, socket, ipaddress, subprocess, http.client
from concurrent.futures import ThreadPoolExecutor, wait

from .core import q, ex, stamp, setting
from . import dockerapi

PROC = os.environ.get("HOST_PROC", "/host/proc")
TS_SOCK = os.environ.get("TAILSCALE_SOCK", "/var/run/tailscale/tailscaled.sock")
VIRTUAL = re.compile(r"^(lo|veth|br-|docker|virbr|tailscale)")
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _arp():
    out = {}
    for line in _read(f"{PROC}/1/net/arp").splitlines()[1:]:
        p = line.split()
        if len(p) >= 6 and not VIRTUAL.match(p[5]) and p[2] != "0x0" and p[3] != "00:00:00:00:00:00":
            out[p[3].lower()] = p[0]
    return out


def devices():
    """Cruza la tabla ARP actual con los dispositivos ya conocidos y devuelve todos."""
    seen, t = _arp(), stamp()
    for mac, ip in seen.items():
        ex("INSERT INTO devices(mac,ip,first_seen,last_seen) VALUES(?,?,?,?) ON CONFLICT(mac) DO UPDATE SET ip=excluded.ip,last_seen=excluded.last_seen", (mac, ip, t, t))
    rows = q("SELECT * FROM devices")
    for r in rows:
        r["online"] = r["mac"] in seen
    return sorted(rows, key=lambda r: (not r["online"], tuple(int(x) for x in r["ip"].split(".")) if r["ip"] and r["ip"].replace(".", "").isdigit() else (999,)))


def _ping(ip):
    try:
        return subprocess.run(["ping", "-c", "1", "-W", "1", str(ip)], capture_output=True, timeout=4).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _rdns(ip):
    try:
        return ip, socket.gethostbyaddr(ip)[0]
    except OSError:
        return ip, ""


def scan():
    """Hace ping a toda la red local para que el servidor refresque su tabla ARP. Devuelve cuántos responden."""
    try:
        net = ipaddress.ip_network(str(setting("lan")), strict=False)
    except ValueError:
        raise ValueError("La red configurada no es válida")
    if net.version != 4 or net.num_addresses > 1024 or not net.is_private:
        raise ValueError("Solo se escanean redes privadas IPv4 de hasta 1024 direcciones")
    with ThreadPoolExecutor(max_workers=64) as pool:
        alive = sum(pool.map(_ping, net.hosts()))
    pool = ThreadPoolExecutor(max_workers=16)     # nombres por DNS inverso, sin esperar más de 3 s en total
    futs = [pool.submit(_rdns, ip) for ip in _arp().values()]
    done, _ = wait(futs, timeout=3)
    pool.shutdown(wait=False, cancel_futures=True)
    for f in done:
        ip, name = f.result()
        if name and name != ip:
            ex("UPDATE devices SET hostname=? WHERE ip=?", (name[:80], ip))
    return alive


def ping(host, count=3):
    if not HOST_RE.match(host or ""):
        raise ValueError("Nombre o dirección no válidos")
    r = subprocess.run(["ping", "-c", str(count), "-W", "2", host], capture_output=True, timeout=15, text=True)
    return (r.stdout or r.stderr).strip()


def _sockets(fname, v6):
    listen, est = set(), 0
    for line in _read(f"{PROC}/1/net/{fname}").splitlines()[1:]:
        p = line.split()
        if len(p) < 4:
            continue
        if p[3] == "0A":
            addr, _, port = p[1].rpartition(":")
            local = addr in ("0100007F", "00000000000000000000000001000000") or addr.startswith("3500007F") or addr.startswith("3600007F")
            listen.add((int(port, 16), local))
        elif p[3] == "01":
            est += 1
    return listen, est


def ports():
    l4, e4 = _sockets("tcp", False)
    l6, e6 = _sockets("tcp6", True)
    owner = {}
    try:
        for c in dockerapi.containers():
            for p in c["ports"]:
                if p["proto"] == "tcp":
                    owner[p["public"]] = c["name"]
    except dockerapi.DockerError:
        pass
    merged = {}
    for port, local in l4 | l6:
        merged[port] = merged.get(port, True) and local
    known = {22: "SSH", 53: "DNS"}
    return dict(established=e4 + e6, listening=[dict(port=p, local=loc, owner=owner.get(p) or known.get(p, "")) for p, loc in sorted(merged.items())])


class _TS(http.client.HTTPConnection):
    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3); s.connect(TS_SOCK); self.sock = s


def tailscale():
    if not os.path.exists(TS_SOCK):
        return None
    c = _TS("local-tailscaled.sock", timeout=3)
    try:
        c.request("GET", "/localapi/v0/status")
        r = c.getresponse()
        if r.status != 200:
            return None
        d = json.loads(r.read())
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        c.close()

    def node(n, me=False):
        return dict(name=n.get("HostName", ""), ip=(n.get("TailscaleIPs") or [""])[0], os=n.get("OS", ""), online=bool(n.get("Online")) or me, me=me,
                    last=(n.get("LastSeen") or "")[:19].replace("T", " ") if not n.get("Online") and not me else "")
    peers = [node(d["Self"], True)] if d.get("Self") else []
    peers += sorted((node(p) for p in (d.get("Peer") or {}).values()), key=lambda x: (not x["online"], x["name"].lower()))
    return dict(state=d.get("BackendState", ""), peers=peers)
