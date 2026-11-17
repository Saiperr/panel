"""Plugins: un .zip con manifest.json e index.html autónomo (estilos y scripts dentro del propio archivo).

Cada plugin se muestra como una sección más, dentro de un marco aislado: no puede leer la sesión ni llamar a la API,
y solo recibe del panel un resumen de métricas por postMessage ({type:"nexo:stats", data:{...}}).
"""
import os, io, re, json, shutil, zipfile

DIR = os.path.join(os.path.dirname(os.environ.get("DB_PATH", "/data/app.db")), "plugins")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
MAX_HTML = 1024 * 1024


def _manifest(pid):
    try:
        with open(os.path.join(DIR, pid, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        return dict(id=pid, name=str(m.get("name") or pid)[:40], version=str(m.get("version") or "")[:20], description=str(m.get("description") or "")[:200])
    except (OSError, ValueError, AttributeError):
        return None


def installed():
    try:
        ids = sorted(d for d in os.listdir(DIR) if ID_RE.match(d))
    except OSError:
        return []
    return [m for m in map(_manifest, ids) if m]


def install(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = {n for n in z.namelist() if not n.endswith("/")}
        if not {"manifest.json", "index.html"} <= names:
            raise ValueError("El zip debe llevar manifest.json e index.html en la raíz")
        m = json.loads(z.read("manifest.json").decode("utf-8"))
        pid = str(m.get("id", "")) if isinstance(m, dict) else ""
        if not ID_RE.match(pid):
            raise ValueError("El «id» del manifest debe ser corto, en minúsculas, con letras, números o guiones")
        if z.getinfo("index.html").file_size > MAX_HTML:
            raise ValueError("index.html pasa de 1 MB")
        html = z.read("index.html")
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError):
        raise ValueError("El archivo no es un plugin válido")
    dest = os.path.join(DIR, pid)
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    with open(os.path.join(dest, "index.html"), "wb") as f:
        f.write(html)
    return _manifest(pid)


def remove(pid):
    if ID_RE.match(pid) and os.path.isdir(os.path.join(DIR, pid)):
        shutil.rmtree(os.path.join(DIR, pid))
        return True
    return False


def page(pid):
    if not ID_RE.match(pid):
        return None
    try:
        with open(os.path.join(DIR, pid, "index.html"), "rb") as f:
            return f.read()
    except OSError:
        return None


EXAMPLE_HTML = """<!doctype html><html lang="es"><meta charset="utf-8"><title>Resumen</title>
<style>body{margin:0;padding:24px;background:#0d1016;color:#e6e9ef;font:16px system-ui,sans-serif}
h1{font-size:20px;margin:0 0 16px}dl{display:grid;grid-template-columns:auto 1fr;gap:10px 24px;margin:0}
dt{color:#8b93a3}dd{margin:0;font-variant-numeric:tabular-nums}</style>
<h1>Resumen del servidor</h1><dl id="d"><dt>Estado</dt><dd>Esperando datos del panel…</dd></dl>
<script>
// El panel envía un resumen de métricas cada pocos segundos.
addEventListener("message", function (e) {
  if (!e.data || e.data.type !== "nexo:stats") return;
  var s = e.data.data, d = document.getElementById("d"); d.textContent = "";
  [["Servidor", s.host.name], ["CPU", s.cpu.pct + " %"], ["Memoria", s.mem.pct + " %"],
   ["Temperatura", s.temp == null ? "sin sensor" : s.temp + " °C"],
   ["Aplicaciones en marcha", s.services.filter(function (x) { return x.ok; }).length + " de " + s.services.length]]
    .forEach(function (r) { var a = document.createElement("dt"), b = document.createElement("dd"); a.textContent = r[0]; b.textContent = r[1]; d.appendChild(a); d.appendChild(b); });
});
</script></html>"""


def example_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({"id": "resumen", "name": "Resumen", "version": "1.0", "description": "Plugin de ejemplo: muestra un resumen con los datos que envía el panel."}, ensure_ascii=False, indent=2))
        z.writestr("index.html", EXAMPLE_HTML)
    return buf.getvalue()
