import os, sqlite3, threading, datetime as dt
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DB = os.environ.get("DB_PATH", "/data/app.db")
_lock = threading.Lock()


def now():
    return dt.datetime.now(TZ).replace(tzinfo=None)


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
        c.executescript("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, created TEXT);")
