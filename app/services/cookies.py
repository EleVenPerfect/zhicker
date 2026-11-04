import json
import re

import requests

from app import crypto
from app.db import execute, fetch_one
from app.pipeline.legacy.curl_to_cookies import parse_cookies_from_curl
from app.timeutil import utcnow

MAX_COOKIE_BYTES = 256 * 1024
MAX_COOKIE_PAIRS = 500
CRITICAL_COOKIES = ("z_c0",)
COLLECTION_ID_RE = re.compile(r"/collection/(\d+)")


class CookieError(ValueError):
    pass


def parse_cookie_input(text):
    raw = (text or "").strip()
    if not raw:
        raise CookieError("请粘贴浏览器 cURL、Cookie 请求头或 Cookies.json 内容。")
    if len(raw.encode("utf-8")) > MAX_COOKIE_BYTES:
        raise CookieError("Cookie 内容过大（超过 256 KiB）。")

    cookies = {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CookieError(f"JSON 解析失败: {exc}") from exc
        if not isinstance(data, dict):
            raise CookieError("Cookies.json 内容必须是 JSON 对象。")
        for key, value in data.items():
            if isinstance(value, (str, int, float)):
                cookies[str(key)] = str(value)
    else:
        looks_like_curl = "curl " in raw[:300] or re.search(
            r"(^|\s)(-H|--header)(\s|$)", raw
        )
        if looks_like_curl:
            try:
                cookies = parse_cookies_from_curl(raw)
            except ValueError as exc:
                raise CookieError(str(exc)) from exc
        if not cookies:
            cookies = _parse_cookie_header(raw)

    cleaned = {}
    for key, value in cookies.items():
        name = str(key).strip()
        cookie_value = str(value).strip()
        if not name or any(ch in name for ch in "=;\r\n"):
            continue
        if "\r" in cookie_value or "\n" in cookie_value:
            raise CookieError(f"Cookie {name} 的值包含换行符，已拒绝保存。")
        cleaned[name] = cookie_value

    if not cleaned:
        raise CookieError(
            "没有解析出任何 Cookie。请确认粘贴的是完整的 Copy as cURL，或 name=value; ... 格式。"
        )
    if len(cleaned) > MAX_COOKIE_PAIRS:
        raise CookieError("Cookie 数量超过 500 个，请只保留知乎相关字段。")
    return cleaned


def _parse_cookie_header(text):
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1]
    result = {}
    for part in re.split(r"[;\n]", text):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        result[key.strip()] = value.strip().strip('"')
    return result


def missing_critical_cookies(cookies):
    return [name for name in CRITICAL_COOKIES if name not in cookies]


def mask_value(value):
    value = str(value)
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}…{value[-2:]}"


def _row(conn):
    return fetch_one(conn, "SELECT * FROM cookies WHERE id = 1")


def load_cookies(conn, secret_key):
    row = _row(conn)
    if row is None:
        return {}
    decrypted = crypto.decrypt(secret_key, row["data_enc"])
    if decrypted is None:
        return {}
    try:
        data = json.loads(decrypted)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def get_cookie_state(conn, secret_key):
    row = _row(conn)
    if row is None:
        return {
            "configured": False,
            "decrypt_failed": False,
            "items": [],
            "count": 0,
            "updated_at": None,
            "last_test_at": None,
            "last_test_ok": None,
            "last_test_message": None,
        }

    cookies = load_cookies(conn, secret_key)
    decrypt_failed = bool(row["data_enc"]) and not cookies
    items = [
        {"name": key, "masked": mask_value(value)}
        for key, value in sorted(cookies.items())
    ]
    return {
        "configured": bool(cookies),
        "decrypt_failed": decrypt_failed,
        "items": items,
        "count": len(cookies),
        "updated_at": row["updated_at"],
        "last_test_at": row["last_test_at"],
        "last_test_ok": row["last_test_ok"],
        "last_test_message": row["last_test_message"],
        "missing_critical": missing_critical_cookies(cookies),
    }


def save_cookies(conn, secret_key, new_cookies, replace=False):
    existing = {} if replace else load_cookies(conn, secret_key)
    merged = {**existing, **new_cookies}
    now = utcnow()
    execute(
        conn,
        """
        INSERT INTO cookies (id, data_enc, names_json, updated_at)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            data_enc = excluded.data_enc,
            names_json = excluded.names_json,
            updated_at = excluded.updated_at,
            last_test_at = NULL,
            last_test_ok = NULL,
            last_test_message = NULL
        """,
        (
            crypto.encrypt(secret_key, json.dumps(merged, ensure_ascii=False)),
            json.dumps(sorted(merged), ensure_ascii=False),
            now,
        ),
    )
    return merged


def clear_cookies(conn):
    execute(conn, "DELETE FROM cookies WHERE id = 1")


def test_cookies(conn, collection_url, cookies):
    match = COLLECTION_ID_RE.search(collection_url or "")
    if not match:
        result = {"ok": False, "message": "收藏夹地址无效，无法测试 Cookie。"}
        _record_test(conn, result)
        return result

    collection_id = match.group(1)
    api_url = f"https://www.zhihu.com/api/v4/collections/{collection_id}/items"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Referer": f"https://www.zhihu.com/collection/{collection_id}",
    }
    try:
        response = requests.get(
            api_url,
            params={"limit": 1, "offset": 0},
            cookies=cookies,
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as exc:
        result = {"ok": False, "message": f"网络请求失败: {exc}"}
        _record_test(conn, result)
        return result

    if response.status_code != 200:
        result = {
            "ok": False,
            "message": f"Cookie 可能已失效，接口返回 HTTP {response.status_code}。",
        }
        _record_test(conn, result)
        return result

    try:
        data = response.json()
    except ValueError:
        result = {"ok": False, "message": "接口返回的不是 JSON，可能被风控拦截。"}
        _record_test(conn, result)
        return result

    if data.get("error"):
        result = {"ok": False, "message": f"接口返回错误: {data.get('error')}"}
        _record_test(conn, result)
        return result

    total = data.get("paging", {}).get("totals")
    result = {
        "ok": True,
        "message": f"Cookie 有效，收藏夹共 {total} 个项目。" if total is not None else "Cookie 有效。",
    }
    _record_test(conn, result)
    return result


def _record_test(conn, result):
    execute(
        conn,
        """
        UPDATE cookies
        SET last_test_at = ?, last_test_ok = ?, last_test_message = ?
        WHERE id = 1
        """,
        (utcnow(), 1 if result["ok"] else 0, result["message"][:500]),
    )
