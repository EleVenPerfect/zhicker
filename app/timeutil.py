from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app


def utcnow():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def format_localtime(value, tz_name, fmt="%Y-%m-%d %H:%M:%S"):
    dt = parse_iso(value)
    if dt is None:
        return value or ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz_name)).strftime(fmt)


def format_duration(start, end=None):
    start_dt = parse_iso(start)
    if start_dt is None:
        return ""
    end_dt = parse_iso(end) or datetime.now(timezone.utc)
    seconds = max(0, int((end_dt - start_dt).total_seconds()))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {seconds} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分"


def format_filesize(size):
    try:
        size = float(size)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return ""


def init_timeutil(app):
    @app.template_filter("localtime")
    def _localtime(value, fmt="%Y-%m-%d %H:%M:%S"):
        return format_localtime(value, current_app.config["APP_TIMEZONE"], fmt)

    @app.template_filter("duration")
    def _duration(start, end=None):
        return format_duration(start, end)

    @app.template_filter("filesize")
    def _filesize(size):
        return format_filesize(size)
