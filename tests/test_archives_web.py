import os

from app.db import db_session, fetch_one
from app.services import collections, cookies, jobs, pipeline
from tests.conftest import get_csrf


def _run_job(app):
    with db_session(app.config["DB_PATH"]) as conn:
        collection_id = collections.create_collection(
            conn, "网页归档测试", "https://www.zhihu.com/collection/654"
        )
        cookies.save_cookies(conn, app.config["SECRET_KEY"], {"z_c0": "fake"})
        collection = collections.get_collection(conn, collection_id)
        job_id = jobs.create_job(conn, collection)
    pipeline.run_job(app, job_id)
    return job_id


def _get_archive(app, job_id):
    with db_session(app.config["DB_PATH"]) as conn:
        return fetch_one(
            conn, "SELECT * FROM archives WHERE job_id = ?", (job_id,)
        )


def test_archive_download_and_delete(logged_in_client, app):
    job_id = _run_job(app)
    archive = _get_archive(app, job_id)
    assert archive is not None

    response = logged_in_client.get("/archives/")
    assert response.status_code == 200
    assert "网页归档测试" in response.get_data(as_text=True)

    response = logged_in_client.get(f"/archives/{archive['id']}/download")
    assert response.status_code == 200
    assert response.mimetype == "application/gzip"

    response = logged_in_client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert archive["display_name"] in response.get_data(as_text=True)
    assert "下载原始数据" in response.get_data(as_text=True)

    response = logged_in_client.get("/")
    assert response.status_code == 200
    assert "原始数据" in response.get_data(as_text=True)

    token = get_csrf(logged_in_client)
    response = logged_in_client.post(
        f"/archives/{archive['id']}/delete", data={"csrf_token": token}
    )
    assert response.status_code == 302
    assert not os.path.exists(
        os.path.join(app.config["DATA_DIR"], "archives", archive["stored_name"])
    )
    with db_session(app.config["DB_PATH"]) as conn:
        assert (
            fetch_one(conn, "SELECT * FROM archives WHERE id = ?", (archive["id"],))
            is None
        )


def test_archive_resend_updates_status(logged_in_client, app, monkeypatch):
    from app.web import archive_routes

    job_id = _run_job(app)
    archive = _get_archive(app, job_id)
    assert archive is not None
    assert archive["email_status"] == "skipped"

    monkeypatch.setattr(
        archive_routes.settings,
        "resolve_smtp",
        lambda conn, config: {
            "values": {
                "host": "smtp.example.com",
                "from_addr": "from@example.com",
                "to_addr": "to@example.com",
            },
            "sources": {},
            "decrypt_failed": False,
        },
    )
    monkeypatch.setattr(archive_routes.mailer, "is_configured", lambda values: True)
    monkeypatch.setattr(
        archive_routes.mailer, "send_archive", lambda *args, **kwargs: (True, None)
    )

    token = get_csrf(logged_in_client)
    response = logged_in_client.post(
        f"/archives/{archive['id']}/resend", data={"csrf_token": token}
    )
    assert response.status_code == 302

    updated = _get_archive(app, job_id)
    assert updated["email_status"] == "sent"
    assert updated["email_attempts"] == 1
