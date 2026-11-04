import pytest

from app import create_app


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


@pytest.fixture
def logged_in_client(client):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post(
        "/login",
        data={"username": "admin", "password": "secret", "csrf_token": token},
    )
    assert response.status_code == 302
    return client


def get_csrf(client):
    with client.session_transaction() as session:
        return session["_csrf_token"]
