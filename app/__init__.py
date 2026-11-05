from flask import Flask, render_template

from .auth import init_auth
from .config import config_from_env, ensure_data_dirs, validate_config
from .csrf import init_csrf
from .db import close_db, init_db
from .services.worker import JobWorker
from .timeutil import init_timeutil

STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "success": "成功",
    "failed": "失败",
}

STAGE_LABELS = {
    "queued": "排队",
    "preparing": "准备",
    "collecting": "抓取文章",
    "converting": "生成 EPUB",
    "finalizing": "保存 EPUB",
    "archiving": "打包原始数据",
    "emailing": "发送邮件",
    "done": "完成",
    "failed": "失败",
}

EMAIL_STATUS_LABELS = {
    "pending": "待发送",
    "sent": "已发送",
    "failed": "发送失败",
    "skipped": "未发送",
}


def create_app(overrides=None, start_worker=False):
    app = Flask(__name__)
    config = config_from_env()
    if overrides:
        config.update(overrides)
    app.config.update(config)

    if not app.config.get("TESTING"):
        validate_config(app.config)

    ensure_data_dirs(app.config["DATA_DIR"])
    init_db(app)

    init_auth(app)
    init_csrf(app)
    init_timeutil(app)
    app.teardown_appcontext(close_db)

    from .web import register_blueprints

    register_blueprints(app)

    app.jinja_env.globals.update(
        STATUS_LABELS=STATUS_LABELS,
        STAGE_LABELS=STAGE_LABELS,
        EMAIL_STATUS_LABELS=EMAIL_STATUS_LABELS,
        PIPELINE_STUB_ACTIVE=app.config["PIPELINE_STUB"] != "off",
    )

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(400)
    def bad_request(error):
        return (
            render_template(
                "error.html",
                code=400,
                message=getattr(error, "description", "请求参数不正确。"),
            ),
            400,
        )

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="页面或文件不存在。"), 404

    @app.errorhandler(500)
    def internal_error(_error):
        return (
            render_template("error.html", code=500, message="服务器内部错误，请稍后重试。"),
            500,
        )

    worker = JobWorker(app)
    app.extensions["worker"] = worker
    if start_worker:
        worker.start()

    return app
