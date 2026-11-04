from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.db import get_db
from app.services import collections, cookies, jobs

bp = Blueprint("collections", __name__, url_prefix="/collections")


@bp.get("/")
def index():
    rows = collections.list_collections(get_db())
    return render_template("collections/list.html", collections=rows)


@bp.route("/new", methods=["GET", "POST"])
def new():
    if request.method == "POST":
        try:
            collections.create_collection(
                get_db(),
                request.form.get("name", ""),
                request.form.get("url", ""),
            )
        except (collections.CollectionError, collections.DuplicateCollection) as exc:
            flash(str(exc), "error")
            return render_template(
                "collections/form.html",
                collection=None,
                form=request.form,
            )
        flash("收藏夹已添加。", "success")
        return redirect(url_for("collections.index"))
    return render_template("collections/form.html", collection=None, form=None)


@bp.route("/<int:collection_id>/edit", methods=["GET", "POST"])
def edit(collection_id):
    conn = get_db()
    collection = collections.get_collection(conn, collection_id)
    if collection is None:
        abort(404)

    if request.method == "POST":
        try:
            updated = collections.update_collection(
                conn,
                collection_id,
                request.form.get("name", ""),
                request.form.get("url", ""),
            )
        except (collections.CollectionError, collections.DuplicateCollection) as exc:
            flash(str(exc), "error")
            return render_template(
                "collections/form.html",
                collection=collection,
                form=request.form,
            )
        if not updated:
            abort(404)
        flash("收藏夹已更新。", "success")
        return redirect(url_for("collections.index"))

    return render_template("collections/form.html", collection=collection, form=None)


@bp.post("/<int:collection_id>/delete")
def delete(collection_id):
    conn = get_db()
    collection = collections.get_collection(conn, collection_id)
    if collection is None:
        abort(404)
    try:
        collections.delete_collection(conn, collection_id)
    except collections.CollectionInUse as exc:
        flash(str(exc), "error")
    else:
        flash("收藏夹已删除，历史任务和 EPUB 仍然保留。", "success")
    return redirect(url_for("collections.index"))


@bp.post("/<int:collection_id>/run")
def run(collection_id):
    conn = get_db()
    collection = collections.get_collection(conn, collection_id)
    if collection is None:
        abort(404)

    cookie_state = cookies.get_cookie_state(conn, current_app.config["SECRET_KEY"])
    if cookie_state["decrypt_failed"] or not cookie_state["configured"]:
        flash("请先在 Cookie 页面导入有效的知乎 Cookie。", "error")
        return redirect(url_for("cookies.index"))

    try:
        job_id = jobs.create_job(conn, collection)
    except jobs.ActiveJobExists as exc:
        flash(str(exc), "error")
        return redirect(url_for("collections.index"))

    worker = current_app.extensions["worker"]
    if worker.submit(job_id):
        flash(f"任务 #{job_id} 已加入下载队列。", "success")
    else:
        flash(f"任务 #{job_id} 已创建，但后台线程正在停止，服务重启后会继续执行。", "info")
    return redirect(url_for("jobs.detail", job_id=job_id))
