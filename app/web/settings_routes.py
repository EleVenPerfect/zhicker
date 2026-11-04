from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.db import get_db
from app.services import mailer, settings

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.get("/")
def index():
    conn = get_db()
    resolved = settings.resolve_smtp(conn, current_app.config)
    return render_template(
        "settings.html",
        fields=settings.SMTP_FIELDS,
        values=resolved["values"],
        sources=resolved["sources"],
        decrypt_failed=resolved["decrypt_failed"],
        smtp_configured=mailer.is_configured(resolved["values"]),
    )


@bp.post("/smtp")
def save():
    conn = get_db()
    try:
        settings.save_smtp(conn, current_app.config, request.form)
    except settings.SettingsError as exc:
        flash(str(exc), "error")
    else:
        flash("SMTP 配置已保存。", "success")
    return redirect(url_for("settings.index"))


@bp.post("/smtp/reset")
def reset():
    settings.reset_smtp(get_db())
    flash("已清除 Web 页面保存的邮箱配置，恢复使用环境变量。", "success")
    return redirect(url_for("settings.index"))


@bp.post("/smtp/test")
def test():
    conn = get_db()
    resolved = settings.resolve_smtp(conn, current_app.config)
    if resolved["decrypt_failed"]:
        flash("SMTP 密码解密失败，请重新填写密码并保存。", "error")
        return redirect(url_for("settings.index"))
    if not mailer.is_configured(resolved["values"]):
        flash("SMTP 配置不完整，请先填写主机、发件地址和收件邮箱并保存。", "error")
        return redirect(url_for("settings.index"))

    ok, error = mailer.send_test(resolved["values"])
    if ok:
        flash(f"测试邮件已发送到 {resolved['values']['to_addr']}，请检查收件箱。", "success")
    else:
        flash(f"测试邮件发送失败：{error}", "error")
    return redirect(url_for("settings.index"))
