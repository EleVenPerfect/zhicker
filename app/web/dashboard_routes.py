from flask import Blueprint, current_app, render_template

from app.db import get_db
from app.services import collections, cookies, epub_store, jobs, mailer, settings

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    conn = get_db()
    config = current_app.config
    smtp = settings.resolve_smtp(conn, config)
    cookie_state = cookies.get_cookie_state(conn, config["SECRET_KEY"])
    status_counts = jobs.count_by_status(conn)

    return render_template(
        "dashboard.html",
        collection_count=collections.count_collections(conn),
        job_count=jobs.count_jobs(conn),
        status_counts=status_counts,
        epub_count=epub_store.count_epubs(conn),
        epub_bytes=epub_store.total_epub_bytes(conn),
        active_jobs=jobs.list_active_jobs(conn, limit=5),
        recent_jobs=jobs.list_recent_jobs(conn, limit=8),
        smtp_configured=mailer.is_configured(smtp["values"]),
        smtp_decrypt_failed=smtp["decrypt_failed"],
        cookie_state=cookie_state,
        stub_mode=config["PIPELINE_STUB"],
    )


@bp.get("/healthz")
def healthz():
    try:
        get_db().execute("SELECT 1").fetchone()
    except Exception:
        return "database unavailable", 503

    worker = current_app.extensions.get("worker")
    if worker is None or not worker.is_alive():
        return "worker unavailable", 503
    return "ok", 200
