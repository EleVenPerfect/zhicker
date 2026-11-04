import os

from app.db import db_session
from app.services import collections, cookies, jobs, pipeline
from tests.conftest import get_csrf


def test_epub_download_and_delete(logged_in_client, app):
    with db_session(app.config["DB_PATH"]) as conn:
        collection_id = collections.create_collection(
            conn, "网页测试", "https://www.zhihu.com/collection/987"
        )
        cookies.save_cookies(conn, app.config["SECRET_KEY"], {"z_c0": "fake"})
        collection = collections.get_collection(conn, collection_id)
        job_id = jobs.create_job(conn, collection)

    pipeline.run_job(app, job_id)

    response = logged_in_client.get("/epubs/")
    assert response.status_code == 200
    assert "网页测试" in response.get_data(as_text=True)

    with db_session(app.config["DB_PATH"]) as conn:
        from app.db import fetch_one

        epub = fetch_one(conn, "SELECT * FROM epubs WHERE job_id = ?", (job_id,))
        epub_id = epub["id"]
        stored_name = epub["stored_name"]

    response = logged_in_client.get(f"/epubs/{epub_id}/download")
    assert response.status_code == 200
    assert response.mimetype == "application/epub+zip"

    token = get_csrf(logged_in_client)
    response = logged_in_client.post(
        f"/epubs/{epub_id}/delete", data={"csrf_token": token}
    )
    assert response.status_code == 302
    assert not os.path.exists(
        os.path.join(app.config["DATA_DIR"], "epubs", stored_name)
    )
    with db_session(app.config["DB_PATH"]) as conn:
        from app.db import fetch_one

        assert fetch_one(conn, "SELECT * FROM epubs WHERE id = ?", (epub_id,)) is None
