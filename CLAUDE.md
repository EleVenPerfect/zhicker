# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## 项目作用

单容器 Flask Web 应用：管理知乎收藏夹，抓取文章转为 Markdown/EPUB，并将原始数据（Markdown + 图片）打包为 tar.gz 归档。EPUB 和归档可通过 SMTP 发送，也可在网页中下载、重发或删除。

## 常用命令

```bash
# 安装开发依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# 本地运行（PIPELINE_STUB=success 不访问知乎，用测试数据跑完整流程）
DATA_DIR=./data \
SECRET_KEY=dev-secret-key-please-change-123456 \
ADMIN_PASSWORD=devpass \
PIPELINE_STUB=success \
.venv/bin/python run.py

# 测试
.venv/bin/pytest -q

# Docker
cp .env.example .env    # 至少填写 SECRET_KEY 和 ADMIN_PASSWORD
docker compose up -d --build
```

仓库没有 Lint、打包或其他构建系统，测试是主要的自动化校验手段。

## 架构

- `run.py`：用 waitress 启动 Flask，后台任务 worker 随应用启动。
- `app/__init__.py`：应用工厂，注册认证、CSRF、数据库、蓝图和状态标签。
- `app/web/`：页面路由，包括概览、收藏夹、任务、EPUB、原始数据、Cookie、设置。
- `app/services/`：核心业务逻辑。
  - `pipeline.py`：单个下载任务的完整流程。
  - `worker.py`：单线程任务队列（`ThreadPoolExecutor(max_workers=1)`）和启动恢复。
  - `epub_store.py`：EPUB 存储、校验、路径安全和邮件状态。
  - `archive_store.py`：原始数据 tar.gz 的创建、校验、存储和管理。
  - `mailer.py`：SMTP 发送，支持 EPUB + tar.gz 双附件。
  - `settings.py` / `cookies.py`：SMTP 与知乎 Cookie 的加密存储。
- `app/pipeline/legacy/`：从上游四阶段流水线项目复制的抓取器与 EPUB 转换脚本，修改上游后需手动同步。

## 任务流水线

`pipeline.run_job()` 顺序固定：

1. 写入任务的 `url.json` 和 `Cookies.json`，调用抓取器下载 `source/*.md` 与 `img/`。
2. 抓取完成后立即删除 `Cookies.json` 和 `url.json`。
3. 用 `markdown_to_epub.py` 生成 EPUB，校验后存入 `<DATA_DIR>/epubs/`。
4. 把 `source/` 和 `img/` 打包为 tar.gz，校验后存入 `<DATA_DIR>/archives/`。
5. 删除任务目录。
6. 发送一封包含 EPUB 和 tar.gz 的邮件（若已配置 SMTP）。
7. 标记任务成功。

关键约束：

- **必须先完成归档再删除任务目录**，不能颠倒顺序。
- 归档内容只含 `source/` 与 `img/`，绝不能包含 `Cookies.json`、`url.json` 或运行日志。
- 归档失败时任务标记失败，但 `source/` 和 `img/` 会移到 `<DATA_DIR>/archive_failed/<任务ID>/`，不会丢弃。
- 邮件发送失败不影响任务成功状态；SMTP 未配置时 EPUB 和归档都记为 `skipped`。
- 抓取器在配置或网络错误时也可能以 0 退出，因此以实际生成的 `.md` 数量判断成功，完整输出写入任务日志。

## 数据目录

```text
<DATA_DIR>/
├── app.db            # SQLite：设置、Cookie、收藏夹、任务、EPUB/归档记录
├── epubs/            # EPUB 长期产物
├── archives/         # 原始数据 tar.gz 长期产物
├── archive_failed/   # 归档失败时保留的原始数据
└── work/             # 任务临时目录，结束后删除
```

SQLite schema 在 `app/schema.sql`，`PRAGMA user_version` 当前为 2。`db.init_db()` 会在版本较低时重放幂等 schema；新增表要同步更新版本号和迁移逻辑。

## 关键配置与安全

- `SECRET_KEY` 用于 session 签名和加密 Cookie/SMTP 密码；变更后已保存的秘密无法解密，需要重新录入。
- `.env` 不入库，参考 `.env.example`。`Cookies.json`、`url.json` 只在任务临时目录短暂存在。
- 容器以 UID `10001` 运行；使用 bind mount 时注意宿主机目录权限。
- 同一个数据卷只运行一个应用实例，worker 恢复逻辑按单实例设计。
- 邮箱附件大小受服务商限制，收藏夹图片很多时 tar.gz 可能过大导致邮件失败；文件仍保留在磁盘上。

## 测试约定

- `tests/conftest.py` 提供临时 `DATA_DIR` 和登录客户端。
- 流水线测试默认使用 `PIPELINE_STUB=success`，覆盖 EPUB 生成、归档、清理和邮件状态。
- 新增归档或邮件行为时，同时更新 `tests/test_pipeline.py` 和 `tests/test_archives_web.py`。
