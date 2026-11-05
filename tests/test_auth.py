from tests.conftest import get_captcha_code, get_csrf


def test_login_required(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_logout(logged_in_client):
    client = logged_in_client
    assert client.get("/").status_code == 200

    token = get_csrf(client)
    response = client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert client.get("/").status_code == 302


def test_captcha_image(client):
    response = client.get("/captcha")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_login_requires_captcha(client):
    client.get("/login")
    token = get_csrf(client)
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "secret",
            "captcha": "",
            "csrf_token": token,
        },
    )
    assert response.status_code == 200
    assert "验证码错误" in response.get_data(as_text=True)
    with client.session_transaction() as session:
        assert "user" not in session


def test_captcha_answer_is_case_insensitive(client, monkeypatch):
    client.get("/login")
    token = get_csrf(client)
    code = get_captcha_code(client, monkeypatch, "AbCd")
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "secret",
            "captcha": code.lower(),
            "csrf_token": token,
        },
    )
    assert response.status_code == 302


def test_wrong_password(client, monkeypatch):
    client.get("/login")
    token = get_csrf(client)
    code = get_captcha_code(client, monkeypatch)
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "wrong",
            "captcha": code,
            "csrf_token": token,
        },
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "user" not in session


def test_captcha_is_single_use(client, monkeypatch):
    client.get("/login")
    token = get_csrf(client)
    code = get_captcha_code(client, monkeypatch)
    client.post(
        "/login",
        data={
            "username": "admin",
            "password": "wrong",
            "captcha": code,
            "csrf_token": token,
        },
    )
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "secret",
            "captcha": code,
            "csrf_token": token,
        },
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "user" not in session


def test_csrf_required(logged_in_client):
    response = logged_in_client.post("/collections/new", data={})
    assert response.status_code == 400


def test_security_headers(logged_in_client):
    response = logged_in_client.get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
