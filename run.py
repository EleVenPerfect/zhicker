import logging
import signal
import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402
from waitress import serve  # noqa: E402


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        app = create_app(start_worker=True)
    except RuntimeError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    worker = app.extensions["worker"]
    stopping = {"value": False}

    def handle_signal(signum, _frame):
        if stopping["value"]:
            return
        stopping["value"] = True
        app.logger.info("收到信号 %s，正在停止后台任务并退出。", signum)
        worker.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    port = app.config["PORT"]
    app.logger.info("服务启动: http://0.0.0.0:%s，数据目录: %s", port, app.config["DATA_DIR"])
    try:
        serve(app, host="0.0.0.0", port=port, threads=4)
    finally:
        worker.shutdown()


if __name__ == "__main__":
    main()
