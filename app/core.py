import os, json, sqlite3, threading, datetime as dt
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DB = os.environ.get("DB_PATH", "/data/app.db")
_lock = threading.Lock()

ROLES = {"lector": 1, "operador": 2, "admin": 3}

# Ajustes del panel con su valor por defecto. Lo que no esté aquí no se puede guardar.
DEFAULTS = {
    "name": "SaiperrNexo",
    "cpu_warn": 75, "mem_warn": 80, "disk_warn": 80, "temp_warn": 70,
    "lan": "192.168.1.0/24",
    "terminal": True,
    "mod_backups": True, "mod_tailscale": True, "mod_sensors": True, "mod_battery": False,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, created TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS apps(id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL, link TEXT, project TEXT);
CREATE TABLE IF NOT EXISTS automations(id INTEGER PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER DEFAULT 1, trig TEXT NOT NULL, action TEXT NOT NULL,
  next_run TEXT, last_run TEXT, last_ok INTEGER, last_msg TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, auto_id INTEGER, name TEXT, at TEXT, ok INTEGER, msg TEXT, by TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT, user TEXT, ip TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS devices(mac TEXT PRIMARY KEY, name TEXT, hostname TEXT, ip TEXT, first_seen TEXT, last_seen TEXT);
"""
USER_COLS = {"role": "TEXT DEFAULT 'lector'", "active": "INTEGER DEFAULT 1", "last_login": "TEXT", "sv": "INTEGER DEFAULT 0", "totp": "TEXT"}


def now():
    return dt.datetime.now(TZ).replace(tzinfo=None)


def stamp():
    return now().isoformat(timespec="seconds")


def conn():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def q(sql, args=()):
    with _lock, conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def ex(sql, args=()):
    with _lock, conn() as c:
        return c.execute(sql, args).lastrowid


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    with _lock, conn() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        fresh = "role" not in have
        for col, decl in USER_COLS.items():
            if col not in have:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        if fresh:   # las cuentas que ya existían en el panel anterior eran de administrador
            c.execute("UPDATE users SET role='admin'")


# ---------- ajustes ----------
def settings():
    out = dict(DEFAULTS)
    for r in q("SELECT k, v FROM settings"):
        if r["k"] in DEFAULTS:
            try:
                out[r["k"]] = json.loads(r["v"])
            except ValueError:
                pass
    return out


def setting(k):
    return settings()[k]


def set_setting(k, v):
    if k in DEFAULTS:
        ex("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))


def audit(user, ip, action, detail=""):
    ex("INSERT INTO audit(at,user,ip,action,detail) VALUES(?,?,?,?,?)", (stamp(), user or "-", ip or "-", action, str(detail)[:300]))
    ex("DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - 2000")
