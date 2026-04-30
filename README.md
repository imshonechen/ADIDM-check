# ADIDM-Check

ADIDM-Check 是一个基于 Flask 的 IDM Ali.Dbg 版本监控站点。它会定时检测配置的上游 XML 源，将版本记录保存到 SQLite；当下载地址来自 Workupload 时，还会尝试绕过 Puzzle Captcha、获取文件信息、下载压缩包并提取更新日志。前台页面和 JSON API 会展示当前选中的最新版本。

## 功能特性

- 前台版本展示页：`/`
- 前台最新版本 JSON API：`/api/latest`
- 管理后台：登录、手动新增记录、编辑、删除、设置展示版本
- 管理后台手动触发抓取
- APScheduler 每日定时抓取
- SQLite 本地存储，无需额外数据库服务
- 使用 `curl_cffi` 处理 Workupload Puzzle Captcha 流程
- 下载文件缓存到 `data/downloads/`
- 已下载文件支持 SHA256 校验，校验一致时跳过重复下载

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
│   ├── models.py            # SQLite 表结构与查询函数
│   ├── scraper.py           # 上游抓取与 Workupload 处理
│   ├── scheduler.py         # 每日抓取调度器
│   ├── api/routes.py        # 前台 API 路由
│   └── admin/
│       ├── routes.py        # 管理后台页面与管理 API
│       └── templates/       # 管理后台 Jinja2 模板
├── templates/index.html     # 前台页面
├── docs/technical-design.md # 技术设计文档
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

SQLite 当前包含三张表：

- `versions`：版本信息、下载地址、SHA256、更新日志、展示标记、时间戳
- `users`：管理员账号与密码哈希
- `settings`：抓取状态，例如 `last_checked` 和 `last_check_status`

## 抓取流程

定时任务会在配置时间每天执行一次，管理员也可以在后台手动触发。

抓取流程：

1. 写入本次检测时间 `last_checked`。
2. 请求上游 XML 源。
3. 提取 `Version` 和 `Download_URL`。
4. 如果下载地址属于 Workupload，则使用 `curl_cffi` 完成 puzzle 流程，提取文件信息，获取直连地址，下载 ZIP，并读取 `Changelog.txt`。
5. 如果版本不存在则插入新记录；如果版本已存在则刷新已有记录。
6. 将 `last_check_status` 更新为 `success` 或 `source_error`。

当源站异常或 Workupload 可选信息获取失败时，已有版本数据会被保留。

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
    "sha256": "...",
    "direct_url": "https://f51.workupload.com/download/...",
    "changelog": "...",
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

JSON 响应遵循统一结构：

```json
{
  "code": 0,
  "message": "操作结果",
  "data": {}
}
```

## 生产部署

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
