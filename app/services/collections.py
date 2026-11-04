import re
import sqlite3

from app.db import execute, fetch_all, fetch_one
from app.timeutil import utcnow

COLLECTION_URL_RE = re.compile(
    r"^https?://(?:www\.)?zhihu\.com/collection/(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class CollectionError(ValueError):
    pass


class DuplicateCollection(Exception):
    pass


class CollectionInUse(Exception):
    pass


def normalize_collection_url(raw_url):
    url = (raw_url or "").strip()
    match = COLLECTION_URL_RE.match(url)
    if not match:
        raise CollectionError(
            "收藏夹地址格式不正确，应形如 https://www.zhihu.com/collection/123456789"
        )
    collection_id = match.group(1)
    return f"https://www.zhihu.com/collection/{collection_id}", collection_id


def sanitize_collection_name(raw_name, collection_id):
    name = _CONTROL_RE.sub("", raw_name or "").strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = f"收藏夹_{collection_id}"
    return name[:100]


def list_collections(conn):
    return fetch_all(
        conn,
        """
        SELECT c.*,
            (SELECT j.status FROM jobs j
             WHERE j.collection_id = c.id ORDER BY j.id DESC LIMIT 1) AS last_status,
            (SELECT j.id FROM jobs j
             WHERE j.collection_id = c.id ORDER BY j.id DESC LIMIT 1) AS last_job_id,
            (SELECT j.created_at FROM jobs j
             WHERE j.collection_id = c.id ORDER BY j.id DESC LIMIT 1) AS last_job_at
        FROM collections c
        ORDER BY c.id DESC
        """,
    )


def get_collection(conn, collection_id):
    return fetch_one(conn, "SELECT * FROM collections WHERE id = ?", (collection_id,))


def create_collection(conn, raw_name, raw_url):
    url, collection_id = normalize_collection_url(raw_url)
    name = sanitize_collection_name(raw_name, collection_id)
    now = utcnow()
    try:
        cursor = execute(
            conn,
            "INSERT INTO collections (name, url, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, url, now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateCollection("该收藏夹地址已经存在。") from exc
    return cursor.lastrowid


def update_collection(conn, collection_id, raw_name, raw_url):
    url, derived_id = normalize_collection_url(raw_url)
    name = sanitize_collection_name(raw_name, derived_id)
    try:
        cursor = execute(
            conn,
            "UPDATE collections SET name = ?, url = ?, updated_at = ? WHERE id = ?",
            (name, url, utcnow(), collection_id),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateCollection("该收藏夹地址已经存在。") from exc
    return cursor.rowcount > 0


def has_active_job(conn, collection_id):
    row = fetch_one(
        conn,
        """
        SELECT 1 FROM jobs
        WHERE collection_id = ? AND status IN ('queued', 'running')
        LIMIT 1
        """,
        (collection_id,),
    )
    return row is not None


def delete_collection(conn, collection_id):
    if has_active_job(conn, collection_id):
        raise CollectionInUse("该收藏夹还有排队或运行中的任务，暂时不能删除。")
    execute(conn, "DELETE FROM collections WHERE id = ?", (collection_id,))


def count_collections(conn):
    row = fetch_one(conn, "SELECT COUNT(*) AS n FROM collections")
    return row["n"] if row else 0
