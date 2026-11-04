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
from app.services import epub_store, jobs, mailer, settings
from app.timeutil import format_localtime, utcnow

bp = Blueprint("epubs", __name__, url_prefix="/epubs")


def _page(raw_value):
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 1


@bp.get("/")
def index():
    conn = get_db()
    page = _page(request.args.get("page"))
    rows, total = epub_store.list_epubs(conn, page=page)
    pages = max(1, (total + epub_store.PAGE_SIZE - 1) // epub_store.PAGE_SIZE)
    smtp = settings.resolve_smtp(conn, current_app.config)
    return render_template(
        "epubs/list.html",
        epubs=rows,
        page=page,
        pages=pages,
        total=total,
        per_page=epub_store.PAGE_SIZE,
        smtp_configured=mailer.is_configured(smtp["values"]),
    )


@bp.get("/<int:epub_id>/download")
def download(epub_id):
    conn = get_db()
    row = epub_store.get_epub(conn, epub_id)
    if row is None:
        abort(404)
    try:
        path = epub_store.epub_path(current_app.config["DATA_DIR"], row["stored_name"])
    except epub_store.EpubError:
        abort(404)
    if not os.path.isfile(path):
        abort(404, description="EPUB 文件已经不存在。")
    return send_file(
        path,
        as_attachment=True,
        download_name=row["display_name"],
        mimetype="application/epub+zip",
    )


@bp.post("/<int:epub_id>/delete")
def delete(epub_id):
    conn = get_db()
    row = epub_store.get_epub(conn, epub_id)
    if row is None:
        abort(404)
    try:
        epub_store.delete_epub(conn, current_app.config["DATA_DIR"], row)
    except epub_store.EpubError as exc:
        flash(str(exc), "error")
    else:
        flash("EPUB 已删除。", "success")
    return redirect(url_for("epubs.index"))


@bp.post("/<int:epub_id>/resend")
def resend(epub_id):
    conn = get_db()
    config = current_app.config
    row = epub_store.get_epub(conn, epub_id)
    if row is None:
        abort(404)

    resolved = settings.resolve_smtp(conn, config)
    values = resolved["values"]
    if resolved["decrypt_failed"]:
        message = "SMTP 密码解密失败，请到设置页重新保存 SMTP 配置。"
        epub_store.set_email_result(conn, epub_id, "failed", message)
        flash(message, "error")
        return redirect(url_for("epubs.index"))

    if not mailer.is_configured(values):
        flash("SMTP 尚未配置完整，请先到设置页填写邮箱信息。", "error")
        return redirect(url_for("epubs.index"))

    try:
        path = epub_store.epub_path(config["DATA_DIR"], row["stored_name"])
        with open(path, "rb") as handle:
            epub_bytes = handle.read()
    except (epub_store.EpubError, OSError) as exc:
        message = f"读取 EPUB 文件失败: {exc}"
        epub_store.set_email_result(conn, epub_id, "failed", message)
        flash(message, "error")
        return redirect(url_for("epubs.index"))

    job = jobs.get_job(conn, row["job_id"]) if row["job_id"] else None
    md_count = job["md_count"] if job and job["md_count"] is not None else 0
    date_label = format_localtime(
        utcnow(), config["APP_TIMEZONE"], "%Y-%m-%d"
    )

    ok, error = mailer.send_epub(
        values,
        epub_bytes,
        row["display_name"],
        row["collection_name"],
        md_count,
        date_label,
    )
    if ok:
        epub_store.set_email_result(conn, epub_id, "sent")
        flash(f"EPUB 已重新发送到 {values['to_addr']}。", "success")
    else:
        epub_store.set_email_result(conn, epub_id, "failed", error)
        flash(f"发送失败：{error}", "error")
    return redirect(url_for("epubs.index"))
