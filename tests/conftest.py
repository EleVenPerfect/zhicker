import pytest

from app import auth, captcha, create_app


@pytest.fixture(autouse=True)
def reset_auth_state():
    auth._failures.clear()
    captcha._challenges.clear()
    yield


@pytest.fixture
def app(tmp_path):
    data_dir = tmp_path / "data"
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "unit-test-secret-key-1234567890",
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "secret",
            "DATA_DIR": str(data_dir),
            "DB_PATH": str(data_dir / "app.db"),
            "PIPELINE_STUB": "success",
            "SMTP_HOST": "",
            "SMTP_FROM": "",
            "SMTP_TO": "",
        }
    )
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def get_captcha_code(client, monkeypatch, code="ABCD"):
    monkeypatch.setattr(captcha, "generate_code", lambda: code)
    response = client.get("/captcha")
    assert response.status_code == 200
    return code


@pytest.fixture
def logged_in_client(client, monkeypatch):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    code = get_captcha_code(client, monkeypatch)
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "secret",
            "captcha": code,
            "csrf_token": token,
        },
    )
    assert response.status_code == 302
    return client


def get_csrf(client):
    with client.session_transaction() as session:
        return session["_csrf_token"]
