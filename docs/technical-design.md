# ADIDM-Check 技术设计文档

## 1. 项目概述

ADIDM-Check 是一个自动化版本监控站点，每日定时抓取 IDM Ali.Dbg版更新信息，存储版本记录，并通过 Web 前端展示最新版本信息。包含管理后台用于记录管理。

---

## 2. 开发技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 后端框架 | Flask 3.x | 轻量级 Python Web 框架 |
| 数据库 | SQLite 3 | 文件型数据库，无需额外服务 |
| ORM | 直接使用 sqlite3 标准库 | 保持简单，无需额外依赖 |
| 定时任务 | APScheduler | Python 定时任务调度 |
| HTTP 请求 | requests | 抓取 XML 源 |
| 消息推送 | Telegram Bot API | 新版本通知机器人会话或频道，并可用文件消息附带版本说明 |
| 在线翻译 | DeepLX / OpenAI 兼容接口 | 将英文更新日志翻译为中文 |
| 反爬绕过 | curl_cffi | 模拟 Chrome TLS 指纹，绕过 workupload.com 反爬 |
| XML 解析 | xml.etree.ElementTree | 标准库解析 XML |
| 前端 | HTML + CSS + JavaScript | 原生实现，无需框架 |
| 管理后台 | Flask + Jinja2 模板 | 服务端渲染 |
| 认证 | Flask-Login | 管理后台登录认证 |
| 部署 | Docker Compose / GHCR / Gunicorn / Waitress | 容器和传统部署 |

### 核心依赖

```
Flask>=3.0
requests>=2.31
APScheduler>=3.10
Flask-Login>=0.6
Werkzeug>=3.0
curl_cffi>=0.14
waitress>=3.0
```

---

## 3. 代码结构

```
ADIDM-check/
├── docs/
│   └── technical-design.md      # 技术文档
├── app/
│   ├── __init__.py              # Flask 应用工厂
│   ├── config.py                # 配置文件
│   ├── formatters.py            # 展示格式化工具
│   ├── models.py                # 数据库模型与操作
│   ├── scraper.py               # 抓取逻辑
│   ├── scheduler.py             # 定时任务调度
│   ├── telegram.py              # Telegram 消息发送
│   ├── translator.py            # 在线翻译
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py            # 前端 API 路由
│   ├── admin/
│   │   ├── __init__.py
│   │   ├── routes.py            # 管理后台路由
│   │   └── templates/
│   │       ├── login.html       # 登录页面
│   │       ├── layout.html      # 后台布局模板
│   │       ├── dashboard.html   # 记录列表页
│   │       ├── settings.html    # 系统设置页
│   │       └── edit.html        # 编辑/新增页面
├── templates/
│   └── index.html               # 前台首页
├── compose.yml                   # GHCR 镜像部署示例
├── Dockerfile                    # 容器镜像构建文件
├── .dockerignore                 # Docker 构建忽略文件
├── .github/workflows/ghcr.yml    # GHCR 镜像构建发布 workflow
├── data/
│   ├── adidm.db                 # SQLite 数据库文件（运行时生成）
│   └── downloads/               # 下载的文件存储目录（运行时生成）
├── run.py                       # 应用入口
├── requirements.txt             # Python 依赖
└── .gitignore
```

---

## 4. 数据库表结构

### 4.1 versions 表（版本记录）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| version | TEXT | NOT NULL, UNIQUE | 版本号，如 `20.6` |
| download_url | TEXT | NOT NULL | 下载地址 |
| filename | TEXT | | 文件名 |
| filesize | TEXT | | 文件大小 |
| sha256 | TEXT | | SHA256 校验值 |
| direct_url | TEXT | | 文件直连下载地址 |
| changelog | TEXT | | 更新日志（从压缩包 Changelog.txt 提取） |
| changelog_zh | TEXT | | 更新日志中文翻译 |
| is_featured | INTEGER | DEFAULT 0 | 是否在前台展示（0=否, 1=是） |
| created_at | TEXT | NOT NULL | 记录创建时间（抓取/新增时间） |
| updated_at | TEXT | NOT NULL | 最后更新时间 |

```sql
CREATE TABLE IF NOT EXISTS versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    version     TEXT    NOT NULL UNIQUE,
    download_url TEXT   NOT NULL,
    filename    TEXT,
    filesize    TEXT,
    sha256      TEXT,
    direct_url  TEXT,
    changelog   TEXT,
    changelog_zh TEXT,
    is_featured INTEGER DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
```

**说明：**
- `is_featured`：用于管理后台指定哪条记录展示在前台。同一时间只有一条记录 `is_featured = 1`。
- `version` 设为 UNIQUE，防止重复版本入库。
- 日期格式统一使用 ISO 8601：`YYYY-MM-DD HH:MM:SS`。

### 4.2 users 表（管理员账号）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| username | TEXT | NOT NULL, UNIQUE | 用户名 |
| password_hash | TEXT | NOT NULL | 密码哈希（Werkzeug 生成） |

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL
);
```

### 4.3 settings 表（全局配置）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| key | TEXT | PRIMARY KEY | 配置键名 |
| value | TEXT | NOT NULL | 配置值 |

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

**当前使用的键：**
- `last_checked`：最近一次版本检测时间（格式 `YYYY-MM-DD HH:MM:SS`），每次执行抓取任务时更新，无论是否发现新版本。前台 API 只返回日期部分（`YYYY-MM-DD`），管理后台显示完整时间。
- `last_check_status`：最近一次检测状态，`success` 表示正常，`source_error` 表示源站异常。前台在源站异常时显示警告提示，管理后台显示状态标识。
- `telegram_bot_token`：Telegram Bot Token。
- `telegram_bot_chat_id`：机器人会话、私聊或群组 Chat ID。
- `telegram_channel_chat_id`：频道用户名（如 `@channel`）或频道 Chat ID（如 `-100...`）。
- `telegram_notify_bot_enabled`：是否将新版本转发给机器人会话，`1` 表示开启，`0` 表示关闭。
- `telegram_notify_channel_enabled`：是否将新版本转发到频道，`1` 表示开启，`0` 表示关闭。
- `telegram_last_notify_status`：最近一次 Telegram 自动转发状态。
- `telegram_commands_enabled`：是否启用 Telegram 机器人命令。
- `telegram_admin_user_ids`：允许执行命令的 Telegram User ID，多个值用英文逗号分隔。
- `telegram_admin_chat_ids`：允许执行命令的 Chat ID，多个值用英文逗号分隔。
- `translation_provider`：翻译服务，`off`、`deeplx` 或 `openai`。
- `translation_deeplx_url`：DeepLX 完整接口地址，例如 `https://api.deeplx.org/<api-key>/translate`。
- `translation_openai_base_url`：OpenAI 兼容接口 Base URL。
- `translation_openai_api_key`：OpenAI 兼容接口 API Key。
- `translation_openai_model`：OpenAI 兼容接口模型名。

### 4.4 telegram_messages 表（Telegram 消息记录）

用于记录系统发送到机器人会话或频道的消息，便于后续编辑、删除、同步和重发。Telegram 上人工编辑或删除不会主动通知系统，本表表示系统最后一次已知状态。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| version_id | INTEGER | NOT NULL | 对应版本记录 |
| target_type | TEXT | NOT NULL | `bot` 或 `channel` |
| chat_id | TEXT | NOT NULL | Telegram Chat ID |
| message_id | INTEGER | | Telegram 返回的 Message ID |
| mode | TEXT | NOT NULL | `message` 或 `document` |
| text | TEXT | | 文本消息内容或文件 caption |
| content_hash | TEXT | | 系统生成内容的 SHA256 |
| status | TEXT | NOT NULL | `sent`、`edited`、`deleted`、`missing`、`failed` |
| last_error | TEXT | | 最近一次 Telegram API 错误 |
| last_checked_at | TEXT | | 最近一次操作时间 |
| created_at | TEXT | NOT NULL | 创建时间 |
| updated_at | TEXT | NOT NULL | 更新时间 |
| deleted_at | TEXT | | 删除时间 |

```sql
CREATE TABLE IF NOT EXISTS telegram_messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id     INTEGER NOT NULL,
    target_type    TEXT    NOT NULL,
    chat_id        TEXT    NOT NULL,
    message_id     INTEGER,
    mode           TEXT    NOT NULL,
    text           TEXT,
    content_hash   TEXT,
    status         TEXT    NOT NULL,
    last_error     TEXT,
    last_checked_at TEXT,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    deleted_at     TEXT,
    UNIQUE(version_id, target_type, chat_id)
);
```

---

## 5. API 规范

所有 API 以 `/api` 为前缀，返回 JSON 格式。

### 5.1 前台 API

#### GET /api/latest

获取前台展示的版本信息（`is_featured = 1` 的记录，若无则返回最新一条）。日期字段只返回到年月日（`YYYY-MM-DD`）。

**响应 200：**

```json
{
    "code": 0,
    "data": {
        "id": 1,
        "version": "20.6",
        "download_url": "https://workupload.com/file/S8bHJWYjbkD",
        "filename": "IDM_6.4x_Crack_v20.6.zip",
        "filesize": "65850 (Byte)",
        "filesize_display": "64.31 KB",
        "sha256": "c537afd82091793889f87e64bc7e8884cfc5d60e63fcc4f876313f516ee5077d",
        "direct_url": "https://f51.workupload.com/download/S8bHJWYjbkD",
        "changelog": "* Improve Interface\n* Improve Windows Version Status\n* Add WinRAR Status\n* Bug Fixes\n* Build #1 CRC32 > cf702b7c",
        "changelog_zh": "* 改进界面\n* 改进 Windows 版本状态\n* 添加 WinRAR 状态\n* 修复 Bug",
        "changelog_display": "* 改进界面\n* 改进 Windows 版本状态\n* 添加 WinRAR 状态\n* 修复 Bug",
        "created_at": "2026-03-26",
        "updated_at": "2026-03-26"
    },
    "last_checked": "2026-03-27",
    "last_check_status": "success"
}
```

**响应 404（无数据）：**

```json
{
    "code": 1,
    "message": "暂无版本数据"
}
```

### 5.2 管理后台 API

以下 API 位于 `/admin/api`，除登录接口外均需登录认证，未登录返回 `401`。

#### POST /admin/api/login

管理员登录。

**请求体：**

```json
{
    "username": "admin",
    "password": "xxx"
}
```

**响应 200：**

```json
{
    "code": 0,
    "message": "登录成功"
}
```

#### GET /admin/api/versions

获取所有版本记录列表（按 `created_at` 降序）。

**响应 200：**

```json
{
    "code": 0,
    "data": [
        {
            "id": 1,
            "version": "20.6",
            "download_url": "...",
            "filename": "...",
            "filesize": "...",
            "sha256": "...",
            "direct_url": "...",
            "changelog": "...",
            "is_featured": 1,
            "created_at": "2026-03-26 12:00:00",
            "updated_at": "2026-03-26 12:00:00"
        }
    ]
}
```

#### POST /admin/api/versions

新增版本记录。

**请求体：**

```json
{
    "version": "20.7",
    "download_url": "https://...",
    "filename": "IDM_6.4x_Crack_v20.7.zip",
    "filesize": "70000 (Byte)",
    "sha256": "abc123...",
    "direct_url": "https://..."
}
```

**响应 201：**

```json
{
    "code": 0,
    "message": "新增成功",
    "data": { "id": 2 }
}
```

#### PUT /admin/api/versions/:id

编辑指定版本记录。

**请求体（部分更新）：**

```json
{
    "filename": "修改后的文件名",
    "filesize": "70000 (Byte)"
}
```

**响应 200：**

```json
{
    "code": 0,
    "message": "更新成功"
}
```

#### DELETE /admin/api/versions/:id

删除指定版本记录。

**响应 200：**

```json
{
    "code": 0,
    "message": "删除成功"
}
```

#### PUT /admin/api/versions/:id/feature

将指定版本设为前台展示（同时取消其他版本的展示状态）。

**响应 200：**

```json
{
    "code": 0,
    "message": "已设为展示版本"
}
```

#### POST /admin/api/scrape

手动触发一次抓取任务。若版本已存在，会刷新下载地址、文件信息等字段。

**响应 200（成功）：**

```json
{
    "code": 0,
    "message": "抓取完成",
    "data": {
        "status": "success",
        "version": "20.6",
        "is_new": false,
        "is_updated": false
    }
}
```

**响应 200（源站异常）：**

```json
{
    "code": 1,
    "message": "源站请求失败：...",
    "data": {
        "status": "source_error",
        "message": "源站请求失败：..."
    }
}
```

#### POST /admin/api/telegram-settings

保存 Telegram 转发设置。该接口需要登录认证。

**请求体：**

```json
{
    "bot_token": "123456:ABC...",
    "bot_chat_id": "123456789",
    "channel_chat_id": "@channel",
    "notify_bot_enabled": true,
    "notify_channel_enabled": false
}
```

**响应 200：**

```json
{
    "code": 0,
    "message": "Telegram 设置已保存"
}
```

#### POST /admin/api/telegram-test

发送 Telegram 测试消息。该接口会使用已保存的配置，`target` 可为 `bot` 或 `channel`。

**请求体：**

```json
{
    "target": "bot"
}
```

**响应 200：**

```json
{
    "code": 0,
    "message": "发送成功"
}
```

**响应 400：**

```json
{
    "code": 1,
    "message": "Telegram Bot Token 未配置"
}
```

#### GET /admin/versions/:id/telegram/:target

管理指定版本的 Telegram 消息。`target` 可为 `bot` 或 `channel`。页面会显示对应 Chat ID、Message ID、远端状态、编辑状态和消息编辑框。

状态规则：

- 没有消息记录、已删除或远端缺失：显示“新增中”，编辑框加载系统预发送内容。
- 已发送或已编辑：显示“编辑中”，编辑框加载已记录的消息内容。

#### POST /admin/api/versions/:id/telegram/:target/send

手动向机器人会话或频道发送指定版本消息，成功后写入 `telegram_messages`。

**请求体：**

```json
{
    "text": "<b>ADIDM-Check 检测到新版本</b>\n版本：<code>20.6</code>"
}
```

#### POST /admin/api/versions/:id/telegram/:target/edit

编辑已记录的 Telegram 消息。文本消息调用 `editMessageText`，文件消息调用 `editMessageCaption`。

**请求体：**

```json
{
    "text": "<b>ADIDM-Check 检测到新版本</b>\n版本：<code>20.6</code>"
}
```

#### POST /admin/api/versions/:id/telegram/:target/sync

根据当前版本信息重新生成消息内容并编辑远端消息。

#### POST /admin/api/versions/:id/telegram/:target/delete

删除远端 Telegram 消息。若 Telegram 返回消息不存在，系统会将本地状态标记为 `missing`。

#### POST /admin/api/versions/:id/telegram/:target/resend

重新发送同一版本消息并更新本地记录中的 `message_id`。请求体可包含 `text`，用于按编辑框内容重发。

#### POST /admin/api/translation-settings

保存在线翻译设置。该接口需要登录认证。

**请求体：**

```json
{
    "provider": "deeplx",
    "deeplx_url": "https://api.deeplx.org/<api-key>/translate",
    "openai_base_url": "https://api.openai.com",
    "openai_api_key": "sk-...",
    "openai_model": "gpt-4o-mini"
}
```

**响应 200：**

```json
{
    "code": 0,
    "message": "翻译设置已保存"
}
```

#### POST /admin/api/translation-test

使用已保存的在线翻译设置执行一次测试翻译。该接口需要登录认证。

**请求体：**

```json
{
    "text": "* Improved UI\n* Fixed bugs"
}
```

#### POST /admin/api/versions/:id/translate

翻译指定版本的更新日志并保存到 `changelog_zh`。

**响应 200：**

```json
{
    "code": 0,
    "message": "翻译测试成功",
    "data": {
        "translation": "* 改进界面\n* 修复 Bug"
    }
}
```

**响应 400：**

```json
{
    "code": 1,
    "message": "翻译失败，请检查翻译服务配置"
}
```

### 5.3 统一响应格式

```json
{
    "code": 0,       // 0=成功, 非0=失败
    "message": "",   // 描述信息（失败时必填）
    "data": {}       // 数据（成功时返回，可选）
}
```

### 5.4 HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 400 | 请求参数错误 |
| 401 | 未登录/认证失败 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 6. 功能模块需求

### 6.1 抓取模块（scraper.py）

**流程：**

1. 记录检测时间（`last_checked`）和检测状态（`last_check_status`）。
2. 请求 `https://idm.0dy.ir/`，携带指定 User-Agent：
   ```
   User-Agent: Mozilla/5.0 (Windows NT 6.1; Trident/7.0; rv:11.0) like Gecko
   ```
   若请求失败，标记 `last_check_status = source_error`，返回错误信息。
3. 解析返回的 XML，提取 `<Version>` 和 `<Download_URL>`。
4. 判断 `Download_URL` 域名是否为 `workupload.com`：
   - **是**：通过 Puzzle Captcha 验证后抓取文件详情和直连地址，并下载文件到本地（见下方 6.1.1）。
   - **否**：仅保存版本号和下载地址，文件信息留空。
5. 若提取到英文更新日志并启用在线翻译，则将更新日志翻译为中文并保存到 `changelog_zh`。
6. 查询数据库，判断该版本是否已存在：
   - **不存在**：插入新记录，`is_featured` 默认设为 `1`（最新版本自动展示），同时将旧记录的 `is_featured` 设为 `0`。
     - 新版本入库后，根据后台 Telegram 设置将新版本信息转发给机器人会话、频道或两者；若文件已下载到 `data/downloads/`，调用 `sendDocument` 发送文件，并将版本信息放入 caption。
   - **已存在**：静默刷新下载地址、文件名、文件大小、SHA256、直连地址、更新日志等字段。仅当 `download_url` 或 `sha256` 发生变化时更新 `updated_at`（说明源站有实质修改），其他字段变化（如直连地址刷新）不更新 `updated_at`。

**抓取频率：** 每天执行一次（默认每天 08:00）。

**错误处理：**
- 网络请求超时设为 30 秒。
- 源站请求失败时标记 `last_check_status = source_error`，前台显示警告提示，管理后台显示异常状态。
- 抓取失败记录日志，不影响现有数据。
- XML 解析失败、页面格式变化等异常需捕获并记录。

#### 6.1.1 Workupload Puzzle Captcha 绕过

workupload.com 对非浏览器请求有反爬机制，访问文件页会返回 "Are you a human?" 验证页面，需要完成 SHA256 Puzzle Challenge 才能获取真实内容。

**反爬机制分析：**
- workupload.com 会检测 TLS 指纹，Python `requests` 库的 TLS 指纹会被识别并拒绝（服务端直接断开连接）。
- 验证流程为前端 JavaScript 解算 SHA256 哈希碰撞，将结果提交后获取 session cookie。

**技术方案：**

使用 `curl_cffi` 库（模拟 Chrome 浏览器 TLS 指纹）配合 Python 解算 puzzle：

1. **访问文件页**：`GET /file/{id}`，初始化 session。
2. **获取 puzzle（第 1 次）**：`GET /puzzle`（带 `X-Requested-With: XMLHttpRequest` 头），返回 JSON：
   ```json
   {
     "success": true,
     "data": {
       "puzzle": "1774468507.031269c43d9b079f5",
       "range": 10000,
       "find": ["hash1", "hash2", "hash3"]
     }
   }
   ```
3. **解算 puzzle**：遍历 `0` 到 `range`，计算 `sha256(puzzle + i)`，找到所有匹配 `find` 数组中的 `i` 值（共需找到 3 个）。
4. **提交答案（第 1 次）**：`POST /captcha`，请求体 `captcha=i1+i2+i3+`（空格分隔，末尾带空格），服务端返回验证 cookie。
5. **访问 /start/{id}**：获取 `token` cookie（服务端 302 重定向回 `/file/{id}`）。
6. **解算并提交 puzzle（第 2 次）**：获取 token 后必须重新验证 captcha，重复步骤 2-4。
7. **再次访问 /start/{id}**：此时返回下载等待页面（HTTP 200），包含文件详情表格。
8. **提取文件信息**：页面 HTML 为表格结构，使用正则提取：
   ```html
   <td>Filename:&nbsp;</td><td>IDM_6.4x_Crack_v20.6.zip</td>
   <td>Filesize:&nbsp;</td><td>65850 (Byte)</td>
   <td>Checksum:&nbsp;</td><td>c537afd...077d (SHA256)</td>
   ```
9. **获取直连下载地址**：调用 `GET /api/file/getDownloadServer/{id}`（带 `X-Requested-With: XMLHttpRequest` 头），返回：
   ```json
   {
     "success": true,
     "data": {
       "url": "https://f51.workupload.com/download/{id}"
     }
   }
   ```
   此 URL 即为文件直连地址，可直接下载。
10. **下载文件到本地**：通过直连地址下载文件，保存到 `data/downloads/` 目录，以原始文件名命名。若文件已存在，使用 SHA256 校验本地文件完整性：校验通过则跳过下载，校验失败则重新下载。若文件不存在则直接下载。
11. **提取更新日志**：使用 Python 标准库 `zipfile` 解压下载的 ZIP 文件（密码为 `1234`），查找并读取 `Changelog.txt` 文件内容。该文件包含所有版本的日志，格式为 `== Change Log vX.X ==` 分隔各版本段落，通过正则匹配当前版本号提取对应段落，并去除每行前导空格后存入数据库 `changelog` 字段。压缩包内通常包含 3 个文件：`Changelog.txt`（更新日志）、软件文件、`Password=1234`（密码提示文件）。

**关键依赖：** `curl_cffi>=0.14`（提供 Chrome TLS 指纹模拟，绕过服务端 TLS 指纹检测）。

**注意事项：**
- 直连地址（如 `https://f51.workupload.com/download/{id}`）是临时的，服务器节点（f51）可能变化，需每次重新获取。
- 整个流程需要 2 次 captcha 解算：第 1 次进入文件页，获取 token 后第 2 次才能进入下载页。

### 6.2 定时任务模块（scheduler.py）

- 使用 APScheduler 的 `BackgroundScheduler`。
- 注册 cron 任务，每天 08:00 执行抓取。
- 应用启动时自动启动调度器。

### 6.3 前台前端页面

**路由：** `GET /`

**展示内容：**
- 文件名（Filename）
- 文件大小（Filesize，前台自动换算为 B、KB、MB 或 GB）
- SHA256 哈希值
- 版本号（Version）
- 下载地址（Download URL，可点击跳转）
- 直连地址（Direct Link，若存在则显示，可点击跳转）
- 更新日志（Changelog，若存在则展示）
- 更新日期（Created At，只显示到年月日）
- 检测日期（Last Checked，最近一次检测的日期）

**数据获取方式：** 页面加载后通过 JavaScript 调用 `GET /api/latest` 获取数据并渲染。

### 6.4 管理后台

**路由前缀：** `/admin`

| 页面 | 路由 | 功能 |
|------|------|------|
| 登录页 | GET /admin/login | 管理员登录表单 |
| 记录列表 | GET /admin/dashboard | 查看所有抓取记录（含创建日期、更新日期），支持删除、设为展示，显示最近检测时间、源站状态和每个版本的机器人/频道消息状态 |
| 系统设置 | GET /admin/settings | 配置在线翻译和 Telegram 转发，并支持翻译测试与 Telegram 测试 |
| Telegram 消息 | GET /admin/versions/:id/telegram/:target | 管理某个版本对应的机器人或频道消息 |
| 新增记录 | GET /admin/create | 手动新增版本记录表单 |
| 编辑记录 | GET /admin/edit/:id | 编辑指定记录表单，并可手动翻译当前更新日志到中文翻译字段 |

**功能清单：**
- 登录/登出
- 查看所有版本记录列表
- 新增版本记录（手动填写所有字段）
- 编辑已有记录（修改任意字段）
- 在编辑页手动触发更新日志翻译，翻译结果填入 `changelog_zh` 表单字段，保存后生效
- 删除记录（同时删除 `data/downloads/` 下对应的本地文件）
- 指定某条记录为前台展示版本（is_featured）
- 手动触发抓取
- 在独立系统设置页配置在线翻译和 Telegram 转发
- 使用后台按钮测试在线翻译、Telegram 机器人和频道发送
- 在版本记录行管理机器人消息和频道消息：手动发送、编辑、同步、删除和重发

### 6.5 展示格式化模块（formatters.py）

- `format_filesize(value)` 用于前台、后台和 Telegram 通知的文件大小展示。
- 原始 `filesize` 字段仍按源站返回内容保存到数据库，展示层额外使用 `filesize_display` 或格式化后的文本。
- 小于 1KB 显示 B，1KB 到 1MB 显示 KB，1MB 到 1GB 显示 MB，1GB 以上显示 GB。
- KB、MB、GB 保留 2 位小数。

### 6.6 认证模块

- 使用 Flask-Login 管理会话。
- 密码使用 `werkzeug.security.generate_password_hash` / `check_password_hash` 进行哈希存储。
- 首次运行时通过命令行初始化管理员账号：
  ```bash
  python run.py init-admin --username admin --password your_password
  ```
- 管理后台所有路由和 API 使用 `@login_required` 装饰器保护。

### 6.7 Telegram 通知模块（telegram.py）

- 无本地文件时使用 Telegram Bot API 的 `sendMessage` 接口发送 HTML 格式消息；有本地文件时使用 `sendDocument` 接口发送文件，并将同一份版本说明作为 caption。
- 配置保存在 `settings` 表，管理后台系统设置页提供 Bot Token、机器人/会话 Chat ID、频道 Chat ID 以及两个独立转发开关。
- 发送成功后记录 `telegram_messages.message_id`，用于后续编辑、删除、同步和重发。
- 仅当抓取到新版本并插入 `versions` 表后自动通知；刷新已有版本不会重复转发。
- 机器人转发与频道转发相互独立，可以只开启其中一个，也可以同时开启。
- 频道转发要求机器人已加入频道并具备发消息权限。
- Telegram 文本消息中，文件名、文件大小和 SHA256 使用等宽格式；文件大小会按 B、KB、MB、GB 自动换算并保留 2 位小数。
- 文件发送依赖本地下载缓存，仅当 `data/downloads/<filename>` 存在时发送文件消息；文件不存在时退回文本通知。
- 版本记录页每行显示机器人和频道消息状态、Message ID 以及管理入口。
- 版本 Telegram 消息页按 `version_id + target_type` 管理单条消息，支持手动发送版本消息、编辑消息、同步当前版本信息、删除远端消息和重发消息。
- 如果远端消息被人工删除，系统通常无法实时感知；下一次编辑或删除失败时会将本地状态标记为 `missing`。
- 发送失败时记录 warning 日志，不影响版本入库和抓取状态。

### 6.8 Telegram 命令模块

- 启用 `telegram_commands_enabled` 后，应用启动时通过后台线程 polling Telegram `getUpdates`。
- 仅允许 `telegram_admin_user_ids` 或 `telegram_admin_chat_ids` 中配置的用户/会话执行命令。
- 支持命令：
  - `/help`：查看可用命令。
  - `/status`：查看最近检测和转发状态。
  - `/latest`：查看当前最新版本。
  - `/check`：手动触发一次检测更新。
  - `/translate [版本号]`：翻译最新或指定版本更新日志，并同步该版本已记录的 Telegram 消息。

### 6.9 在线翻译模块（translator.py）

- 支持 `off`、`deeplx`、`openai` 三种模式。
- DeepLX 使用完整接口地址，例如 `https://api.deeplx.org/<api-key>/translate`，请求体包含 `text`、`source_lang=EN`、`target_lang=ZH`。
- OpenAI 兼容模式请求 `/v1/chat/completions`，使用 Bearer API Key，并通过系统提示要求保留更新日志结构；Base URL 可填写服务根地址、`/v1` 或完整 `/v1/chat/completions`。
- 翻译失败时记录 warning 日志并回退原文，不影响抓取、入库和 Telegram 转发。
- 管理后台系统设置页提供翻译测试，会先保存当前配置，再调用 `/admin/api/translation-test` 返回测试文本的翻译结果。
- 版本编辑页复用 `/admin/api/translation-test`，手动将当前 `changelog` 翻译后填入 `changelog_zh`，不自动提交数据库。
- 前台 API 提供 `changelog_display`，优先返回中文翻译，没有中文翻译时返回原始更新日志。

---

## 7. 代码规范

### 7.1 Python 代码规范

- 遵循 PEP 8 编码规范。
- 缩进使用 4 个空格。
- 文件编码统一 UTF-8。
- 变量和函数命名使用 `snake_case`。
- 类命名使用 `PascalCase`。
- 常量命名使用 `UPPER_SNAKE_CASE`。
- 每个模块文件顶部包含简要用途说明。

### 7.2 前端代码规范

- HTML 使用语义化标签。
- CSS 类名使用 `kebab-case`。
- JavaScript 变量命名使用 `camelCase`。
- API 请求统一使用 `fetch`，不引入第三方库。

### 7.3 SQL 规范

- 关键字使用大写：`SELECT`、`INSERT`、`WHERE` 等。
- 所有查询使用参数化绑定（`?` 占位符），禁止字符串拼接 SQL，防止注入。

---

## 8. 提交规范

使用 Conventional Commits 规范：

```
<type>(<scope>): <subject>
```

### Type 类型

| 类型 | 说明 |
|------|------|
| feat | 新功能 |
| fix | 修复 Bug |
| docs | 文档变更 |
| style | 代码格式（不影响逻辑） |
| refactor | 重构（无新功能或修复） |
| perf | 性能优化 |
| test | 测试相关 |
| chore | 构建/工具/依赖变更 |

### Scope 范围

| 范围 | 说明 |
|------|------|
| scraper | 抓取模块 |
| api | API 接口 |
| admin | 管理后台 |
| frontend | 前台页面 |
| db | 数据库相关 |
| auth | 认证相关 |

### 示例

```
feat(scraper): 实现 IDM 版本信息抓取逻辑
fix(api): 修复 latest 接口无数据时返回 500 的问题
docs: 添加技术设计文档
chore: 添加 requirements.txt 依赖清单
```

---

## 9. 配置项（config.py）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| SECRET_KEY | 随机生成 | Flask 会话密钥 |
| DATABASE_PATH | data/adidm.db | 数据库文件路径 |
| SCRAPE_URL | https://idm.0dy.ir/ | 抓取目标地址 |
| SCRAPE_USER_AGENT | Mozilla/5.0 (Windows NT 6.1; ...) | 请求 User-Agent |
| SCRAPE_HOUR | 8 | 每天抓取时间（小时） |
| SCRAPE_MINUTE | 0 | 每天抓取时间（分钟） |
| REQUEST_TIMEOUT | 30 | HTTP 请求超时（秒） |

---

## 10. 部署说明

### 开发环境

```bash
pip install -r requirements.txt
python run.py init-admin --username admin --password your_password
python run.py
```

访问 `http://localhost:26300` 查看前台，`http://localhost:26300/admin` 进入管理后台。

### Docker Compose（GHCR）

推荐使用仓库提供的 `compose.yml` 部署：

```yaml
services:
  adidm-check:
    image: ghcr.io/imshonechen/adidm-check:latest
    container_name: adidm-check
    restart: unless-stopped
    ports:
      - "26300:26300"
    environment:
      SECRET_KEY: "change-this-to-a-random-secret-key"
    volumes:
      - ./data:/app/data
```

启动：

```bash
mkdir -p data
docker compose up -d
```

初始化管理员：

```bash
docker compose exec adidm-check python run.py init-admin --username admin --password your_password
```

升级：

```bash
docker compose pull
docker compose up -d
```

容器内使用 Waitress 监听 `0.0.0.0:26300`。数据库和下载文件通过 `./data:/app/data` 持久化。

GHCR 镜像由 `.github/workflows/ghcr.yml` 自动构建：

- 推送 `main` 分支发布 `latest` 和 `sha-*` 标签。
- 推送 `v*` Git 标签发布对应版本标签。
- 镜像名为 `ghcr.io/imshonechen/adidm-check`。
- 构建平台为 `linux/amd64` 和 `linux/arm64`。

生产环境必须修改 `SECRET_KEY`，并确保 GitHub Packages 中镜像可被部署环境拉取。

### 传统生产环境

```bash
pip install gunicorn   # Linux
pip install waitress   # Windows

# Linux
gunicorn -w 2 -b 0.0.0.0:26300 "app:create_app()"

# Windows
waitress-serve --host=0.0.0.0 --port=26300 app:create_app
```

建议使用 Nginx 反向代理，配合 systemd 管理进程。
