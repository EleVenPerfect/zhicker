import hmac
import threading
import time

from flask import current_app, redirect, request, session, url_for

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5
PUBLIC_ENDPOINTS = {"auth.login", "dashboard.healthz"}

_lock = threading.Lock()
_failures = {}


def _prune(bucket, now):
    return [stamp for stamp in bucket if now - stamp < LOGIN_WINDOW_SECONDS]


def _is_limited(key):
    now = time.monotonic()
    with _lock:
        bucket = _prune(_failures.get(key, []), now)
        _failures[key] = bucket
        return len(bucket) >= LOGIN_MAX_ATTEMPTS


def _record(key):
    now = time.monotonic()
    with _lock:
        bucket = _prune(_failures.get(key, []), now)
        bucket.append(now)
        _failures[key] = bucket


def is_rate_limited(ip, username):
    return _is_limited(f"ip:{ip}") or _is_limited(f"user:{username.lower()}")


def record_failure(ip, username):
    _record(f"ip:{ip}")
    _record(f"user:{username.lower()}")


def clear_failures(ip, username):
    with _lock:
        _failures.pop(f"ip:{ip}", None)
        _failures.pop(f"user:{username.lower()}", None)


def verify_credentials(username, password):
    expected_user = current_app.config["ADMIN_USERNAME"]
    expected_password = current_app.config["ADMIN_PASSWORD"]
    user_ok = hmac.compare_digest(username, expected_user)
    password_ok = hmac.compare_digest(password, expected_password)
    return user_ok and password_ok


def init_auth(app):
    @app.before_request
    def require_login():
        endpoint = request.endpoint
        if endpoint is None or endpoint in PUBLIC_ENDPOINTS or endpoint == "static":
            return None
        if not session.get("user"):
            return redirect(url_for("auth.login", next=request.path))
        return None
