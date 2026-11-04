from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.db import get_db
from app.services import collections, cookies

bp = Blueprint("cookies", __name__, url_prefix="/cookies")


@bp.get("/")
def index():
    conn = get_db()
    state = cookies.get_cookie_state(conn, current_app.config["SECRET_KEY"])
    return render_template(
        "cookies.html",
        state=state,
        collections=collections.list_collections(conn),
    )


@bp.post("/import")
def import_cookies():
    conn = get_db()
    try:
        parsed = cookies.parse_cookie_input(request.form.get("cookie_text", ""))
        merged = cookies.save_cookies(
            conn,
            current_app.config["SECRET_KEY"],
            parsed,
            replace=(request.form.get("mode") == "replace"),
        )
    except cookies.CookieError as exc:
        flash(str(exc), "error")
        return redirect(url_for("cookies.index"))

    missing = cookies.missing_critical_cookies(merged)
    message = f"已导入 {len(parsed)} 个 Cookie，当前共 {len(merged)} 个。"
    if missing:
        message += f" 警告：缺少关键字段 {', '.join(missing)}，抓取可能失败。"
        flash(message, "info")
    else:
        flash(message, "success")
    return redirect(url_for("cookies.index"))


@bp.post("/clear")
def clear():
    cookies.clear_cookies(get_db())
    flash("已清除保存的 Cookie。", "success")
    return redirect(url_for("cookies.index"))


@bp.post("/test")
def test():
    conn = get_db()
    stored = cookies.load_cookies(conn, current_app.config["SECRET_KEY"])
    if not stored:
        flash("尚未保存有效的 Cookie，无法测试。", "error")
        return redirect(url_for("cookies.index"))

    rows = collections.list_collections(conn)
    if not rows:
        flash("请先添加一个收藏夹，再用它测试 Cookie。", "error")
        return redirect(url_for("cookies.index"))

    collection_id = request.form.get("collection_id", type=int)
    collection = None
    if collection_id:
        collection = collections.get_collection(conn, collection_id)
    if collection is None:
        collection = rows[0]

    result = cookies.test_cookies(conn, collection["url"], stored)
    flash(result["message"], "success" if result["ok"] else "error")
    return redirect(url_for("cookies.index"))
