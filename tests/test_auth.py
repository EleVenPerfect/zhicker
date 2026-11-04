from tests.conftest import get_csrf


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


def test_wrong_password(client):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/login",
        data={"username": "admin", "password": "wrong", "csrf_token": token},
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
