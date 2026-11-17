import os, re, json, hmac, time, base64, struct, secrets, hashlib, ipaddress
from fastapi import FastAPI, Request, Form, Body, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from .core import q, one, ex, init_db, now, stamp, settings, set_setting, audit, ROLES, DEFAULTS
from . import metrics, dockerapi, netinfo, files, console, automations, plugins

HERE = os.path.dirname(__file__)
init_db()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=os.environ["SECRET_KEY"], same_site="lax", session_cookie="panel_session",
                   https_only=os.environ.get("COOKIE_SECURE", "0") == "1", max_age=60 * 60 * 24 * 14)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
templates.env.globals["asset_v"] = hashlib.sha1(b"".join(open(os.path.join(HERE, "static", f), "rb").read() for f in ("style.css", "app.js"))).hexdigest()[:10]
templates.env.globals["panel_name"] = lambda: settings()["name"]
ph = PasswordHasher()
SETUP_CODE = os.environ.get("SETUP_CODE", "")
FAILS, WINDOW = {}, 600
USER_RE = re.compile(r"[a-z0-9_.-]{3,32}")
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
PLUGIN_CSP = "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'"


@app.middleware("http")
async def security(request: Request, call_next):
    limit = 2 * 1024 * 1024 if request.url.path == "/api/plugins/install" else 16 * 1024
    try:
        if int(request.headers.get("content-length") or 0) > limit:
            return PlainTextResponse("Petición demasiado grande", status_code=413)
    except ValueError:
        return PlainTextResponse("Petición no válida", status_code=400)
    # Cloudflare indica en CF-Visitor el esquema que usó el visitante: si llegó por http, a https
    if '"scheme":"http"' in request.headers.get("cf-visitor", "") and request.method in ("GET", "HEAD"):
        host = request.headers.get("host", "")
        if re.fullmatch(r"[A-Za-z0-9.-]+", host):
            return RedirectResponse(f"https://{host}{request.url.path}", status_code=301)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/plugins/"):
        resp.headers["Content-Security-Policy"] = PLUGIN_CSP
    else:
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = CSP
    if not request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.on_event("startup")
def _start():
    metrics.start()
    dockerapi.start()
    automations.start()


@app.exception_handler(dockerapi.DockerError)
@app.exception_handler(files.FileError)
@app.exception_handler(ValueError)
def _bad(request, exc):
    return JSONResponse({"detail": str(exc) or "Petición no válida"}, status_code=400)


# ---------- utilidades ----------
def client_ip(request):
    return request.client.host if request.client else "?"


def blocked(keys_limits):
    t = time.time()
    for k in [k for k, v in FAILS.items() if not any(x > t - WINDOW for x in v)]:
        FAILS.pop(k, None)
    return any(len([x for x in FAILS.get(k, []) if x > t - WINDOW]) >= m for k, m in keys_limits)


def register_fail(keys):
    t = time.time()
    for k in keys:
        FAILS[k] = [x for x in FAILS.get(k, []) if x > t - WINDOW] + [t]


def csrf(request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(24)
    return request.session["csrf"]


def check_csrf(request, token):
    if not token or not secrets.compare_digest(str(token), request.session.get("csrf", "")):
        raise PermissionError


def getuser(request):
    uid = request.session.get("uid")
    u = one("SELECT id, username, role, active, sv, totp IS NOT NULL AS twofa FROM users WHERE id=?", (uid,)) if uid else None
    if not u or not u["active"] or u["sv"] != request.session.get("sv", 0) or u["role"] not in ROLES:
        return None
    return u


def need(request, role="lector"):
    """Usuario con sesión y rol suficiente; en las peticiones que cambian algo, además el token CSRF."""
    u = getuser(request)
    if not u:
        raise HTTPException(401, "Sesión caducada")
    if ROLES[u["role"]] < ROLES[role]:
        raise HTTPException(403, "Tu rol no permite esta acción")
    if request.method != "GET":
        try:
            check_csrf(request, request.headers.get("x-csrf-token"))
        except PermissionError:
            raise HTTPException(403, "Sesión caducada, recarga la página")
    return u


def log(request, u, action, detail=""):
    audit(u["username"] if u else None, client_ip(request), action, detail)


def flash(request, msg, kind="ok"):
    request.session["flash"] = {"msg": msg, "kind": kind}


def go(path):
    return RedirectResponse(path, status_code=303)


def render(request, name, **ctx):
    ctx.update(user=getuser(request), csrf=csrf(request), flash=request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, ctx)


def has_users():
    return bool(one("SELECT 1 AS x FROM users LIMIT 1"))


def check_password(pw):
    if not isinstance(pw, str) or not 10 <= len(pw) <= 200:
        raise ValueError("La contraseña debe tener entre 10 y 200 caracteres")
    return ph.hash(pw)


def totp_at(secret, t):
    h = hmac.new(base64.b32decode(secret), struct.pack(">Q", int(t) // 30), "sha1").digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def totp_ok(secret, code):
    code = re.sub(r"\s", "", str(code or ""))
    return any(hmac.compare_digest(totp_at(secret, time.time() + d * 30), code) for d in (-1, 0, 1))


# ---------- acceso ----------
@app.get("/login")
def login_page(request: Request):
    if not has_users():
        return go("/configurar")
    return render(request, "login.html")


@app.post("/login")
def login_post(request: Request, username: str = Form(""), password: str = Form(""), code: str = Form(""), csrf_token: str = Form("")):
    try:
        check_csrf(request, csrf_token)
    except PermissionError:
        flash(request, "Sesión caducada, inténtalo de nuevo.", "err"); return go("/login")
    ip, uname = client_ip(request), username.strip().lower()[:64]
    keys = [((ip, uname), 5), ((ip, "*"), 15), (("*", uname), 20)]
    if blocked(keys):
        flash(request, "Demasiados intentos. Espera 10 minutos.", "err"); return go("/login")
    u = one("SELECT * FROM users WHERE username=?", (uname,))
    try:
        if not u or not u["active"] or len(password) > 200:
            raise VerifyMismatchError()
        ph.verify(u["pw_hash"], password)
        if u["totp"] and not totp_ok(u["totp"], code):
            raise VerifyMismatchError()
    except (VerifyMismatchError, InvalidHashError):
        register_fail([k for k, _ in keys])
        audit(uname, ip, "Acceso fallido")
        flash(request, "Usuario, contraseña o código incorrectos.", "err"); return go("/login")
    request.session.clear()
    request.session["uid"], request.session["sv"] = u["id"], u["sv"]
    ex("UPDATE users SET last_login=? WHERE id=?", (stamp(), u["id"]))
    audit(uname, ip, "Inicio de sesión")
    return go("/")


@app.get("/configurar")
def setup_page(request: Request):
    """Solo existe mientras no haya ningún usuario: crea la cuenta de administrador."""
    if has_users():
        return go("/login")
    return render(request, "setup.html")


@app.post("/configurar")
def setup_post(request: Request, username: str = Form(""), password: str = Form(""), code: str = Form(""), csrf_token: str = Form("")):
    if has_users():
        return go("/login")
    try:
        check_csrf(request, csrf_token)
    except PermissionError:
        flash(request, "Sesión caducada, inténtalo de nuevo.", "err"); return go("/configurar")
    keys = [((client_ip(request), "setup"), 5), (("*", "setup"), 30)]
    if blocked(keys):
        flash(request, "Demasiados intentos. Espera 10 minutos.", "err"); return go("/configurar")
    if not SETUP_CODE or not secrets.compare_digest(code.strip().encode(), SETUP_CODE.encode()):
        register_fail([k for k, _ in keys])
        flash(request, "Código de configuración incorrecto.", "err"); return go("/configurar")
    username = username.strip().lower()
    if not USER_RE.fullmatch(username):
        flash(request, "Usuario: 3-32 caracteres (letras, números, . _ -).", "err"); return go("/configurar")
    if not 10 <= len(password) <= 200:
        flash(request, "La contraseña debe tener entre 10 y 200 caracteres.", "err"); return go("/configurar")
    uid = ex("INSERT INTO users(username,pw_hash,created,role) VALUES(?,?,?,'admin')", (username, ph.hash(password), now().isoformat()))
    request.session.clear(); request.session["uid"], request.session["sv"] = uid, 0
    return go("/")


@app.post("/salir")
def logout(request: Request, csrf_token: str = Form("")):
    try:
        check_csrf(request, csrf_token)
    except PermissionError:
        return go("/")
    request.session.clear()
    return go("/login")


@app.get("/")
def home(request: Request):
    if not getuser(request):
        return go("/login")
    return render(request, "index.html")


# ---------- panel ----------
@app.get("/api/boot")
def api_boot(request: Request):
    u = need(request)
    return dict(user=dict(id=u["id"], username=u["username"], role=u["role"], twofa=bool(u["twofa"])), settings=settings(),
                plugins=plugins.installed(), docker=dockerapi.available(), files=files.available(),
                host=(metrics.snapshot().get("host") or {}).get("name", ""))


@app.get("/api/stats")
def api_stats(request: Request, h: int = 0):
    need(request)
    data = metrics.snapshot()
    if h:
        data["history"] = metrics.history()
    return JSONResponse(data)


def _status_file(name):
    try:
        with open(os.path.join(files.ROOT, "backups", name), encoding="utf-8") as f:
            p = f.read().split(None, 1)
        return dict(ok=p[0] == "OK", at=p[1].strip() if len(p) > 1 else "")
    except (OSError, IndexError):
        return None


@app.get("/api/overview")
def api_overview(request: Request):
    need(request)
    s, out = settings(), {}
    try:
        cs = dockerapi.containers()
        out["containers"] = dict(running=sum(c["state"] == "running" for c in cs), total=len(cs),
                                 stopped=[c["name"] for c in cs if c["state"] != "running"])
    except dockerapi.DockerError:
        out["containers"] = None
    if s["mod_backups"]:
        out["backups"] = dict(copia=_status_file("STATUS"), actualizacion=_status_file("UPDATE_STATUS"))
    out["automations"] = one("SELECT COUNT(*) AS n, SUM(enabled) AS on_ FROM automations")
    out["last_runs"] = q("SELECT name, at, ok, msg FROM runs ORDER BY id DESC LIMIT 5")
    return out


# ---------- aplicaciones ----------
PORT_RE = re.compile(r"host\.docker\.internal:(\d+)")


@app.get("/api/apps")
def api_apps(request: Request):
    need(request)
    try:
        cs = dockerapi.containers()
    except dockerapi.DockerError:
        cs = []
    groups, byport = {}, {}
    for c in cs:
        key = c["project"] or c["name"]
        groups.setdefault(key, []).append(dict(id=c["id"], name=c["name"], state=c["state"], status=c["status"], self=c["self"]))
        for p in c["ports"]:
            byport[p["public"]] = key
    cards, used = [], set()
    for s in metrics.services():
        m = PORT_RE.search(s["target"])
        key = s["project"] if s["project"] in groups else byport.get(int(m.group(1))) if m else None
        card = dict(key=key or f"check-{s['id']}", name=s["name"], link=s["link"], check=s, containers=groups.get(key, []) if key and key not in used else [])
        if key:
            used.add(key)
        cards.append(card)
    for key, items in groups.items():
        if key not in used:
            cards.append(dict(key=key, name=key, link="", check=None, containers=items))
    return dict(apps=cards, projects=sorted(groups))


@app.post("/api/apps")
def api_apps_save(request: Request, b: dict = Body(...)):
    u = need(request, "admin")
    name, kind, target = str(b.get("name", "")).strip()[:60], b.get("kind"), str(b.get("target", "")).strip()[:300]
    link, project = str(b.get("link", "")).strip()[:300], str(b.get("project", "")).strip()[:80]
    if not name or kind not in ("http", "tcp"):
        raise ValueError("Falta el nombre o el tipo")
    if kind == "http" and not re.match(r"^https?://\S+$", target):
        raise ValueError("La dirección debe empezar por http:// o https://")
    if kind == "tcp" and not re.match(r"^[A-Za-z0-9.-]+:\d{1,5}$", target):
        raise ValueError("Para TCP indica equipo:puerto")
    if link and not re.match(r"^https?://\S+$", link):
        raise ValueError("El enlace debe empezar por http:// o https://")
    if b.get("id"):
        ex("UPDATE apps SET name=?,kind=?,target=?,link=?,project=? WHERE id=?", (name, kind, target, link, project, int(b["id"])))
    else:
        ex("INSERT INTO apps(name,kind,target,link,project) VALUES(?,?,?,?,?)", (name, kind, target, link, project))
    metrics.recheck()
    log(request, u, "Aplicación guardada", name)
    return {"ok": True}


@app.delete("/api/apps/{app_id}")
def api_apps_del(request: Request, app_id: int):
    u = need(request, "admin")
    ex("DELETE FROM apps WHERE id=?", (app_id,))
    metrics.recheck()
    log(request, u, "Aplicación eliminada", app_id)
    return {"ok": True}


@app.post("/api/apps/group/{key}/{op}")
def api_apps_op(request: Request, key: str, op: str):
    u = need(request, "operador")
    targets = [c for c in dockerapi.containers() if (c["project"] or c["name"]) == key]
    if not targets or op not in dockerapi.OPS:
        raise ValueError("Aplicación u operación no válida")
    if op == "stop" and any(c["self"] for c in targets):
        raise ValueError("No se puede parar el propio panel desde el panel")
    for c in sorted(targets, key=lambda c: c["self"]):     # el propio panel, si toca, el último
        dockerapi.action(c["id"], op)
    log(request, u, f"Aplicación: {op}", key)
    return {"ok": True}


# ---------- docker ----------
@app.get("/api/docker/containers")
def api_containers(request: Request):
    need(request)
    return dict(containers=dockerapi.containers(), stats=dockerapi.stats(), version=dockerapi.version())


@app.get("/api/docker/containers/{ref}")
def api_container(request: Request, ref: str):
    need(request)
    return dockerapi.inspect(ref)


@app.get("/api/docker/containers/{ref}/logs")
def api_logs(request: Request, ref: str, tail: int = 200):
    need(request, "operador")
    return dict(text=dockerapi.logs(ref, tail))


@app.post("/api/docker/containers/{ref}/{op}")
def api_container_op(request: Request, ref: str, op: str):
    u = need(request, "operador")
    name = dockerapi.action(ref, op)
    log(request, u, f"Contenedor: {op}", name)
    return {"ok": True}


@app.get("/api/docker/resources")
def api_resources(request: Request):
    need(request)
    return dict(images=dockerapi.images(), volumes=dockerapi.volumes(), networks=dockerapi.networks())


@app.post("/api/docker/prune")
def api_prune(request: Request):
    u = need(request, "admin")
    n, freed = dockerapi.prune_images()
    log(request, u, "Limpieza de imágenes", f"{n} imágenes, {freed} bytes")
    return dict(deleted=n, freed=freed)


# ---------- archivos ----------
@app.get("/api/files")
def api_files(request: Request, path: str = ""):
    need(request, "admin")
    return files.listing(path)


@app.get("/api/files/view")
def api_file_view(request: Request, path: str):
    need(request, "admin")
    return files.view(path)


@app.get("/api/files/download")
def api_file_download(request: Request, path: str):
    u = need(request, "admin")
    full, rel = files.resolve(path)
    if not os.path.isfile(full):
        raise files.FileError("No es un archivo")
    log(request, u, "Descarga de archivo", rel)
    return FileResponse(full, filename=os.path.basename(full), media_type="application/octet-stream")


# ---------- terminal ----------
@app.post("/api/console")
def api_console(request: Request, b: dict = Body(...)):
    u = need(request, "operador")
    if not settings()["terminal"]:
        raise HTTPException(403, "La terminal está desactivada en Configuración")
    line = str(b.get("cmd", ""))[:300].strip()
    log(request, u, "Terminal", line)
    return dict(out=console.run(line, u))


# ---------- red ----------
@app.get("/api/net")
def api_net(request: Request):
    need(request)
    return dict(devices=netinfo.devices(), ports=netinfo.ports(), tailscale=netinfo.tailscale() if settings()["mod_tailscale"] else None, lan=settings()["lan"])


@app.post("/api/net/scan")
def api_net_scan(request: Request):
    u = need(request, "operador")
    if blocked([(("scan", "*"), 6)]):
        raise ValueError("Demasiados escaneos seguidos; espera unos minutos")
    register_fail([("scan", "*")])
    alive = netinfo.scan()
    log(request, u, "Escaneo de red", f"{alive} equipos responden")
    return dict(alive=alive)


@app.post("/api/net/device")
def api_net_device(request: Request, b: dict = Body(...)):
    need(request, "operador")
    mac = str(b.get("mac", "")).lower()
    if b.get("forget"):
        ex("DELETE FROM devices WHERE mac=?", (mac,))
    else:
        ex("UPDATE devices SET name=? WHERE mac=?", (str(b.get("name", "")).strip()[:40], mac))
    return {"ok": True}


# ---------- usuarios ----------
def _admins(except_id=None):
    return one("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1 AND id IS NOT ?", (except_id,))["n"]


@app.get("/api/users")
def api_users(request: Request):
    need(request, "admin")
    return dict(users=q("SELECT id, username, role, active, created, last_login, totp IS NOT NULL AS twofa FROM users ORDER BY id"))


@app.post("/api/users")
def api_user_new(request: Request, b: dict = Body(...)):
    u = need(request, "admin")
    name, role = str(b.get("username", "")).strip().lower(), b.get("role")
    if not USER_RE.fullmatch(name):
        raise ValueError("Usuario: 3-32 caracteres (letras, números, . _ -)")
    if role not in ROLES:
        raise ValueError("Rol no válido")
    if one("SELECT 1 AS x FROM users WHERE username=?", (name,)):
        raise ValueError("Ya existe un usuario con ese nombre")
    ex("INSERT INTO users(username,pw_hash,created,role) VALUES(?,?,?,?)", (name, check_password(b.get("password")), stamp(), role))
    log(request, u, "Usuario creado", f"{name} ({role})")
    return {"ok": True}


@app.post("/api/users/{uid}")
def api_user_edit(request: Request, uid: int, b: dict = Body(...)):
    u = need(request, "admin")
    t = one("SELECT * FROM users WHERE id=?", (uid,))
    if not t:
        raise ValueError("No existe ese usuario")
    role, active = b.get("role", t["role"]), int(bool(b.get("active", t["active"])))
    if role not in ROLES:
        raise ValueError("Rol no válido")
    if (role != "admin" or not active) and t["role"] == "admin" and t["active"] and not _admins(uid):
        raise ValueError("Tiene que quedar al menos un administrador activo")
    sv = t["sv"] + (1 if not active or role != t["role"] else 0)      # cambiar el rol o desactivar cierra sus sesiones
    ex("UPDATE users SET role=?, active=?, sv=? WHERE id=?", (role, active, sv, uid))
    if b.get("password"):
        ex("UPDATE users SET pw_hash=?, sv=sv+1 WHERE id=?", (check_password(b["password"]), uid))
    if b.get("reset_2fa"):
        ex("UPDATE users SET totp=NULL WHERE id=?", (uid,))
    if uid == u["id"]:
        request.session["sv"] = one("SELECT sv FROM users WHERE id=?", (uid,))["sv"]
    log(request, u, "Usuario modificado", f"{t['username']}: rol {role}, {'activo' if active else 'desactivado'}")
    return {"ok": True}


@app.delete("/api/users/{uid}")
def api_user_del(request: Request, uid: int):
    u = need(request, "admin")
    t = one("SELECT * FROM users WHERE id=?", (uid,))
    if not t or uid == u["id"]:
        raise ValueError("No puedes eliminar tu propia cuenta")
    if t["role"] == "admin" and t["active"] and not _admins(uid):
        raise ValueError("Tiene que quedar al menos un administrador activo")
    ex("DELETE FROM users WHERE id=?", (uid,))
    log(request, u, "Usuario eliminado", t["username"])
    return {"ok": True}


@app.post("/api/account/password")
def api_my_password(request: Request, b: dict = Body(...)):
    u = need(request)
    row = one("SELECT * FROM users WHERE id=?", (u["id"],))
    try:
        ph.verify(row["pw_hash"], str(b.get("current", ""))[:200])
    except (VerifyMismatchError, InvalidHashError):
        raise ValueError("La contraseña actual no es correcta")
    ex("UPDATE users SET pw_hash=?, sv=sv+1 WHERE id=?", (check_password(b.get("new")), u["id"]))
    request.session["sv"] = row["sv"] + 1          # esta sesión sigue; las demás se cierran
    log(request, u, "Cambio de contraseña")
    return {"ok": True}


@app.post("/api/account/2fa")
def api_my_2fa(request: Request, b: dict = Body(...)):
    u = need(request)
    step = b.get("step")
    if step == "start":
        secret = base64.b32encode(secrets.token_bytes(20)).decode()
        request.session["totp_pending"] = secret
        return dict(secret=secret, uri=f"otpauth://totp/{settings()['name']}:{u['username']}?secret={secret}&issuer={settings()['name']}")
    if step == "confirm":
        secret = request.session.get("totp_pending")
        if not secret or not totp_ok(secret, b.get("code")):
            raise ValueError("El código no coincide; comprueba la hora del móvil y vuelve a intentarlo")
        ex("UPDATE users SET totp=? WHERE id=?", (secret, u["id"]))
        request.session.pop("totp_pending", None)
        log(request, u, "Verificación en dos pasos activada")
        return {"ok": True}
    if step == "disable":
        row = one("SELECT * FROM users WHERE id=?", (u["id"],))
        try:
            ph.verify(row["pw_hash"], str(b.get("password", ""))[:200])
        except (VerifyMismatchError, InvalidHashError):
            raise ValueError("La contraseña no es correcta")
        ex("UPDATE users SET totp=NULL WHERE id=?", (u["id"],))
        log(request, u, "Verificación en dos pasos desactivada")
        return {"ok": True}
    raise ValueError("Paso no válido")


# ---------- automatizaciones ----------
@app.get("/api/automations")
def api_autos(request: Request):
    need(request)
    rows = q("SELECT * FROM automations ORDER BY id")
    for r in rows:
        r["trig"], r["action"] = json.loads(r["trig"]), json.loads(r["action"])
    try:
        names = [c["name"] for c in dockerapi.containers()]
    except dockerapi.DockerError:
        names = []
    return dict(items=rows, runs=q("SELECT name, at, ok, msg, by FROM runs ORDER BY id DESC LIMIT 30"), containers=names,
                apps=[dict(id=s["id"], name=s["name"]) for s in metrics.services()])


@app.post("/api/automations")
def api_auto_save(request: Request, b: dict = Body(...)):
    u = need(request, "admin")
    name = str(b.get("name", "")).strip()[:60]
    if not name or not isinstance(b.get("trig"), dict) or not isinstance(b.get("action"), dict):
        raise ValueError("Falta el nombre, el disparador o la acción")
    try:
        trig, action = automations.validate(b["trig"], b["action"])
    except (TypeError, KeyError):
        raise ValueError("Datos de la tarea no válidos")
    args = (name, json.dumps(trig), json.dumps(action), automations.next_run(trig))
    if b.get("id"):
        ex("UPDATE automations SET name=?, trig=?, action=?, next_run=? WHERE id=?", args + (int(b["id"]),))
    else:
        ex("INSERT INTO automations(name,trig,action,next_run,created) VALUES(?,?,?,?,?)", args + (stamp(),))
    log(request, u, "Automatización guardada", name)
    return {"ok": True}


@app.post("/api/automations/{aid}/{op}")
def api_auto_op(request: Request, aid: int, op: str):
    u = need(request, "operador" if op == "run" else "admin")
    a = one("SELECT * FROM automations WHERE id=?", (aid,))
    if not a:
        raise ValueError("No existe esa tarea")
    if op == "run":
        ok, msg = automations.run(a, u["username"])
        log(request, u, "Automatización ejecutada a mano", a["name"])
        return dict(ok=ok, msg=msg)
    if op == "toggle":
        on = 0 if a["enabled"] else 1
        ex("UPDATE automations SET enabled=?, next_run=? WHERE id=?", (on, automations.next_run(json.loads(a["trig"])) if on else None, aid))
    elif op == "delete":
        ex("DELETE FROM automations WHERE id=?", (aid,))
    else:
        raise ValueError("Operación no válida")
    log(request, u, f"Automatización: {op}", a["name"])
    return {"ok": True}


# ---------- plugins ----------
@app.get("/api/plugins")
def api_plugins(request: Request):
    need(request)
    return dict(installed=plugins.installed())


@app.post("/api/plugins/install")
def api_plugin_install(request: Request, file: UploadFile = File(...)):
    u = need(request, "admin")
    m = plugins.install(file.file.read(2 * 1024 * 1024))
    log(request, u, "Plugin instalado", m["id"])
    return m


@app.delete("/api/plugins/{pid}")
def api_plugin_del(request: Request, pid: str):
    u = need(request, "admin")
    plugins.remove(pid)
    log(request, u, "Plugin eliminado", pid)
    return {"ok": True}


@app.get("/api/plugins/ejemplo.zip")
def api_plugin_example(request: Request):
    need(request)
    return Response(plugins.example_zip(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="plugin-ejemplo.zip"'})


@app.get("/plugins/{pid}/")
def plugin_page(request: Request, pid: str):
    if not getuser(request):
        raise HTTPException(401)
    html = plugins.page(pid)
    if html is None:
        raise HTTPException(404)
    return Response(html, media_type="text/html; charset=utf-8")


# ---------- configuración ----------
@app.post("/api/settings")
def api_settings(request: Request, b: dict = Body(...)):
    u = need(request, "admin")
    clean = {}
    for k, v in b.items():
        if k not in DEFAULTS:
            continue
        d = DEFAULTS[k]
        if isinstance(d, bool):
            clean[k] = bool(v)
        elif isinstance(d, int):
            clean[k] = max(1, min(int(v), 110 if k == "temp_warn" else 100))
        elif k == "lan":
            net = ipaddress.ip_network(str(v).strip(), strict=False)
            if net.version != 4 or not net.is_private or net.num_addresses > 1024:
                raise ValueError("La red debe ser privada, IPv4 y de 1024 direcciones como mucho (p. ej. 192.168.1.0/24)")
            clean[k] = str(net)
        else:
            v = str(v).strip()[:40]
            if not v:
                raise ValueError("El nombre no puede quedar vacío")
            clean[k] = v
    for k, v in clean.items():
        set_setting(k, v)
    log(request, u, "Configuración cambiada", ", ".join(sorted(clean)))
    return settings()


@app.get("/api/audit")
def api_audit(request: Request):
    need(request, "admin")
    return dict(items=q("SELECT at, user, ip, action, detail FROM audit ORDER BY id DESC LIMIT 200"))
