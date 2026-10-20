# 律师事务所官网及微信公众号文章自动同步系统

基于 Python/FastAPI 的可运行实现，覆盖公开官网、文章高保真隔离渲染、管理后台、历史/增量同步、图片迁移、HTML 安全净化、幂等去重、版本留痕和定时任务。

## 快速启动

要求 Python 3.10+（生产环境建议 3.12）。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
python -m app.cli init-db
python -m app.cli create-admin
python -m app.cli sync
uvicorn app.main:app --reload
```

打开：

- 官网：http://127.0.0.1:8000
- 管理后台：http://127.0.0.1:8000/admin/login
- 健康检查：http://127.0.0.1:8000/healthz

示例数据位于 `examples/wechat_feed.json`。首次执行 `sync` 会导入两篇带秀米式内联排版的示例文章；再次执行会因为来源 ID 和内容哈希而安全跳过。

## 接入真实公众号监测 API

系统业务层只依赖 `ArticleSourceAdapter`。如果供应商能按项目定义的统一结构输出数据，可设置：

```dotenv
SYNC_ADAPTER=http
SYNC_API_BASE_URL=https://supplier.example/api
SYNC_API_TOKEN=replace-me
```

参考 HTTP 适配器约定 `GET /articles?lookback_days=30` 返回 JSON 数组（或 `{ "articles": [...] }`），字段与 `examples/wechat_feed.json` 一致。若真实供应商字段不同，请在 `app/sync/adapters.py` 新增供应商专用适配器，在适配层完成签名、分页和字段映射，不要把外部字段直接传播到数据库模型。

## 发布门禁

- 来源账号必须启用。
- 标题及净化后正文不能为空。
- 外链图片必须全部下载到自有存储；任一图片失败则文章进入 `failed`，不会自动公开。
- `<script>`、事件属性和危险标签会被移除；公开正文在无脚本 sandbox iframe 中渲染，并应用独立 CSP。
- 同一来源账号和文章 ID 具有联合唯一性，内容哈希相同则跳过。
- 原始 HTML、净化后 HTML 和版本号会保留，已有公开正文不会被空响应覆盖。

## PostgreSQL / Supabase

将 `DATABASE_URL` 改为 PostgreSQL 连接串即可使用 SQLAlchemy 创建表；也可执行 `migrations/001_initial_postgresql.sql`。生产环境应只允许服务端凭据读取 `raw_html`、同步日志和管理员数据。媒体文件当前落在 `STORAGE_DIR`；部署到无持久磁盘的平台时，应把 `migrate_article_images` 的写入实现替换成 Supabase Storage/S3 适配器。

## 自动运行

- 常驻服务器：`python -m app.worker`，北京时间 09:15、18:15 运行，每周日 03:30 补偿扫描。
- GitHub Actions：`.github/workflows/sync.yml` 已配置同一时间表，需要在仓库 Secrets 中设置数据库和 API 凭据。
- 手动：后台“同步任务”或 `python -m app.cli sync`。

## 生产上线前必须完成

1. 用真实 API 样本验证历史分页、唯一 ID、完整 HTML、图片链接和撤回状态。
2. 用 30 篇代表性秀米文章建立截图基线并确认支持/降级清单。
3. 替换律所名称、团队、联系方式、地址和品牌素材。
4. 设置随机 `SECRET_KEY`、强管理员密码、HTTPS、数据库备份及异常告警。
5. 若使用 Vercel 等无持久磁盘运行环境，将媒体存储切换到对象存储，并让同步任务使用同一数据库和存储。

## 测试

```powershell
pytest
```

测试覆盖 HTML/XSS 净化、中文 URL slug、首次发布和重复同步幂等性。

