from email.utils import parseaddr

from app import crypto
from app.config import SMTP_SECURITY_MODES
from app.db import execute, fetch_all
from app.timeutil import utcnow

DB_PREFIX = "smtp."

SMTP_FIELDS = (
    {"key": "host", "env": "SMTP_HOST", "label": "SMTP 主机", "default": ""},
    {"key": "port", "env": "SMTP_PORT", "label": "端口", "default": "587"},
    {"key": "security", "env": "SMTP_SECURITY", "label": "加密方式", "default": "starttls"},
    {"key": "username", "env": "SMTP_USERNAME", "label": "用户名", "default": ""},
    {"key": "password", "env": "SMTP_PASSWORD", "label": "密码", "default": "", "secret": True},
    {"key": "from_addr", "env": "SMTP_FROM", "label": "发件地址", "default": ""},
    {"key": "from_name", "env": "SMTP_FROM_NAME", "label": "发件人名称", "default": "知乎收藏"},
    {"key": "to_addr", "env": "SMTP_TO", "label": "收件邮箱", "default": ""},
)
FIELD_BY_KEY = {field["key"]: field for field in SMTP_FIELDS}


class SettingsError(ValueError):
    pass


def _env_value(field, config):
    value = config.get(field["env"], field["default"])
    if value is None:
        value = field["default"]
    return str(value)


def _normalize_address(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return ""
    if "," in value or ";" in value:
        raise SettingsError("目前只支持单个收件/发件邮箱地址。")
    _name, address = parseaddr(value)
    if not address or "@" not in address or any(ch.isspace() for ch in address):
        raise SettingsError(f"邮箱地址格式不正确: {value}")
    return address


def resolve_smtp(conn, config):
    values = {field["key"]: _env_value(field, config) for field in SMTP_FIELDS}
    sources = {field["key"]: "env" for field in SMTP_FIELDS}
    decrypt_failed = False

    rows = fetch_all(
        conn,
        "SELECT key, value, is_secret FROM settings WHERE key LIKE ?",
        (DB_PREFIX + "%",),
    )
    for row in rows:
        field_key = row["key"][len(DB_PREFIX):]
        if field_key not in FIELD_BY_KEY:
            continue
        raw = row["value"]
        if row["is_secret"]:
            decrypted = crypto.decrypt(config["SECRET_KEY"], raw)
            if decrypted is None:
                decrypt_failed = True
                raw = ""
            else:
                raw = decrypted
        values[field_key] = raw
        sources[field_key] = "db"

    try:
        values["port"] = int(values.get("port") or 587)
    except (TypeError, ValueError):
        values["port"] = 587
    values["security"] = (values.get("security") or "starttls").lower()
    values["host"] = (values.get("host") or "").strip()
    values["username"] = (values.get("username") or "").strip()
    values["from_name"] = " ".join((values.get("from_name") or "").split())

    for key in ("from_addr", "to_addr"):
        try:
            values[key] = _normalize_address(values.get(key))
        except SettingsError:
            pass
    values["timeout"] = config.get("SMTP_TIMEOUT_SECONDS", 30)

    return {"values": values, "sources": sources, "decrypt_failed": decrypt_failed}


def save_smtp(conn, config, form):
    errors = []
    new_values = {}
    for field in SMTP_FIELDS:
        key = field["key"]
        if field.get("secret"):
            continue
        raw = (form.get(key) or "").strip()
        new_values[key] = raw

    port_raw = new_values.get("port") or "587"
    try:
        port = int(port_raw)
        if not 1 <= port <= 65535:
            raise ValueError
        new_values["port"] = str(port)
    except ValueError:
        errors.append("SMTP 端口必须是 1-65535 之间的整数。")

    security = (new_values.get("security") or "").lower()
    if security not in SMTP_SECURITY_MODES:
        errors.append("加密方式只能是 starttls、ssl 或 none。")
    new_values["security"] = security

    for key, label in (("from_addr", "发件地址"), ("to_addr", "收件邮箱")):
        try:
            new_values[key] = _normalize_address(new_values.get(key))
        except SettingsError as exc:
            errors.append(f"{label}：{exc}")

    new_values["from_name"] = " ".join((new_values.get("from_name") or "").split())
    if errors:
        raise SettingsError("；".join(errors))

    now = utcnow()
    for field in SMTP_FIELDS:
        if field.get("secret"):
            continue
        _upsert(conn, DB_PREFIX + field["key"], new_values.get(field["key"], ""), 0, now)

    password = form.get("password") or ""
    if password:
        _upsert(conn, DB_PREFIX + "password", crypto.encrypt(config["SECRET_KEY"], password), 1, now)


def reset_smtp(conn):
    execute(conn, "DELETE FROM settings WHERE key LIKE ?", (DB_PREFIX + "%",))


def _upsert(conn, key, value, is_secret, now):
    execute(
        conn,
        """
        INSERT INTO settings (key, value, is_secret, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            is_secret = excluded.is_secret,
            updated_at = excluded.updated_at
        """,
        (key, value, 1 if is_secret else 0, now),
    )
