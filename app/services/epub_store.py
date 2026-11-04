import os
import re
import uuid
import zipfile

from app.db import execute, fetch_all, fetch_one
from app.timeutil import utcnow

PAGE_SIZE = 20
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


class EpubError(Exception):
    pass


def _sanitize_filename(raw_name):
    name = _ILLEGAL_FILENAME_RE.sub("_", raw_name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "知乎收藏"
    return name[:100]


def build_display_name(collection_name, date_str):
    return f"{_sanitize_filename(collection_name)}_{date_str}.epub"


def epub_dir(data_dir):
    return os.path.join(data_dir, "epubs")


def epub_path(data_dir, stored_name):
    name = stored_name or ""
    if not name or os.path.basename(name) != name or not name.endswith(".epub"):
        raise EpubError("EPUB 文件名不合法。")
    root = os.path.abspath(epub_dir(data_dir))
    path = os.path.abspath(os.path.join(root, name))
    if os.path.commonpath([root, path]) != root:
        raise EpubError("EPUB 路径不合法。")
    return path


def verify_epub(path):
    if not os.path.isfile(path):
        raise EpubError("EPUB 文件不存在。")
    if os.path.getsize(path) < 1024:
        raise EpubError("EPUB 文件过小，可能生成失败。")
    if not zipfile.is_zipfile(path):
        raise EpubError("生成的文件不是合法的 EPUB 压缩包。")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            try:
                mimetype = archive.read("mimetype").decode("ascii", "ignore").strip()
            except KeyError as exc:
                raise EpubError("EPUB 缺少 mimetype 文件。") from exc
            if mimetype != "application/epub+zip":
                raise EpubError("EPUB mimetype 不正确。")
            if not any(name.lower().endswith((".xhtml", ".html", ".htm")) for name in names):
                raise EpubError("EPUB 中没有正文页面。")
    except zipfile.BadZipFile as exc:
        raise EpubError("EPUB 压缩包损坏。") from exc


def store_epub(conn, data_dir, job_id, collection_name, display_name, temp_path):
    verify_epub(temp_path)
    os.makedirs(epub_dir(data_dir), mode=0o700, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.epub"
    final_path = epub_path(data_dir, stored_name)
    os.replace(temp_path, final_path)
    size = os.path.getsize(final_path)
    title = os.path.splitext(display_name)[0]
    try:
        cursor = execute(
            conn,
            """
            INSERT INTO epubs
                (job_id, collection_name, title, stored_name, display_name,
                 size_bytes, created_at, email_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                job_id,
                collection_name,
                title,
                stored_name,
                display_name,
                size,
                utcnow(),
            ),
        )
    except Exception:
        try:
            os.remove(final_path)
        except OSError:
            pass
        raise
    return {
        "id": cursor.lastrowid,
        "stored_name": stored_name,
        "path": final_path,
        "display_name": display_name,
        "size": size,
    }


def get_epub(conn, epub_id):
    return fetch_one(conn, "SELECT * FROM epubs WHERE id = ?", (epub_id,))


def epub_for_job(conn, job_id):
    return fetch_one(
        conn,
        "SELECT * FROM epubs WHERE job_id = ? ORDER BY id DESC LIMIT 1",
        (job_id,),
    )


def list_epubs(conn, page=1, per_page=PAGE_SIZE):
    total = fetch_one(conn, "SELECT COUNT(*) AS n FROM epubs")["n"]
    offset = max(0, (page - 1) * per_page)
    rows = fetch_all(
        conn,
        "SELECT * FROM epubs ORDER BY id DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    return rows, total


def delete_epub(conn, data_dir, epub_row):
    path = epub_path(data_dir, epub_row["stored_name"])
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise EpubError(f"删除 EPUB 文件失败: {exc}") from exc
    execute(conn, "DELETE FROM epubs WHERE id = ?", (epub_row["id"],))


def set_email_result(conn, epub_id, status, error=None, attempted=True):
    execute(
        conn,
        """
        UPDATE epubs
        SET email_status = ?,
            email_attempts = email_attempts + ?,
            last_email_at = ?,
            last_email_error = ?
        WHERE id = ?
        """,
        (
            status,
            1 if attempted else 0,
            utcnow() if attempted else None,
            (error or "")[:1000] or None,
            epub_id,
        ),
    )


def count_epubs(conn):
    row = fetch_one(conn, "SELECT COUNT(*) AS n FROM epubs")
    return row["n"] if row else 0


def total_epub_bytes(conn):
    row = fetch_one(conn, "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM epubs")
    return row["n"] if row else 0
