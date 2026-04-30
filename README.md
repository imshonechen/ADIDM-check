# ADIDM-Check

ADIDM-Check 是一个基于 Flask 的 IDM Ali.Dbg 版本监控站点。它会定时检测配置的上游 XML 源，将版本记录保存到 SQLite；当下载地址来自 Workupload 时，还会尝试绕过 Puzzle Captcha、获取文件信息、下载压缩包并提取更新日志。前台页面和 JSON API 会展示当前选中的最新版本。

## 功能特性

- 前台版本展示页：`/`
- 前台最新版本 JSON API：`/api/latest`
- 管理后台：登录、手动新增记录、编辑、删除、设置展示版本、系统设置
- 管理后台手动触发抓取
- 新版本可选择转发给 Telegram 机器人会话或频道，并在本地文件存在时以文件消息附带说明发送
- Telegram 消息在版本记录行按机器人/频道分别管理，支持发送、编辑、同步、删除、重发，并记录 Message ID
- Telegram 机器人支持 `/check`、`/latest`、`/status`、`/translate` 管理命令
- APScheduler 每日定时抓取
- SQLite 本地存储，无需额外数据库服务
- 使用 `curl_cffi` 处理 Workupload Puzzle Captcha 流程
- 下载文件缓存到 `data/downloads/`
- 已下载文件支持 SHA256 校验，校验一致时跳过重复下载
- 前台、后台和 Telegram 通知中的文件大小会自动换算为 B、KB、MB 或 GB
- 更新日志支持在线自动翻译为中文，兼容 DeepLX 和 OpenAI `/v1/chat/completions`

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端框架 | Flask 3.x |
| 数据库 | SQLite 3，直接使用 Python `sqlite3` |
| 定时任务 | APScheduler |
| HTTP 请求 | `requests`、`curl_cffi` |
| XML 解析 | `xml.etree.ElementTree` |
| 认证 | Flask-Login、Werkzeug 密码哈希 |
| 前端 | 原生 HTML、CSS、JavaScript、Jinja2 模板 |

## 项目结构

```text
ADIDM-check/
├── app/
│   ├── __init__.py          # Flask 应用工厂
│   ├── config.py            # 运行配置
│   ├── formatters.py        # 展示格式化工具
│   ├── models.py            # SQLite 表结构与查询函数
│   ├── scraper.py           # 上游抓取与 Workupload 处理
│   ├── scheduler.py         # 每日抓取调度器
│   ├── telegram.py          # Telegram 消息发送
│   ├── translator.py        # 在线翻译
│   ├── api/routes.py        # 前台 API 路由
│   └── admin/
│       ├── routes.py        # 管理后台页面与管理 API
│       └── templates/       # 管理后台 Jinja2 模板，包含记录列表、系统设置和编辑页
├── templates/index.html     # 前台页面
├── docs/technical-design.md # 技术设计文档
├── compose.yml              # GHCR 镜像部署示例
├── Dockerfile               # GHCR 镜像构建文件
├── data/                    # 运行时数据库与下载文件，已被 Git 忽略
├── requirements.txt
└── run.py
```

## 快速开始

建议使用 Python 3.10 或更高版本。

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

初始化或更新管理员账号：

```bash
python run.py init-admin --username admin --password your_password
```

启动开发服务器：

```bash
python run.py
```

访问地址：

- 前台页面：`http://localhost:26300/`
- 管理后台：`http://localhost:26300/admin`
- 最新版本 API：`http://localhost:26300/api/latest`

## 配置说明

配置集中在 `app/config.py`。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | `change-this-to-a-random-secret-key` | Flask 会话密钥，可通过环境变量 `SECRET_KEY` 覆盖 |
| `DATABASE_PATH` | `data/adidm.db` | SQLite 数据库路径 |
| `SCRAPE_URL` | `https://idm.0dy.ir/` | 上游 XML 源地址 |
| `SCRAPE_USER_AGENT` | IE11 风格 UA 字符串 | 请求上游源时使用的 User-Agent |
| `SCRAPE_HOUR` | `8` | 每日抓取小时 |
| `SCRAPE_MINUTE` | `0` | 每日抓取分钟 |
| `REQUEST_TIMEOUT` | `30` | 外部请求超时时间，单位秒 |
| `PORT` | `26300` | 开发服务器端口 |

生产环境请务必设置强随机 `SECRET_KEY`。

## 运行时数据

应用启动时会自动创建 `data/adidm.db`。下载文件会保存在 `data/downloads/`。整个 `data/` 目录已被 Git 忽略。

SQLite 当前包含四张表：

- `versions`：版本信息、下载地址、SHA256、更新日志、展示标记、时间戳
- `users`：管理员账号与密码哈希
- `settings`：抓取状态、Telegram 配置与在线翻译配置，例如 `last_checked`、`telegram_bot_token`、`translation_provider`
- `telegram_messages`：Telegram 机器人/频道消息记录、Message ID、状态和最近错误

## 抓取流程

定时任务会在配置时间每天执行一次，管理员也可以在后台手动触发。

抓取流程：

1. 写入本次检测时间 `last_checked`。
2. 请求上游 XML 源。
3. 提取 `Version` 和 `Download_URL`。
4. 如果下载地址属于 Workupload，则使用 `curl_cffi` 完成 puzzle 流程，提取文件信息，获取直连地址，下载 ZIP，并读取 `Changelog.txt`。
5. 如果已启用在线翻译，会将英文更新日志翻译为中文并保存到 `changelog_zh`。
6. 如果版本不存在则插入新记录；如果版本已存在则刷新已有记录。
7. 新版本入库后按后台开关转发给 Telegram 机器人会话或频道；如果文件已下载到 `data/downloads/`，会作为 Telegram 文件消息发送，并将版本说明放在文件 caption 中。
8. 将 `last_check_status` 更新为 `success` 或 `source_error`。

当源站异常或 Workupload 可选信息获取失败时，已有版本数据会被保留。

文件大小原始值会保存在数据库中，前台、后台列表、API 的 `filesize_display` 字段和 Telegram 通知会自动换算显示：小于 1KB 显示 B，1KB 到 1MB 显示 KB，1MB 到 1GB 显示 MB，1GB 以上显示 GB，小数保留 2 位。

## 在线翻译

后台“系统设置 / 更新日志翻译设置”支持：

- 关闭翻译
- DeepLX：填写完整接口地址，例如 `https://api.deeplx.org/<api-key>/translate`
- OpenAI 兼容接口：填写 Base URL、API Key 和模型名，程序会请求 `/v1/chat/completions`
- 翻译测试：保存当前配置后，输入测试文本并立即查看翻译结果

翻译失败不会影响抓取和入库。前台、后台和 Telegram 通知会优先展示 `changelog_zh`，没有中文翻译时回退到原始 `changelog`。版本编辑页也提供“翻译更新日志”按钮，可手动将当前更新日志翻译到中文翻译框，确认后再保存。

## Telegram 管理

后台“系统设置 / Telegram 转发设置”可以配置 Bot Token、机器人会话 Chat ID、频道 Chat ID、自动转发开关和命令权限。启用机器人命令后，程序会通过后台 polling 接收命令：

| 命令 | 说明 |
| --- | --- |
| `/help` | 查看可用命令 |
| `/status` | 查看最近检测和转发状态 |
| `/latest` | 查看当前最新版本 |
| `/check` | 手动触发一次检测更新 |
| `/translate [版本号]` | 翻译最新或指定版本更新日志，并同步已记录的 Telegram 消息 |

命令只允许配置的 Telegram User ID 或 Chat ID 执行。后台版本记录每一行提供“管理机器人”和“管理频道”入口，进入后会按当前版本和目标加载预发送或已发送内容；未发送或已删除时显示“新增中”，已发送时显示“编辑中”。如果远端消息已被手动删除，下一次编辑/删除失败时会把本地状态标记为“远端可能已删除”。

## API

### 前台 API

`GET /api/latest`

返回当前展示版本。如果没有设置展示版本，则返回数据库中最新的一条记录。

```json
{
  "code": 0,
  "data": {
    "version": "20.6",
    "download_url": "https://workupload.com/file/...",
    "filename": "IDM_6.4x_Crack_v20.6.zip",
    "filesize": "65850 (Byte)",
    "filesize_display": "64.31 KB",
    "sha256": "...",
    "direct_url": "https://f51.workupload.com/download/...",
    "changelog": "...",
    "changelog_zh": "...",
    "changelog_display": "...",
    "created_at": "2026-03-26",
    "updated_at": "2026-03-26"
  },
  "last_checked": "2026-03-27",
  "last_check_status": "success"
}
```

无版本数据时：

```json
{
  "code": 1,
  "message": "暂无版本数据"
}
```

### 管理后台页面

管理后台位于 `/admin`，除 `/admin/login` 外均需要登录。

| 路由 | 说明 |
| --- | --- |
| `GET /admin/login` | 登录页面 |
| `GET /admin/dashboard` | 版本列表与抓取状态 |
| `GET /admin/settings` | 系统设置，包含在线翻译与 Telegram 转发 |
| `POST /admin/api/translation-settings` | 保存在线翻译设置 |
| `POST /admin/api/translation-test` | 测试在线翻译 |
| `POST /admin/api/telegram-settings` | 保存 Telegram 转发设置 |
| `POST /admin/api/telegram-test` | 发送 Telegram 测试消息 |
| `GET /admin/versions/<id>/telegram/<target>` | 管理指定版本的机器人或频道消息 |
| `POST /admin/api/versions/<id>/telegram/<target>/send` | 手动发送版本消息 |
| `POST /admin/api/versions/<id>/telegram/<target>/edit` | 编辑 Telegram 消息 |
| `POST /admin/api/versions/<id>/telegram/<target>/sync` | 用当前版本信息同步 Telegram 消息 |
| `POST /admin/api/versions/<id>/telegram/<target>/delete` | 删除 Telegram 消息 |
| `POST /admin/api/versions/<id>/telegram/<target>/resend` | 重发 Telegram 消息 |
| `POST /admin/api/versions/<id>/translate` | 翻译指定版本更新日志 |
| `GET /admin/create` | 新增版本页面 |
| `GET /admin/edit/<id>` | 编辑版本页面 |
| `GET /admin/logout` | 退出登录 |

### 管理后台 JSON API

管理后台 JSON API 位于 `/admin/api`。

| 方法 | 路由 | 说明 |
| --- | --- | --- |
| `POST` | `/admin/api/login` | 登录 |
| `GET` | `/admin/api/versions` | 获取版本列表 |
| `POST` | `/admin/api/versions` | 新增版本 |
| `PUT` | `/admin/api/versions/<id>` | 更新版本 |
| `DELETE` | `/admin/api/versions/<id>` | 删除版本并清理本地文件 |
| `PUT` | `/admin/api/versions/<id>/feature` | 设置为前台展示版本 |
| `POST` | `/admin/api/scrape` | 手动触发抓取 |
| `POST` | `/admin/api/translation-settings` | 保存在线翻译设置 |
| `POST` | `/admin/api/translation-test` | 测试在线翻译 |
| `POST` | `/admin/api/telegram-settings` | 保存 Telegram 转发设置 |
| `POST` | `/admin/api/telegram-test` | 测试 Telegram 发送 |
| `POST` | `/admin/api/versions/<id>/telegram/<target>/send` | 手动发送版本消息 |
| `POST` | `/admin/api/versions/<id>/telegram/<target>/edit` | 编辑 Telegram 消息 |
| `POST` | `/admin/api/versions/<id>/telegram/<target>/sync` | 同步 Telegram 消息 |
| `POST` | `/admin/api/versions/<id>/telegram/<target>/delete` | 删除 Telegram 消息 |
| `POST` | `/admin/api/versions/<id>/telegram/<target>/resend` | 重发 Telegram 消息 |
| `POST` | `/admin/api/versions/<id>/translate` | 翻译指定版本更新日志 |

JSON 响应遵循统一结构：

```json
{
  "code": 0,
  "message": "操作结果",
  "data": {}
}
```

## 生产部署

### Docker Compose（GHCR）

仓库提供 `compose.yml`，默认使用 GHCR 镜像：

```yaml
image: ghcr.io/imshonechen/adidm-check:latest
```

部署步骤：

```bash
mkdir -p data
docker compose up -d
```

访问：

- 前台页面：`http://服务器IP:26300/`
- 管理后台：`http://服务器IP:26300/admin`

首次部署后初始化管理员账号：

```bash
docker compose exec adidm-check python run.py init-admin --username admin --password your_password
```

生产环境请修改 `compose.yml` 中的 `SECRET_KEY`，并保留 `./data:/app/data` 卷挂载，数据库和下载文件都会保存在宿主机 `data/` 目录。

升级镜像：

```bash
docker compose pull
docker compose up -d
```

GHCR 镜像由 `.github/workflows/ghcr.yml` 在推送 `main` 分支或 `v*` 标签时自动构建并发布，支持 `linux/amd64` 和 `linux/arm64`。

### 传统部署

Linux 使用 Gunicorn：

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:26300 "app:create_app()"
```

Windows 使用 Waitress：

```bash
pip install waitress
waitress-serve --host=0.0.0.0 --port=26300 app:create_app
```

生产环境建议放在 Nginx 等反向代理后面，并配合 TLS、压缩和进程守护。

## 开发说明

- 数据库访问集中放在 `app/models.py`。
- 外部抓取逻辑集中放在 `app/scraper.py`。
- SQL 必须使用 `?` 参数绑定，避免字符串拼接。
- 管理后台页面和修改类 API 需要使用 `@login_required`。
- 不要提交 `data/` 下的运行时文件。
- Trellis 与本地 AI 工作流文件已被 `.gitignore` 忽略。
