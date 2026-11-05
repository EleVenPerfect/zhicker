import os
import tarfile
import uuid

from app.db import execute, fetch_all, fetch_one
from app.services.epub_store import sanitize_filename
from app.timeutil import utcnow

PAGE_SIZE = 20
ARCHIVE_SUFFIX = ".tar.gz"


class ArchiveError(Exception):
    pass


def build_display_name(collection_name, date_str):
    return f"{sanitize_filename(collection_name)}_{date_str}{ARCHIVE_SUFFIX}"


def archives_dir(data_dir):
    return os.path.join(data_dir, "archives")


def archive_path(data_dir, stored_name):
    name = stored_name or ""
    if not name or os.path.basename(name) != name or not name.endswith(ARCHIVE_SUFFIX):
        raise ArchiveError("原始数据归档文件名不合法。")
    root = os.path.abspath(archives_dir(data_dir))
    path = os.path.abspath(os.path.join(root, name))
    if os.path.commonpath([root, path]) != root:
        raise ArchiveError("原始数据归档路径不合法。")
    return path


def create_archive(source_dir, image_dir, output_path):
    if not os.path.isdir(source_dir):
        raise ArchiveError("原始数据目录不存在。")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    try:
        with tarfile.open(output_path, "w:gz") as archive:
            archive.add(source_dir, arcname="source")
            if os.path.isdir(image_dir):
                archive.add(image_dir, arcname="img")
    except (tarfile.TarError, OSError) as exc:
        _remove_quietly(output_path)
        raise ArchiveError(f"打包原始数据失败: {exc}") from exc
    return output_path


def verify_archive(path):
    if not os.path.isfile(path):
        raise ArchiveError("原始数据归档不存在。")
    if os.path.getsize(path) < 1:
        raise ArchiveError("原始数据归档为空。")
    if not tarfile.is_tarfile(path):
        raise ArchiveError("原始数据归档不是合法的 tar.gz 文件。")
    try:
        with tarfile.open(path, "r:gz") as archive:
            has_markdown = any(
                member.name.startswith("source/") and member.name.endswith(".md")
                for member in archive.getmembers()
            )
    except (tarfile.TarError, OSError) as exc:
        raise ArchiveError("原始数据归档损坏。") from exc
    if not has_markdown:
        raise ArchiveError("原始数据归档中没有 Markdown 文件。")


def store_archive(conn, data_dir, job_id, collection_name, display_name, temp_path):
    verify_archive(temp_path)
    os.makedirs(archives_dir(data_dir), mode=0o700, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ARCHIVE_SUFFIX}"
    final_path = archive_path(data_dir, stored_name)
    os.replace(temp_path, final_path)
    size = os.path.getsize(final_path)
    title = (
        display_name[: -len(ARCHIVE_SUFFIX)]
        if display_name.endswith(ARCHIVE_SUFFIX)
        else display_name
    )
    try:
        cursor = execute(
            conn,
            """
            INSERT INTO archives
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
        _remove_quietly(final_path)
        raise
    return {
        "id": cursor.lastrowid,
        "stored_name": stored_name,
        "path": final_path,
        "display_name": display_name,
        "size": size,
    }


def get_archive(conn, archive_id):
    return fetch_one(conn, "SELECT * FROM archives WHERE id = ?", (archive_id,))


def archive_for_job(conn, job_id):
    return fetch_one(
        conn,
        "SELECT * FROM archives WHERE job_id = ? ORDER BY id DESC LIMIT 1",
        (job_id,),
    )


def list_archives(conn, page=1, per_page=PAGE_SIZE):
    total = fetch_one(conn, "SELECT COUNT(*) AS n FROM archives")["n"]
    offset = max(0, (page - 1) * per_page)
    rows = fetch_all(
        conn,
        "SELECT * FROM archives ORDER BY id DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    return rows, total


def delete_archive(conn, data_dir, archive_row):
    path = archive_path(data_dir, archive_row["stored_name"])
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ArchiveError(f"删除原始数据归档失败: {exc}") from exc
    execute(conn, "DELETE FROM archives WHERE id = ?", (archive_row["id"],))


def set_email_result(conn, archive_id, status, error=None, attempted=True):
    execute(
        conn,
        """
        UPDATE archives
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
            archive_id,
        ),
    )


def count_archives(conn):
    row = fetch_one(conn, "SELECT COUNT(*) AS n FROM archives")
    return row["n"] if row else 0


def total_archive_bytes(conn):
    row = fetch_one(conn, "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM archives")
    return row["n"] if row else 0


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass
