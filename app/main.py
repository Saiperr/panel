import os, re, secrets, time, hashlib
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from .core import one, ex, init_db, now
from . import metrics

HERE = os.path.dirname(__file__)
init_db()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=os.environ["SECRET_KEY"], same_site="lax", session_cookie="panel_session",
                   https_only=os.environ.get("COOKIE_SECURE", "0") == "1", max_age=60 * 60 * 24 * 14)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
templates.env.globals["asset_v"] = hashlib.sha1(b"".join(open(os.path.join(HERE, "static", f), "rb").read() for f in ("style.css", "app.js"))).hexdigest()[:10]
ph = PasswordHasher()
SETUP_CODE = os.environ.get("SETUP_CODE", "")
FAILS, WINDOW = {}, 600


@app.middleware("http")
async def security(request: Request, call_next):
    try:
        if int(request.headers.get("content-length") or 0) > 16 * 1024:
            return PlainTextResponse("Petición demasiado grande", status_code=413)
    except ValueError:
        return PlainTextResponse("Petición no válida", status_code=400)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                               "script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    if not request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.on_event("startup")
def _start():
    metrics.start()


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
    return one("SELECT id, username FROM users WHERE id=?", (uid,)) if uid else None


def flash(request, msg, kind="ok"):
    request.session["flash"] = {"msg": msg, "kind": kind}


def go(path):
    return RedirectResponse(path, status_code=303)


def render(request, name, **ctx):
    ctx.update(user=getuser(request), csrf=csrf(request), flash=request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, ctx)


def has_users():
    return bool(one("SELECT 1 AS x FROM users LIMIT 1"))


# ---------- acceso ----------
@app.get("/login")
def login_page(request: Request):
    if not has_users():
        return go("/configurar")
    return render(request, "login.html")


@app.post("/login")
def login_post(request: Request, username: str = Form(""), password: str = Form(""), csrf_token: str = Form("")):
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
        if not u or len(password) > 200:
            raise VerifyMismatchError()
        ph.verify(u["pw_hash"], password)
    except (VerifyMismatchError, InvalidHashError):
        register_fail([k for k, _ in keys])
        flash(request, "Usuario o contraseña incorrectos.", "err"); return go("/login")
    request.session.clear()
    request.session["uid"] = u["id"]
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
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", username):
        flash(request, "Usuario: 3-32 caracteres (letras, números, . _ -).", "err"); return go("/configurar")
    if not 10 <= len(password) <= 200:
        flash(request, "La contraseña debe tener entre 10 y 200 caracteres.", "err"); return go("/configurar")
    uid = ex("INSERT INTO users(username,pw_hash,created) VALUES(?,?,?)", (username, ph.hash(password), now().isoformat()))
    request.session.clear(); request.session["uid"] = uid
    return go("/")


@app.post("/salir")
def logout(request: Request, csrf_token: str = Form("")):
    try:
        check_csrf(request, csrf_token)
    except PermissionError:
        return go("/")
    request.session.clear()
    return go("/login")


# ---------- panel ----------
@app.get("/")
def home(request: Request):
    if not getuser(request):
        return go("/login")
    return render(request, "index.html")


@app.get("/api/stats")
def api_stats(request: Request, h: int = 0):
    if not getuser(request):
        return JSONResponse({"error": "login"}, status_code=401)
    data = metrics.snapshot()
    if h:
        data["history"] = metrics.history()
    return JSONResponse(data)
