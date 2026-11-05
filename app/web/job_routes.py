from flask import Blueprint, abort, render_template, request

from app.db import get_db
from app.services import archive_store, epub_store, jobs

bp = Blueprint("jobs", __name__, url_prefix="/jobs")


def _page(raw_value):
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 1


@bp.get("/")
def index():
    conn = get_db()
    page = _page(request.args.get("page"))
    rows, total = jobs.list_jobs(conn, page=page)
    pages = max(1, (total + jobs.PAGE_SIZE - 1) // jobs.PAGE_SIZE)
    return render_template(
        "jobs/list.html",
        jobs=rows,
        page=page,
        pages=pages,
        total=total,
        per_page=jobs.PAGE_SIZE,
    )


@bp.get("/<int:job_id>")
def detail(job_id):
    conn = get_db()
    job = jobs.get_job(conn, job_id)
    if job is None:
        abort(404)
    epub = epub_store.epub_for_job(conn, job_id)
    archive = archive_store.archive_for_job(conn, job_id)
    return render_template("jobs/detail.html", job=job, epub=epub, archive=archive)
