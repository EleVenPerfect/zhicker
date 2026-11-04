import sqlite3

from app.db import execute, fetch_all, fetch_one
from app.timeutil import utcnow

PAGE_SIZE = 20


class ActiveJobExists(Exception):
    pass


def create_job(conn, collection):
    now = utcnow()
    try:
        cursor = execute(
            conn,
            """
            INSERT INTO jobs
                (collection_id, collection_name, collection_url, status, stage, created_at)
            VALUES (?, ?, ?, 'queued', 'queued', ?)
            """,
            (collection["id"], collection["name"], collection["url"], now),
        )
    except sqlite3.IntegrityError as exc:
        raise ActiveJobExists("该收藏夹已有排队或运行中的任务。") from exc
    return cursor.lastrowid


def claim_job(conn, job_id):
    cursor = execute(
        conn,
        """
        UPDATE jobs
        SET status = 'running', stage = 'preparing', started_at = ?
        WHERE id = ? AND status = 'queued'
        """,
        (utcnow(), job_id),
    )
    return cursor.rowcount == 1


def set_stage(conn, job_id, stage):
    execute(conn, "UPDATE jobs SET stage = ? WHERE id = ?", (stage, job_id))


def set_md_count(conn, job_id, md_count):
    execute(conn, "UPDATE jobs SET md_count = ? WHERE id = ?", (md_count, job_id))


def set_log(conn, job_id, log_text):
    execute(conn, "UPDATE jobs SET log_text = ? WHERE id = ?", (log_text, job_id))


def mark_success(conn, job_id, md_count, log_text):
    execute(
        conn,
        """
        UPDATE jobs
        SET status = 'success', stage = 'done', finished_at = ?,
            md_count = ?, error = NULL, log_text = ?
        WHERE id = ?
        """,
        (utcnow(), md_count, log_text, job_id),
    )


def mark_failed(conn, job_id, error, log_text=None):
    execute(
        conn,
        """
        UPDATE jobs
        SET status = 'failed', stage = 'failed', finished_at = ?,
            error = ?, log_text = COALESCE(?, log_text)
        WHERE id = ?
        """,
        (utcnow(), error[:1000], log_text, job_id),
    )


def get_job(conn, job_id):
    return fetch_one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))


def list_jobs(conn, page=1, per_page=PAGE_SIZE):
    total = fetch_one(conn, "SELECT COUNT(*) AS n FROM jobs")["n"]
    offset = max(0, (page - 1) * per_page)
    rows = fetch_all(
        conn,
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    return rows, total


def list_recent_jobs(conn, limit=8):
    return fetch_all(conn, "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))


def list_active_jobs(conn, limit=10):
    return fetch_all(
        conn,
        "SELECT * FROM jobs WHERE status IN ('queued', 'running') ORDER BY id ASC LIMIT ?",
        (limit,),
    )


def list_queued_ids(conn):
    return [row["id"] for row in fetch_all(conn, "SELECT id FROM jobs WHERE status = 'queued' ORDER BY id ASC")]


def count_jobs(conn):
    row = fetch_one(conn, "SELECT COUNT(*) AS n FROM jobs")
    return row["n"] if row else 0


def count_by_status(conn):
    rows = fetch_all(conn, "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    result = {row["status"]: row["n"] for row in rows}
    for key in ("queued", "running", "success", "failed"):
        result.setdefault(key, 0)
    return result
