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

# 测试：全量、单文件、单个用例
.venv/bin/pytest -q
.venv/bin/pytest -q tests/test_pipeline.py
.venv/bin/pytest -q tests/test_pipeline.py::test_stub_pipeline_creates_epub_and_cleans_workdir

# Docker
cp .env.example .env    # 至少填写 SECRET_KEY 和 ADMIN_PASSWORD
docker compose up -d --build
```

仓库没有 Lint 配置。CI（`.github/workflows/docker.yml`）只在推送 `main` 或 `v*` 标签时构建并推送 GHCR 镜像，不运行测试；本地 pytest 是主要校验手段。

## 架构

- `run.py`：用 waitress 启动 Flask，并调用 `create_app(start_worker=True)` 启动后台 worker。应用工厂默认不启动 worker，测试中直接同步调用 `pipeline.run_job()`。
- `app/__init__.py`：应用工厂，注册认证、CSRF、数据库、蓝图、模板标签和 CSP 等安全响应头。
- `app/web/`：按资源拆分的页面路由，包括概览、收藏夹、任务、EPUB、原始数据、Cookie、设置；`dashboard.healthz` 是容器健康检查端点。
- `app/services/`：核心业务逻辑。
  - `pipeline.py`：单个下载任务的完整流程，子进程带超时（抓取 30 分钟、EPUB 10 分钟），超时杀整个进程组。
  - `worker.py`：单线程任务队列（`ThreadPoolExecutor(max_workers=1)`）和启动恢复。
  - `epub_store.py` / `archive_store.py`：产物的校验、存储、路径安全和邮件状态。
  - `mailer.py`：SMTP 发送，支持 EPUB + tar.gz 双附件。
  - `settings.py` / `cookies.py`：SMTP 与知乎 Cookie 的加密存储。
- `app/pipeline/legacy/`：从上游四阶段流水线项目（上游提交 `2b0b809`）原样复制的抓取、EPUB 转换、Cookie 解析三个脚本，上游修改后需手动同步。抓取器文件名保留历史拼写 `zhihu-artical-collect2markdown.py`。

### 请求与认证

- 除 `auth.login`、`dashboard.healthz` 和静态文件外，所有路由都由 `app/auth.py` 的 `before_request` 强制登录。
- 所有写请求（POST/PUT/PATCH/DELETE）必须带 CSRF token：表单字段 `csrf_token` 或 `X-CSRF-Token` 头。测试中用 `tests/conftest.py` 的 `logged_in_client` 和 `get_csrf()`。
- 登录失败限流为每 IP/用户名 5 次/15 分钟，内存实现，重启即清空。
- 登录页需要图形验证码（`app/captcha.py`），挑战保存在进程内存中，5 分钟过期且一次性使用；多实例部署不共享。
- 时间戳统一以 UTC ISO 字符串存入 SQLite，页面通过 Jinja 的 `localtime` 过滤器按 `APP_TIMEZONE` 展示。

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
- 邮件发送失败不影响任务成功状态；SMTP 未配置时 EPUB 和归档都记为 `skipped`。EPUB 读取失败时仍会单独尝试发送归档。
- 抓取器在配置或网络错误时也可能以 0 退出，因此以实际生成的 `.md` 数量判断成功，完整输出写入任务日志。
- 每个收藏夹同时只允许一个排队/运行中的任务，由 `jobs` 表的部分唯一索引 `uq_jobs_active_collection` 保证。
- 服务启动时 worker 会把遗留的 `running` 任务标记失败、清理 `work/`，并删除数据库中不存在的孤立 EPUB/归档文件。

## 数据目录

```text
<DATA_DIR>/
├── app.db            # SQLite：设置、Cookie、收藏夹、任务、EPUB/归档记录
├── epubs/            # EPUB 长期产物
├── archives/         # 原始数据 tar.gz 长期产物
├── archive_failed/   # 归档失败时保留的原始数据
└── work/             # 任务临时目录，结束后删除
```

产物以随机 UUID 文件名保存，原始显示名单独存库；`epub_store.epub_path()` / `archive_store.archive_path()` 会校验 basename 和扩展名，新增下载、删除路由必须走这些 helper。

SQLite schema 在 `app/schema.sql`，`PRAGMA user_version` 当前为 2。`db.init_db()` 会在版本较低时重放幂等 schema；新增表要同步更新版本号和迁移逻辑。

## 关键配置与安全

- `SECRET_KEY` 用于 session 签名，并经 HKDF 派生密钥（Fernet）加密 Cookie/SMTP 密码；变更后已保存的秘密无法解密，需要重新录入。
- SMTP 设置以 `settings` 表中的 `smtp.*` 键覆盖 `.env`；密码字段不回显，留空表示保持原值，「恢复默认」删除覆盖后回退到环境变量。
- `.env` 不入库，参考 `.env.example`。`Cookies.json`、`url.json` 只在任务临时目录短暂存在。
- `PIPELINE_STUB` 支持 `off` / `success` / `empty` / `fail`，非 `off` 时不访问知乎。
- 容器 entrypoint 以 root 启动，把 `DATA_DIR` 归属到 `PUID`/`PGID`（默认 `10001`）后用 `setpriv` 降权运行应用，并检查目标用户可写；bind mount 场景把 `PUID`/`PGID` 设为宿主机用户。
- `DATA_DIR_MODE`（默认 `0700`）控制 `<DATA_DIR>` 及各子目录权限，启动时会对已存在目录重新 `chmod`；若目录不属于容器用户或文件系统不支持 `chmod`，只记录警告并沿用现有权限；设为 `0777` 会向所有本地用户开放数据，属于明确的安全取舍。
- 同一个数据卷只运行一个应用实例，worker 恢复逻辑按单实例设计。
- 邮箱附件大小受服务商限制，收藏夹图片很多时 tar.gz 可能过大导致邮件失败；文件仍保留在磁盘上。

## 测试约定

- `tests/conftest.py` 提供临时 `DATA_DIR` 和登录客户端；测试配置默认 `PIPELINE_STUB=success`。
- 测试不启动 worker，直接调用 `pipeline.run_job(app, job_id)` 同步执行。
- 流水线测试覆盖 EPUB 生成、归档、清理和邮件状态；新增归档或邮件行为时，同时更新 `tests/test_pipeline.py` 和 `tests/test_archives_web.py`。
