import os
from datetime import timedelta
from zoneinfo import ZoneInfo

SMTP_SECURITY_MODES = ("starttls", "ssl", "none")
PIPELINE_STUB_MODES = ("off", "success", "empty", "fail")

PLACEHOLDER_SECRETS = {
    "",
    "change-me",
    "please-change-me",
    "请替换为随机字符串",
    "your-secret-key",
}


def _env(name, default=""):
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _env_raw(name, default=""):
    value = os.environ.get(name)
    return default if value is None else value


def _env_bool(name, default=False):
    value = _env(name)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    value = _env(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"环境变量 {name} 必须是整数，当前值: {value}") from exc


def config_from_env():
    data_dir = os.path.abspath(_env("DATA_DIR", "/data"))
    app_timezone = _env("APP_TIMEZONE", _env("TZ", "Asia/Shanghai")) or "Asia/Shanghai"
    session_hours = _env_int("SESSION_LIFETIME_HOURS", 12)
    return {
        "SECRET_KEY": _env("SECRET_KEY"),
        "ADMIN_USERNAME": _env("ADMIN_USERNAME", "admin") or "admin",
        "ADMIN_PASSWORD": _env_raw("ADMIN_PASSWORD"),
        "DATA_DIR": data_dir,
        "DB_PATH": os.path.join(data_dir, "app.db"),
        "PORT": _env_int("PORT", 8080),
        "TZ": _env("TZ", "Asia/Shanghai") or "Asia/Shanghai",
        "APP_TIMEZONE": app_timezone,
        "SESSION_COOKIE_SECURE": _env_bool("SESSION_COOKIE_SECURE", False),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_LIFETIME_HOURS": session_hours,
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=session_hours),
        "SMTP_HOST": _env("SMTP_HOST"),
        "SMTP_PORT": _env_int("SMTP_PORT", 587),
        "SMTP_SECURITY": (_env("SMTP_SECURITY", "starttls") or "starttls").lower(),
        "SMTP_USERNAME": _env("SMTP_USERNAME"),
        "SMTP_PASSWORD": _env_raw("SMTP_PASSWORD"),
        "SMTP_FROM": _env("SMTP_FROM"),
        "SMTP_FROM_NAME": _env("SMTP_FROM_NAME", "知乎收藏") or "知乎收藏",
        "SMTP_TO": _env("SMTP_TO"),
        "SMTP_TIMEOUT_SECONDS": 30,
        "COLLECT_TIMEOUT_SECONDS": 1800,
        "EPUB_TIMEOUT_SECONDS": 600,
        "JOB_LOG_MAX_BYTES": 65536,
        "PIPELINE_STUB": (_env("PIPELINE_STUB", "off") or "off").lower(),
        "MAX_CONTENT_LENGTH": 1024 * 1024,
        "TESTING": False,
    }


def validate_config(config):
    secret = config.get("SECRET_KEY") or ""
    if secret in PLACEHOLDER_SECRETS or len(secret) < 16:
        raise RuntimeError(
            "SECRET_KEY 未配置或过于简单，请在 .env 中设置至少 16 位的随机字符串。"
        )
    if not config.get("ADMIN_PASSWORD"):
        raise RuntimeError("ADMIN_PASSWORD 未配置，请在 .env 中设置登录密码。")
    if not config.get("ADMIN_USERNAME"):
        raise RuntimeError("ADMIN_USERNAME 不能为空。")

    try:
        ZoneInfo(config["APP_TIMEZONE"])
    except Exception as exc:
        raise RuntimeError(f"APP_TIMEZONE 无效: {config['APP_TIMEZONE']}") from exc

    port = config.get("PORT")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise RuntimeError("PORT 必须在 1-65535 之间。")
    smtp_port = config.get("SMTP_PORT")
    if not isinstance(smtp_port, int) or not 1 <= smtp_port <= 65535:
        raise RuntimeError("SMTP_PORT 必须在 1-65535 之间。")
    if config.get("SMTP_SECURITY") not in SMTP_SECURITY_MODES:
        raise RuntimeError(
            "SMTP_SECURITY 只能是 starttls、ssl 或 none。"
        )
    if config.get("PIPELINE_STUB") not in PIPELINE_STUB_MODES:
        raise RuntimeError("PIPELINE_STUB 只能是 off、success、empty 或 fail。")

    data_dir = config["DATA_DIR"]
    try:
        os.makedirs(data_dir, exist_ok=True)
        probe = os.path.join(data_dir, ".write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
    except OSError as exc:
        raise RuntimeError(f"数据目录不可写: {data_dir} ({exc})") from exc


def ensure_data_dirs(data_dir):
    for path in (data_dir, os.path.join(data_dir, "epubs"), os.path.join(data_dir, "work")):
        os.makedirs(path, mode=0o700, exist_ok=True)
