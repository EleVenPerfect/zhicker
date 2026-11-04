import pytest

from app.db import db_session, fetch_one
from app.services import collections, settings


def test_collection_url_validation():
    url, collection_id = collections.normalize_collection_url(
        "https://www.zhihu.com/collection/123456?utm_source=x"
    )
    assert url == "https://www.zhihu.com/collection/123456"
    assert collection_id == "123456"

    with pytest.raises(collections.CollectionError):
        collections.normalize_collection_url("https://example.com/collection/123")
    with pytest.raises(collections.CollectionError):
        collections.normalize_collection_url("https://www.zhihu.com/collection/abc")


def test_collection_crud_and_duplicate(app):
    with db_session(app.config["DB_PATH"]) as conn:
        collection_id = collections.create_collection(
            conn, "", "https://www.zhihu.com/collection/42"
        )
        row = collections.get_collection(conn, collection_id)
        assert row["name"] == "收藏夹_42"

        with pytest.raises(collections.DuplicateCollection):
            collections.create_collection(
                conn, "重复", "https://www.zhihu.com/collection/42/"
            )

        assert collections.update_collection(
            conn, collection_id, "新名字", "https://www.zhihu.com/collection/42"
        )
        assert collections.get_collection(conn, collection_id)["name"] == "新名字"
        collections.delete_collection(conn, collection_id)
        assert collections.get_collection(conn, collection_id) is None


def test_smtp_env_default_and_db_override(app):
    config = app.config
    with db_session(config["DB_PATH"]) as conn:
        resolved = settings.resolve_smtp(conn, config)
        assert resolved["values"]["port"] == 587
        assert resolved["values"]["security"] == "starttls"
        assert resolved["sources"]["host"] == "env"

        form = {
            "host": "smtp.example.com",
            "port": "465",
            "security": "ssl",
            "username": "user",
            "password": "super-secret",
            "from_addr": "from@example.com",
            "from_name": "测试发件人",
            "to_addr": "to@example.com",
        }
        settings.save_smtp(conn, config, form)
        resolved = settings.resolve_smtp(conn, config)
        assert resolved["values"]["host"] == "smtp.example.com"
        assert resolved["values"]["port"] == 465
        assert resolved["values"]["security"] == "ssl"
        assert resolved["values"]["password"] == "super-secret"
        assert resolved["sources"]["host"] == "db"

        row = fetch_one(conn, "SELECT value FROM settings WHERE key = 'smtp.password'")
        assert row["value"] != "super-secret"

        settings.reset_smtp(conn)
        resolved = settings.resolve_smtp(conn, config)
        assert resolved["sources"]["host"] == "env"
        assert resolved["values"]["host"] == ""


def test_smtp_validation(app):
    with db_session(app.config["DB_PATH"]) as conn:
        with pytest.raises(settings.SettingsError):
            settings.save_smtp(
                conn,
                app.config,
                {
                    "host": "smtp.example.com",
                    "port": "70000",
                    "security": "starttls",
                    "from_addr": "from@example.com",
                    "to_addr": "to@example.com",
                },
            )
        with pytest.raises(settings.SettingsError):
            settings.save_smtp(
                conn,
                app.config,
                {
                    "host": "smtp.example.com",
                    "port": "587",
                    "security": "starttls",
                    "from_addr": "not-an-email",
                    "to_addr": "to@example.com",
                },
            )
