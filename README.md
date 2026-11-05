# 知乎收藏夹 Web 管理

在现有抓取流水线之上封装的一个单容器 Web 应用：

- 登录后管理收藏夹地址、知乎 Cookie、下载任务、EPUB、原始数据归档和 SMTP 邮箱。
- 每个下载任务把指定收藏夹抓取为 Markdown/图片，再转换成 EPUB。
- EPUB 生成成功后，Markdown 和图片会打包成 tar.gz 保存，随后删除临时目录。
- EPUB 和原始数据归档会在同一封邮件中作为附件发送；发送失败不影响文件保存，可手动重发。
- EPUB 和原始数据归档在页面中分别可下载、重发邮件、手动删除。
- 所有管理数据保存在容器内 `/data/app.db`（SQLite），建议挂载持久化卷。
- 仅支持手动触发下载，不做定时调度。

## 快速开始

```bash
cp .env.example .env

# 生成 SECRET_KEY，并填入 .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# 编辑 .env，至少填写 SECRET_KEY 和 ADMIN_PASSWORD
docker compose up -d --build
```

浏览器访问 `http://服务器地址:8080`，用 `.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录。

首次使用顺序：

1. 进入「设置」填写 SMTP 信息，保存后点「发送测试邮件」。
2. 进入「Cookie」粘贴浏览器 Copy as cURL 的内容，保存并测试连接。
3. 进入「收藏夹」新增收藏夹地址，点击「立即下载」。
4. 任务完成后在「EPUB」页面下载文件，在「原始数据」页面下载 tar.gz，邮件会自动发送。

查看日志：

```bash
docker compose logs -f
```

如果服务器无法拉取 Docker Hub，可在 `.env` 中把 `BASE_IMAGE` 改成可用的 Python 3.12 slim 镜像（例如公司内网或镜像站提供的地址），把 `PIP_INDEX_URL` 改成可用的 PyPI 镜像，然后重新执行 `docker compose up -d --build`。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | 必填 | 用于 session 签名和 SQLite 中 Cookie/SMTP 密码的加密，至少 16 位随机字符串 |
| `ADMIN_USERNAME` | `admin` | 登录用户名 |
| `ADMIN_PASSWORD` | 必填 | 登录密码 |
| `DATA_DIR` | `/data` | SQLite、EPUB、原始数据归档、临时目录的根目录 |
| `DATA_DIR_MODE` | `0700` | 数据目录权限；`0755` 允许他人读取，`0777` 允许所有人读写/删除 |
| `PORT` | `8080` | 容器内监听端口 |
| `HOST_PORT` | `8080` | 映射到宿主机的端口 |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `APP_TIMEZONE` | 同 `TZ` | 页面时间展示时区 |
| `SESSION_COOKIE_SECURE` | `false` | 使用 HTTPS 后设为 `true` |
| `SESSION_LIFETIME_HOURS` | `12` | 登录有效期 |
| `SMTP_HOST` | 空 | SMTP 服务器，留空表示不发送邮件 |
| `SMTP_PORT` | `587` | SMTP 端口 |
| `SMTP_SECURITY` | `starttls` | `starttls` / `ssl` / `none` |
| `SMTP_USERNAME` | 空 | SMTP 用户名，为空时不登录 |
| `SMTP_PASSWORD` | 空 | SMTP 密码 |
| `SMTP_FROM` | 空 | 发件邮箱地址 |
| `SMTP_FROM_NAME` | `知乎收藏` | 发件人名称 |
| `SMTP_TO` | 空 | 收件邮箱地址 |
| `PIPELINE_STUB` | `off` | 仅测试用：`success` / `empty` / `fail`，不会访问知乎 |
| `BASE_IMAGE` | `python:3.12-slim` | 构建参数，可替换为内网镜像 |
| `PIP_INDEX_URL` | 清华源 | 构建参数，可替换为内网 PyPI 镜像 |

SMTP 配置可以在 Web「设置」页面覆盖，保存后写入 SQLite，优先级高于环境变量。页面上的「恢复默认」会清除这些覆盖，重新使用 `.env` 中的值。密码字段不会回显，留空保存表示保持原密码不变。

常见邮箱示例：

- QQ 邮箱：`SMTP_HOST=smtp.qq.com`，`SMTP_PORT=465`，`SMTP_SECURITY=ssl`，密码使用授权码。
- 163 邮箱：`SMTP_HOST=smtp.163.com`，`SMTP_PORT=465`，`SMTP_SECURITY=ssl`，密码使用授权码。
- Gmail：`SMTP_HOST=smtp.gmail.com`，`SMTP_PORT=587`，`SMTP_SECURITY=starttls`，密码使用应用专用密码。

## Cookie 获取

1. 浏览器登录知乎，打开开发者工具 Network 面板。
2. 刷新页面，右键任意一条 `www.zhihu.com` 请求，选择 Copy → Copy as cURL。
3. 粘贴到「Cookie」页面的文本框，保存。
4. 在另一栏选择一个收藏夹，点「测试连接」，确认能看到项目总数。

抓取收藏夹接口主要依赖有效的 `z_c0`。Cookie 过期后任务会失败，重新导入即可。Cookie 和 SMTP 密码都用 `SECRET_KEY` 派生密钥加密后保存在 SQLite 中。

> 注意：更换 `SECRET_KEY` 会导致已保存的 Cookie 和 SMTP 密码无法解密，需要在页面上重新录入。

## 数据与清理

容器内数据目录：

```text
/data/
├── app.db            # SQLite：Cookie、收藏夹、任务、EPUB/归档记录、SMTP 配置
├── epubs/            # 长期产物：EPUB
├── archives/         # 长期产物：原始数据 tar.gz（Markdown + 图片）
├── archive_failed/   # 打包失败时保留的原始数据，供人工排查
└── work/             # 下载临时目录，任务结束即删除
```

每个任务的工作流程：

1. 在 `/data/work/<任务ID>/` 写入该任务的 `url.json` 和 `Cookies.json`。
2. 调用内置抓取脚本下载 Markdown 和图片，抓取完成后立即删除这两个配置文件。
3. 调用内置 EPUB 转换脚本，输出到任务目录。
4. EPUB 校验通过后移动到 `/data/epubs/`。
5. 把 `source/` 和 `img/` 打包成 tar.gz，校验后移动到 `/data/archives/`。
6. 删除整个任务目录。
7. 发送邮件（EPUB 与 tar.gz 同一封邮件，如果已配置 SMTP）。

失败任务同样会清理临时目录，失败原因和日志尾部保存在任务详情中。若打包 tar.gz 失败，任务会标记失败，但 `source/` 和 `img/` 会保留到 `/data/archive_failed/<任务ID>/`，不会直接丢弃。归档内容不包含 `Cookies.json`、`url.json` 或运行日志。任务记录和最多 64 KiB 的诊断日志留在 SQLite 中，方便排查问题。

> 邮件附件大小受邮箱服务商限制（常见为 25–50 MB）。原始数据包含图片，收藏夹较大时压缩包可能超出限制，导致整封邮件发送失败；此时 EPUB 和 tar.gz 仍保存在磁盘上，可分别下载或调大服务商限制后重发。

服务重启时，正在运行的任务会被标记为失败（进程已经不存在），需要重新点击下载；仍在排队的任务会自动继续。

同一个数据卷只运行一个应用实例：后台任务队列和启动时的中断恢复都是按单实例设计的。备份时只需要备份 Docker 卷 `zhihu_data`（或 `/data` 目录），恢复时把数据卷挂回即可。

使用 bind mount 而不是命名卷时，建议让容器以宿主机用户身份运行，这样宿主机可以直接访问数据目录：

```bash
mkdir -p ./data
# docker-compose.yml 中把 zhihu_data:/data 改成 ./data:/data
```

在 `.env` 中把 `PUID` / `PGID` 设为宿主机用户（先用 `id -u` 和 `id -g` 查看）：

```bash
PUID=1000
PGID=1000
```

`docker-compose.yml` 会把它们作为容器的 `user`。容器写出的文件归该用户所有，目录权限仍保持 `0700`。如果数据目录此前由容器以 UID `10001` 创建，切换后需要一次性改回当前用户：

```bash
sudo chown -R "$(id -u):$(id -g)" ./data
```

继续使用命名卷时不要设置 `PUID` / `PGID`，容器保持默认 UID `10001`。

如果不需要按用户隔离，也可以直接向所有人开放数据目录，在 `.env` 中设置：

```bash
DATA_DIR_MODE=0777
```

并在宿主机对挂载根目录执行一次：

```bash
sudo chmod 0777 ./data
```

`DATA_DIR_MODE` 会在每次启动时应用到 `epubs/`、`archives/`、`archive_failed/`、`work/`。如果目录不属于容器用户或挂载的文件系统不支持 `chmod`，应用会记录警告并沿用现有权限继续启动。注意 `0777` 会让本机所有用户都能读取甚至删除其中的 Cookie、EPUB 和归档，仅在个人可信任的机器上使用；只读访问建议用 `0755`。

## 开发与测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

DATA_DIR=./data \
SECRET_KEY=dev-secret-key-please-change-123456 \
ADMIN_PASSWORD=devpass \
PIPELINE_STUB=success \
.venv/bin/python run.py

.venv/bin/pytest -q
```

`PIPELINE_STUB=success` 会用本地生成的 Markdown 和小图片跑真实的 EPUB 转换流程，不需要知乎 Cookie。可以配合本地 SMTP 测试工具（例如 Mailpit）验证邮件附件。

## 关于内置脚本

`app/pipeline/legacy/` 下的三个脚本（抓取、EPUB 转换、Cookie 解析）是从上游四阶段流水线项目原样复制的（对应上游提交 `2b0b809`）。上游修改这些脚本后，需要手动同步到 `app/pipeline/legacy/`。抓取器文件名保留了历史拼写 `zhihu-artical-collect2markdown.py`。

任务执行不依赖旧脚本的退出码：抓取器在配置或网络错误时也可能以 0 退出，因此应用以实际生成的 `.md` 文件数量作为成功依据，并把完整输出保存在任务日志中。

## 常见问题

**任务失败，提示没有下载到文章**
先检查 Cookie 是否过期。在 Cookie 页面点「测试连接」；如果失败，重新从浏览器复制 cURL。收藏夹本身为空也会触发同样提示。

**邮件发送失败**
在设置页检查 SMTP 主机、端口、加密方式和授权码。可以先发测试邮件；EPUB 和原始数据归档不会因邮件失败而丢失，可以在各自列表点「重发邮件」。如果错误提示附件过大，说明压缩包超过了服务商限制，请改为在「原始数据」页面直接下载。

**EPUB 页面下载提示文件不存在**
可能是手动清理了 `/data/epubs` 中的文件。删除该记录后重新运行任务即可。

**容器启动报配置错误**
检查 `.env` 中 `SECRET_KEY` 和 `ADMIN_PASSWORD` 是否已填写，`SMTP_SECURITY` 是否为 `starttls` / `ssl` / `none`。

**启动报「数据目录不可写」**
日志会打印容器用户的 uid/gid 和 `/data` 的所有者与权限，通常是挂载目录不属于容器用户：
- bind mount：在 `.env` 设置 `PUID`/`PGID` 为宿主机用户的 `id -u` / `id -g`，并在宿主机执行 `sudo chown -R "$(id -u):$(id -g)" ./data`。
- 命名卷：保持容器默认用户 10001，执行一次 `docker run --rm -u 0 -v <卷名>:/data <镜像> chown -R 10001:10001 /data`。卷名可用 `docker volume ls` 查看，通常是 `<compose 项目名>_zhihu_data`。

**启动日志提示无法设置数据目录权限**
例如 `无法设置 /data 的权限为 0700 (Operation not permitted)`。说明容器用户不是 `/data` 的所有者（bind mount、旧版本创建的数据卷，或 CIFS/NFS 等不支持 `chmod` 的挂载），应用会沿用现有权限继续启动。要消除告警并固定权限，请设置正确的 `PUID`/`PGID`，并在宿主机对数据目录执行 `sudo chown -R <uid>:<gid> ./data`。

**想验证完整流程但没有知乎 Cookie**
在 `.env` 中设置 `PIPELINE_STUB=success` 重启容器，即可用假数据跑通 EPUB 和邮件流程。验证完记得改回 `off`。

## 安全建议

- 使用强密码，并限制管理端口只对可信网络开放。
- 对外暴露时放在 HTTPS 反向代理后，并设置 `SESSION_COOKIE_SECURE=true`。
- 妥善保管 `.env`（建议 `chmod 600`），不要提交到仓库。
- 定期备份数据卷；`.env` 中的 `SECRET_KEY` 也要一起备份，否则备份里的秘密无法解密。
