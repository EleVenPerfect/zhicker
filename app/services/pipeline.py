import base64
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db import db_session
from app.services import cookies as cookies_service
from app.services import epub_store, jobs, mailer, settings

LEGACY_DIR = Path(__file__).resolve().parent.parent / "pipeline" / "legacy"
COLLECTOR = LEGACY_DIR / "zhihu-artical-collect2markdown.py"
EPUB_CONVERTER = LEGACY_DIR / "markdown_to_epub.py"

_STUB_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

_active_lock = threading.Lock()
_active_proc = None


class PipelineError(RuntimeError):
    pass


def terminate_active_process():
    with _active_lock:
        proc = _active_proc
    if proc is not None and proc.poll() is None:
        _kill_process_group(proc)


def run_job(app, job_id):
    config = app.config
    with db_session(config["DB_PATH"]) as conn:
        if not jobs.claim_job(conn, job_id):
            return
        job = jobs.get_job(conn, job_id)
        if job is None:
            return

        workdir = os.path.join(config["DATA_DIR"], "work", str(job_id))
        log_path = os.path.join(workdir, "run.log")
        try:
            _prepare(config, conn, job, workdir)
            jobs.set_stage(conn, job_id, "collecting")
            _collect(config, job, workdir, log_path)

            md_count = _count_markdown(os.path.join(workdir, "source"))
            if md_count == 0:
                raise PipelineError(
                    "没有下载到任何文章：收藏夹可能为空，或 Cookie 已失效。"
                    "请查看任务日志，并重新导入浏览器 Cookie 后重试。"
                )
            jobs.set_md_count(conn, job_id, md_count)

            jobs.set_stage(conn, job_id, "converting")
            display_name = epub_store.build_display_name(
                job["collection_name"], _today(config)
            )
            temp_epub = os.path.join(workdir, display_name)
            _convert(config, workdir, temp_epub, log_path)

            jobs.set_stage(conn, job_id, "finalizing")
            stored = epub_store.store_epub(
                conn,
                config["DATA_DIR"],
                job_id,
                job["collection_name"],
                display_name,
                temp_epub,
            )
            log_text = _log_tail(log_path, config["JOB_LOG_MAX_BYTES"])

            # EPUB 已经保存在最终目录，抓取/图片等临时数据立即清理。
            shutil.rmtree(workdir, ignore_errors=True)

            jobs.set_stage(conn, job_id, "emailing")
            try:
                _send_email(config, conn, job, stored, md_count)
            except Exception as exc:
                # EPUB 已经落盘，邮件异常不应把任务标记为失败。
                try:
                    epub_store.set_email_result(
                        conn, stored["id"], "failed", f"邮件发送异常: {exc}"
                    )
                except Exception:
                    pass
            jobs.mark_success(conn, job_id, md_count, log_text)
        except Exception as exc:
            log_text = _log_tail(log_path, config["JOB_LOG_MAX_BYTES"])
            jobs.mark_failed(conn, job_id, _error_text(exc), log_text)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _prepare(config, conn, job, workdir):
    cookies = cookies_service.load_cookies(conn, config["SECRET_KEY"])
    if not cookies:
        raise PipelineError("尚未配置有效的知乎 Cookie，请先在 Cookie 页面导入。")

    source_dir = os.path.join(workdir, "source")
    image_dir = os.path.join(workdir, "img")
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)

    url_config = {
        "global_image_path": "img",
        "collections": [{"url": job["collection_url"], "path": "source"}],
    }
    with open(os.path.join(workdir, "url.json"), "w", encoding="utf-8") as handle:
        json.dump(url_config, handle, ensure_ascii=False, indent=4)

    cookie_path = os.path.join(workdir, "Cookies.json")
    with open(cookie_path, "w", encoding="utf-8") as handle:
        json.dump(cookies, handle, ensure_ascii=False, indent=4)
    os.chmod(cookie_path, 0o600)


def _collect(config, job, workdir, log_path):
    stub_mode = config.get("PIPELINE_STUB", "off")
    if stub_mode != "off":
        _run_stub(stub_mode, workdir, log_path)
        return
    _run_command(
        [sys.executable, str(COLLECTOR)],
        cwd=workdir,
        log_path=log_path,
        timeout=config["COLLECT_TIMEOUT_SECONDS"],
        label="抓取收藏夹",
        config=config,
        check=False,
    )


def _convert(config, workdir, output_path, log_path):
    command = [
        sys.executable,
        str(EPUB_CONVERTER),
        os.path.join(workdir, "source"),
        "--no-archive",
        "--no-cleanup",
        "--output",
        output_path,
        "--image-dir",
        os.path.join(workdir, "img"),
    ]
    _run_command(
        command,
        cwd=workdir,
        log_path=log_path,
        timeout=config["EPUB_TIMEOUT_SECONDS"],
        label="生成 EPUB",
        config=config,
        check=True,
    )
    if not os.path.isfile(output_path):
        raise PipelineError("EPUB 转换脚本没有生成输出文件。")
    epub_store.verify_epub(output_path)


def _run_stub(mode, workdir, log_path):
    os.makedirs(workdir, exist_ok=True)
    os.makedirs(os.path.join(workdir, "source"), exist_ok=True)
    os.makedirs(os.path.join(workdir, "img"), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"PIPELINE_STUB={mode}，使用本地测试数据，不访问知乎。\n")

    if mode == "fail":
        raise PipelineError("PIPELINE_STUB=fail：模拟抓取失败。")
    if mode == "empty":
        return

    image_path = os.path.join(workdir, "img", "test.png")
    with open(image_path, "wb") as image:
        image.write(_STUB_PNG)

    content = """---
title: "测试文章"
url: "https://www.zhihu.com/question/1/answer/2"
author: "测试作者"
created: "2026-01-01 12:00"
modified: "2026-01-01 12:00"
upvote_num: 12
comment_num: 3
---

# 测试文章

这是 PIPELINE_STUB 生成的测试内容，用于验证 EPUB 生成、清理和邮件发送流程。

![测试图片](../img/test.png)
"""
    with open(os.path.join(workdir, "source", "测试文章.md"), "w", encoding="utf-8") as handle:
        handle.write(content)


def _run_command(command, cwd, log_path, timeout, label, config, check=True):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TZ"] = config.get("TZ", "Asia/Shanghai")

    with open(log_path, "ab") as log_file:
        header = f"\n===== {label} =====\n$ {' '.join(command)}\n"
        log_file.write(header.encode("utf-8"))
        log_file.flush()
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        _set_active_process(process)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            raise PipelineError(f"{label}超时（{timeout} 秒），进程已终止。")
        finally:
            _clear_active_process(process)

    if check and code != 0:
        tail = _log_tail(log_path, 2000)
        raise PipelineError(f"{label}失败（退出码 {code}）。\n{tail[-800:]}")
    return code


def _set_active_process(process):
    global _active_proc
    with _active_lock:
        _active_proc = process


def _clear_active_process(process):
    global _active_proc
    with _active_lock:
        if _active_proc is process:
            _active_proc = None


def _kill_process_group(process):
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _send_email(config, conn, job, stored, md_count):
    resolved = settings.resolve_smtp(conn, config)
    values = resolved["values"]

    if resolved["decrypt_failed"]:
        epub_store.set_email_result(
            conn,
            stored["id"],
            "failed",
            "SMTP 密码解密失败（SECRET_KEY 可能已变更），请重新保存 SMTP 配置后重发。",
        )
        return

    if not mailer.is_configured(values):
        epub_store.set_email_result(
            conn,
            stored["id"],
            "skipped",
            "SMTP 未配置，EPUB 已保存，可稍后在设置页配置邮箱并重发。",
            attempted=False,
        )
        return

    try:
        with open(stored["path"], "rb") as handle:
            epub_bytes = handle.read()
    except OSError as exc:
        epub_store.set_email_result(
            conn, stored["id"], "failed", f"读取 EPUB 文件失败: {exc}"
        )
        return

    ok, error = mailer.send_epub(
        values,
        epub_bytes,
        stored["display_name"],
        job["collection_name"],
        md_count,
        _today(config),
    )
    if ok:
        epub_store.set_email_result(conn, stored["id"], "sent")
    else:
        epub_store.set_email_result(conn, stored["id"], "failed", error)


def _count_markdown(source_dir):
    return len(glob.glob(os.path.join(source_dir, "**", "*.md"), recursive=True))


def _today(config):
    return datetime.now(ZoneInfo(config["APP_TIMEZONE"])).strftime("%Y-%m-%d")


def _log_tail(path, max_bytes):
    if not path or not os.path.isfile(path):
        return ""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read()
        return data.decode("utf-8", "replace")
    except OSError:
        return ""


def _error_text(exc):
    text = str(exc).strip() or exc.__class__.__name__
    return text[:1000]
