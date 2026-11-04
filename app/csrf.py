import hmac
import secrets

from flask import abort, request, session


def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def init_csrf(app):
    @app.before_request
    def protect_csrf():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        expected = session.get("_csrf_token", "")
        provided = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        if not expected or not provided or not hmac.compare_digest(expected, provided):
            abort(400, description="CSRF 校验失败，请刷新页面后重试。")
        return None

    app.jinja_env.globals["csrf_token"] = get_csrf_token
