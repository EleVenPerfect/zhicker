from app.db import db_session, fetch_one
from app.services import cookies
from tests.conftest import get_csrf


CURL_TEXT = """curl 'https://www.zhihu.com/api/v4/collections/123/items?limit=20&offset=0' \\
  -H 'cookie: z_c0=abc123; d_c0=x=y=z; _xsrf=token-value' \\
  -H 'user-agent: test'"""


def test_parse_curl_cookie():
    parsed = cookies.parse_cookie_input(CURL_TEXT)
    assert parsed["z_c0"] == "abc123"
    assert parsed["d_c0"] == "x=y=z"
    assert parsed["_xsrf"] == "token-value"


def test_parse_raw_header():
    parsed = cookies.parse_cookie_input("Cookie: z_c0=abc; d_c0=def")
    assert parsed == {"z_c0": "abc", "d_c0": "def"}


def test_parse_json_cookies():
    parsed = cookies.parse_cookie_input('{"z_c0": "abc", "d_c0": "def"}')
    assert parsed["z_c0"] == "abc"


def test_parse_rejects_empty():
    try:
        cookies.parse_cookie_input("no equals signs here")
    except cookies.CookieError:
        pass
    else:
        raise AssertionError("expected CookieError")


def test_save_merge_and_replace(app):
    secret = app.config["SECRET_KEY"]
    with db_session(app.config["DB_PATH"]) as conn:
        cookies.save_cookies(conn, secret, {"alpha": "first-secret"})
        merged = cookies.save_cookies(conn, secret, {"beta": "second-secret"})
        assert set(merged) == {"alpha", "beta"}

        replaced = cookies.save_cookies(
            conn, secret, {"gamma": "third-secret"}, replace=True
        )
        assert replaced == {"gamma": "third-secret"}
        assert cookies.load_cookies(conn, secret) == {"gamma": "third-secret"}

        row = fetch_one(conn, "SELECT data_enc FROM cookies WHERE id = 1")
        assert "first-secret" not in row["data_enc"]
        assert "third-secret" not in row["data_enc"]


def test_clear_cookies(app):
    secret = app.config["SECRET_KEY"]
    with db_session(app.config["DB_PATH"]) as conn:
        cookies.save_cookies(conn, secret, {"z_c0": "abc"})
        cookies.clear_cookies(conn)
        assert cookies.load_cookies(conn, secret) == {}


def test_cookie_page_and_clear(logged_in_client, app):
    secret = app.config["SECRET_KEY"]
    with db_session(app.config["DB_PATH"]) as conn:
        cookies.save_cookies(conn, secret, {"z_c0": "abc"})

    response = logged_in_client.get("/cookies/")
    assert response.status_code == 200
    assert "清除已保存的 Cookie" in response.get_data(as_text=True)

    token = get_csrf(logged_in_client)
    response = logged_in_client.post("/cookies/clear", data={"csrf_token": token})
    assert response.status_code == 302
    with db_session(app.config["DB_PATH"]) as conn:
        assert cookies.load_cookies(conn, secret) == {}


def test_mask_value():
    assert cookies.mask_value("abcdef") == "ab…ef"
    assert cookies.mask_value("ab") == "***"
