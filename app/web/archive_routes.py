import os

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from app.db import get_db
from app.services import archive_store, jobs, mailer, settings
from app.timeutil import format_localtime, utcnow

bp = Blueprint("archives", __name__, url_prefix="/archives")


def _page(raw_value):
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 1


@bp.get("/")
def index():
    conn = get_db()
    page = _page(request.args.get("page"))
    rows, total = archive_store.list_archives(conn, page=page)
    pages = max(
        1, (total + archive_store.PAGE_SIZE - 1) // archive_store.PAGE_SIZE
    )
    smtp = settings.resolve_smtp(conn, current_app.config)
    return render_template(
        "archives/list.html",
        archives=rows,
        page=page,
        pages=pages,
        total=total,
        per_page=archive_store.PAGE_SIZE,
        smtp_configured=mailer.is_configured(smtp["values"]),
    )


@bp.get("/<int:archive_id>/download")
def download(archive_id):
    conn = get_db()
    row = archive_store.get_archive(conn, archive_id)
    if row is None:
        abort(404)
    try:
        path = archive_store.archive_path(
            current_app.config["DATA_DIR"], row["stored_name"]
        )
    except archive_store.ArchiveError:
        abort(404)
    if not os.path.isfile(path):
        abort(404, description="原始数据归档已经不存在。")
    return send_file(
        path,
        as_attachment=True,
        download_name=row["display_name"],
        mimetype="application/gzip",
    )


@bp.post("/<int:archive_id>/delete")
def delete(archive_id):
    conn = get_db()
    row = archive_store.get_archive(conn, archive_id)
    if row is None:
        abort(404)
    try:
        archive_store.delete_archive(conn, current_app.config["DATA_DIR"], row)
    except archive_store.ArchiveError as exc:
        flash(str(exc), "error")
    else:
        flash("原始数据归档已删除。", "success")
    return redirect(url_for("archives.index"))


@bp.post("/<int:archive_id>/resend")
def resend(archive_id):
    conn = get_db()
    config = current_app.config
    row = archive_store.get_archive(conn, archive_id)
    if row is None:
        abort(404)

    resolved = settings.resolve_smtp(conn, config)
    values = resolved["values"]
    if resolved["decrypt_failed"]:
        message = "SMTP 密码解密失败，请到设置页重新保存 SMTP 配置。"
        archive_store.set_email_result(conn, archive_id, "failed", message)
        flash(message, "error")
        return redirect(url_for("archives.index"))

    if not mailer.is_configured(values):
        flash("SMTP 尚未配置完整，请先到设置页填写邮箱信息。", "error")
        return redirect(url_for("archives.index"))

    try:
        path = archive_store.archive_path(config["DATA_DIR"], row["stored_name"])
        with open(path, "rb") as handle:
            archive_bytes = handle.read()
    except (archive_store.ArchiveError, OSError) as exc:
        message = f"读取原始数据归档失败: {exc}"
        archive_store.set_email_result(conn, archive_id, "failed", message)
        flash(message, "error")
        return redirect(url_for("archives.index"))

    job = jobs.get_job(conn, row["job_id"]) if row["job_id"] else None
    md_count = job["md_count"] if job and job["md_count"] is not None else 0
    date_label = format_localtime(utcnow(), config["APP_TIMEZONE"], "%Y-%m-%d")

    ok, error = mailer.send_archive(
        values,
        archive_bytes,
        row["display_name"],
        row["collection_name"],
        md_count,
        date_label,
    )
    if ok:
        archive_store.set_email_result(conn, archive_id, "sent")
        flash(f"原始数据已重新发送到 {values['to_addr']}。", "success")
    else:
        archive_store.set_email_result(conn, archive_id, "failed", error)
        flash(f"发送失败：{error}", "error")
    return redirect(url_for("archives.index"))
