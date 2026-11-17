"""Explorador de archivos de solo lectura sobre la carpeta del servidor montada en FILES_ROOT."""
import os, re, stat

ROOT = os.path.realpath(os.environ.get("FILES_ROOT", "/host/home"))
LABEL = os.environ.get("FILES_LABEL", "/home/saiperr")
# Claves y secretos: no se listan ni se abren desde el panel.
DENY = re.compile(r"^(\.ssh|\.gnupg|\.docker|\.env(\..*)?|\.bash_history|\.netrc|id_(rsa|ed25519|ecdsa).*|.*\.(pem|key|kdbx))$", re.I)
MAX_VIEW = 256 * 1024


class FileError(Exception):
    pass


def available():
    return os.path.isdir(ROOT)


def resolve(rel):
    rel = (rel or "").replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p]
    if any(p in (".", "..") or DENY.match(p) for p in parts):
        raise FileError("Ruta no permitida")
    full = os.path.realpath(os.path.join(ROOT, *parts))
    if full != ROOT and not full.startswith(ROOT + os.sep):   # enlaces simbólicos que salen de la carpeta
        raise FileError("Ruta no permitida")
    if any(DENY.match(p) for p in os.path.relpath(full, ROOT).split(os.sep)):
        raise FileError("Ruta no permitida")
    if not os.path.lexists(full):
        raise FileError("No existe")
    return full, "/".join(parts)


def listing(rel):
    full, rel = resolve(rel)
    if not os.path.isdir(full):
        raise FileError("No es una carpeta")
    items = []
    try:
        names = os.listdir(full)
    except OSError:
        raise FileError("Sin permiso para leer esta carpeta")
    for n in names:
        if DENY.match(n):
            continue
        try:
            st = os.stat(os.path.join(full, n))
        except OSError:
            continue
        items.append(dict(name=n, dir=stat.S_ISDIR(st.st_mode), size=st.st_size, mtime=int(st.st_mtime)))
    items.sort(key=lambda i: (not i["dir"], i["name"].lower()))
    return dict(path=rel, label=LABEL, items=items[:2000], more=max(len(items) - 2000, 0))


def view(rel):
    full, rel = resolve(rel)
    if not os.path.isfile(full):
        raise FileError("No es un archivo")
    size = os.path.getsize(full)
    try:
        with open(full, "rb") as f:
            data = f.read(MAX_VIEW)
    except OSError:
        raise FileError("Sin permiso para leer este archivo")
    if b"\0" in data:
        return dict(path=rel, size=size, binary=True)
    return dict(path=rel, size=size, binary=False, truncated=size > MAX_VIEW, text=data.decode("utf-8", "replace"))
