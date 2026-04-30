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
| 反爬绕过 | curl_cffi | 模拟 Chrome TLS 指纹，绕过 workupload.com 反爬 |
| XML 解析 | xml.etree.ElementTree | 标准库解析 XML |
| 前端 | HTML + CSS + JavaScript | 原生实现，无需框架 |
| 管理后台 | Flask + Jinja2 模板 | 服务端渲染 |
| 认证 | Flask-Login | 管理后台登录认证 |
| 部署 | Gunicorn / Waitress | 生产环境 WSGI 服务器 |

### 核心依赖

```
Flask>=3.0
requests>=2.31
APScheduler>=3.10
Flask-Login>=0.6
Werkzeug>=3.0
curl_cffi>=0.14
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
│   ├── models.py                # 数据库模型与操作
│   ├── scraper.py               # 抓取逻辑
│   ├── scheduler.py             # 定时任务调度
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
│   │       └── edit.html        # 编辑/新增页面
│   └── static/
│       ├── css/
│       │   └── style.css        # 前端样式
│       └── js/
│           └── main.js          # 前端 JS 逻辑
├── templates/
│   └── index.html               # 前台首页
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
        "sha256": "c537afd82091793889f87e64bc7e8884cfc5d60e63fcc4f876313f516ee5077d",
        "direct_url": "https://f51.workupload.com/download/S8bHJWYjbkD",
        "changelog": "* Improve Interface\n* Improve Windows Version Status\n* Add WinRAR Status\n* Bug Fixes\n* Build #1 CRC32 > cf702b7c",
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

以下 API 均需登录认证，未登录返回 `401`。

#### POST /api/admin/login

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

#### GET /api/admin/versions

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

#### POST /api/admin/versions

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

#### PUT /api/admin/versions/:id

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

#### DELETE /api/admin/versions/:id

删除指定版本记录。

**响应 200：**

```json
{
    "code": 0,
    "message": "删除成功"
}
```

#### PUT /api/admin/versions/:id/feature

将指定版本设为前台展示（同时取消其他版本的展示状态）。

**响应 200：**

```json
{
    "code": 0,
    "message": "已设为展示版本"
}
```

#### POST /api/admin/scrape

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
5. 查询数据库，判断该版本是否已存在：
   - **不存在**：插入新记录，`is_featured` 默认设为 `1`（最新版本自动展示），同时将旧记录的 `is_featured` 设为 `0`。
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
- 文件大小（Filesize）
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
| 记录列表 | GET /admin/dashboard | 查看所有抓取记录（含创建日期、更新日期），支持删除、设为展示，显示最近检测时间和源站状态 |
| 新增记录 | GET /admin/create | 手动新增版本记录表单 |
| 编辑记录 | GET /admin/edit/:id | 编辑指定记录表单 |

**功能清单：**
- 登录/登出
- 查看所有版本记录列表
- 新增版本记录（手动填写所有字段）
- 编辑已有记录（修改任意字段）
- 删除记录（同时删除 `data/downloads/` 下对应的本地文件）
- 指定某条记录为前台展示版本（is_featured）
- 手动触发抓取

### 6.5 认证模块

- 使用 Flask-Login 管理会话。
- 密码使用 `werkzeug.security.generate_password_hash` / `check_password_hash` 进行哈希存储。
- 首次运行时通过命令行初始化管理员账号：
  ```bash
  python run.py init-admin --username admin --password your_password
  ```
- 管理后台所有路由和 API 使用 `@login_required` 装饰器保护。

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

### 生产环境

```bash
pip install gunicorn   # Linux
pip install waitress   # Windows

# Linux
gunicorn -w 2 -b 0.0.0.0:26300 "app:create_app()"

# Windows
waitress-serve --host=0.0.0.0 --port=26300 app:create_app
```

建议使用 Nginx 反向代理，配合 systemd 管理进程。
