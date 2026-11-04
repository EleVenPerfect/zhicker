from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import auth
from app.csrf import get_csrf_token

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("dashboard.index"))

    next_url = request.args.get("next", "")
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = request.remote_addr or "unknown"

        if auth.is_rate_limited(ip, username):
            flash("登录失败次数过多，请 15 分钟后再试。", "error")
            return render_template("login.html")

        if auth.verify_credentials(username, password):
            auth.clear_failures(ip, username)
            session.clear()
            session["user"] = username
            session.permanent = True
            get_csrf_token()
            if (
                not next_url.startswith("/")
                or next_url.startswith("//")
                or "\\" in next_url
            ):
                next_url = url_for("dashboard.index")
            return redirect(next_url)

        auth.record_failure(ip, username)
        flash("用户名或密码错误。", "error")
        return render_template("login.html")

    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    flash("已退出登录。", "success")
    return redirect(url_for("auth.login"))
