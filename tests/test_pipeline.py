import os

from app.db import db_session, execute, fetch_all, fetch_one
from app.services import collections, cookies, epub_store, jobs, mailer, pipeline
from app.services.worker import JobWorker
from app.timeutil import utcnow


def _prepare_job(app):
    with db_session(app.config["DB_PATH"]) as conn:
        collection_id = collections.create_collection(
            conn, "测试收藏夹", "https://www.zhihu.com/collection/123"
        )
        cookies.save_cookies(conn, app.config["SECRET_KEY"], {"z_c0": "fake"})
        collection = collections.get_collection(conn, collection_id)
        job_id = jobs.create_job(conn, collection)
    return job_id


def test_stub_pipeline_creates_epub_and_cleans_workdir(app):
    job_id = _prepare_job(app)
    pipeline.run_job(app, job_id)

    with db_session(app.config["DB_PATH"]) as conn:
        job = jobs.get_job(conn, job_id)
        assert job["status"] == "success"
        assert job["stage"] == "done"
        assert job["md_count"] == 1
        epub = fetch_one(conn, "SELECT * FROM epubs WHERE job_id = ?", (job_id,))
        assert epub is not None
        assert epub["email_status"] == "skipped"
        path = epub_store.epub_path(app.config["DATA_DIR"], epub["stored_name"])
        assert os.path.isfile(path)
        epub_store.verify_epub(path)

    work_dir = os.path.join(app.config["DATA_DIR"], "work", str(job_id))
    assert not os.path.exists(work_dir)


def test_stub_empty_fails_and_cleans_workdir(app):
    app.config["PIPELINE_STUB"] = "empty"
    job_id = _prepare_job(app)
    pipeline.run_job(app, job_id)

    with db_session(app.config["DB_PATH"]) as conn:
        job = jobs.get_job(conn, job_id)
        assert job["status"] == "failed"
        assert "没有下载到任何文章" in job["error"]
        assert fetch_one(conn, "SELECT * FROM epubs WHERE job_id = ?", (job_id,)) is None

    assert not os.path.exists(os.path.join(app.config["DATA_DIR"], "work", str(job_id)))


def test_job_recovery_marks_running_failed_and_cleans(app):
    job_id = _prepare_job(app)
    with db_session(app.config["DB_PATH"]) as conn:
        jobs.claim_job(conn, job_id)
        queued_collection_id = collections.create_collection(
            conn, "排队收藏夹", "https://www.zhihu.com/collection/456"
        )
        queued_job_id = jobs.create_job(
            conn, collections.get_collection(conn, queued_collection_id)
        )

    work_dir = os.path.join(app.config["DATA_DIR"], "work", str(job_id))
    os.makedirs(work_dir)
    with open(os.path.join(work_dir, "temp.txt"), "w", encoding="utf-8") as handle:
        handle.write("temp")

    orphan_path = os.path.join(app.config["DATA_DIR"], "epubs", "orphan.epub")
    with open(orphan_path, "wb") as handle:
        handle.write(b"orphan")

    worker = JobWorker(app)
    worker._recover()
    worker.executor.shutdown(wait=False)

    with db_session(app.config["DB_PATH"]) as conn:
        failed = jobs.get_job(conn, job_id)
        assert failed["status"] == "failed"
        assert "服务重启" in failed["error"]
        assert jobs.get_job(conn, queued_job_id)["status"] == "queued"

    assert not os.path.exists(work_dir)
    assert not os.path.exists(orphan_path)


def test_email_failure_does_not_fail_job(app, monkeypatch):
    job_id = _prepare_job(app)

    monkeypatch.setattr(
        pipeline.settings,
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
    monkeypatch.setattr(pipeline.mailer, "is_configured", lambda values: True)

    def explode(*_args, **_kwargs):
        raise RuntimeError("smtp connection lost")

    monkeypatch.setattr(pipeline.mailer, "send_epub", explode)
    pipeline.run_job(app, job_id)

    with db_session(app.config["DB_PATH"]) as conn:
        job = jobs.get_job(conn, job_id)
        epub = fetch_one(conn, "SELECT * FROM epubs WHERE job_id = ?", (job_id,))
        assert job["status"] == "success"
        assert epub["email_status"] == "failed"
        assert "smtp connection lost" in epub["last_email_error"]


def test_epub_path_traversal_rejected(app):
    try:
        epub_store.epub_path(app.config["DATA_DIR"], "../evil.epub")
    except epub_store.EpubError:
        pass
    else:
        raise AssertionError("path traversal should be rejected")

    path = epub_store.epub_path(app.config["DATA_DIR"], "abc.epub")
    assert path.endswith(os.path.join("epubs", "abc.epub"))


def test_mailer_sends_attachment(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host
            sent["port"] = port

        def ehlo(self):
            pass

        def starttls(self, context=None):
            pass

        def login(self, username, password):
            sent["login"] = (username, password)

        def send_message(self, message):
            sent["message"] = message

        def quit(self):
            pass

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    values = {
        "host": "smtp.example.com",
        "port": 587,
        "security": "starttls",
        "username": "",
        "password": "",
        "from_addr": "from@example.com",
        "from_name": "测试",
        "to_addr": "to@example.com",
        "timeout": 5,
    }
    ok, error = mailer.send_epub(
        values, b"epub-bytes", "测试.epub", "收藏夹", 2, "2026-11-04"
    )
    assert ok, error
    message = sent["message"]
    assert message["To"] == "to@example.com"
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "测试.epub"
