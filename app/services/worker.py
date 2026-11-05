import logging
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

from app.db import db_session, execute, fetch_all
from app.services import pipeline
from app.timeutil import utcnow

logger = logging.getLogger(__name__)


class JobWorker:
    def __init__(self, app):
        self.app = app
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zhihu-job")
        self._lock = threading.Lock()
        self._started = False
        self._stopping = False

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        self._recover()
        with db_session(self.app.config["DB_PATH"]) as conn:
            queued_ids = [
                row["id"]
                for row in fetch_all(
                    conn, "SELECT id FROM jobs WHERE status = 'queued' ORDER BY id ASC"
                )
            ]
        for job_id in queued_ids:
            self.submit(job_id)

    def submit(self, job_id):
        if self._stopping:
            return False
        try:
            self.executor.submit(self._run, job_id)
            return True
        except RuntimeError:
            return False

    def _run(self, job_id):
        try:
            pipeline.run_job(self.app, job_id)
        except Exception as exc:
            logger.exception("任务 %s 执行异常", job_id)
            with db_session(self.app.config["DB_PATH"]) as conn:
                execute(
                    conn,
                    """
                    UPDATE jobs
                    SET status = 'failed', stage = 'failed', finished_at = ?,
                        error = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (utcnow(), f"任务执行异常: {exc}"[:1000], job_id),
                )

    def _recover(self):
        config = self.app.config
        with db_session(config["DB_PATH"]) as conn:
            execute(
                conn,
                """
                UPDATE jobs
                SET status = 'failed', stage = 'failed', finished_at = ?,
                    error = ?
                WHERE status = 'running'
                """,
                (utcnow(), "服务重启，任务已中断，请重新运行。"),
            )
            known_epubs = {
                row["stored_name"]
                for row in fetch_all(conn, "SELECT stored_name FROM epubs")
            }
            known_archives = {
                row["stored_name"]
                for row in fetch_all(conn, "SELECT stored_name FROM archives")
            }

        work_root = os.path.join(config["DATA_DIR"], "work")
        for entry in _safe_scandir(work_root):
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, ignore_errors=True)

        epub_root = os.path.join(config["DATA_DIR"], "epubs")
        for entry in _safe_scandir(epub_root):
            if (
                entry.is_file(follow_symlinks=False)
                and entry.name.endswith(".epub")
                and entry.name not in known_epubs
            ):
                try:
                    os.remove(entry.path)
                except OSError:
                    logger.warning("清理孤立 EPUB 失败: %s", entry.path)

        archive_root = os.path.join(config["DATA_DIR"], "archives")
        for entry in _safe_scandir(archive_root):
            if (
                entry.is_file(follow_symlinks=False)
                and entry.name.endswith(".tar.gz")
                and entry.name not in known_archives
            ):
                try:
                    os.remove(entry.path)
                except OSError:
                    logger.warning("清理孤立原始数据归档失败: %s", entry.path)

    def is_alive(self):
        return self._started and not self._stopping

    def shutdown(self):
        with self._lock:
            if self._stopping:
                return
            self._stopping = True
        pipeline.terminate_active_process()
        self.executor.shutdown(wait=False, cancel_futures=True)


def _safe_scandir(path):
    try:
        return list(os.scandir(path))
    except OSError:
        return []
