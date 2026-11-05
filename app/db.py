import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

from .config import ensure_data_dirs

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def db_session(path):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(app):
    ensure_data_dirs(app.config["DATA_DIR"])
    conn = connect(app.config["DB_PATH"])
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        # schema.sql 目前全部是 IF NOT EXISTS，v1 库可安全重放补出 v2 新增的表。
        if version < 2:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute("PRAGMA user_version = 2")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.commit()
    finally:
        conn.close()


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def fetch_all(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def fetch_one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def execute(conn, sql, params=(), commit=True):
    cursor = conn.execute(sql, params)
    if commit:
        conn.commit()
    return cursor
