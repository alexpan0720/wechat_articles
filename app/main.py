from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.content import article_document, sanitize_article_html
from app.database import get_db, init_db
from app.dependencies import build_adapter
from app.models import AdminProfile, Article, ArticleStatus, ArticleVersion, SyncRun, utcnow
from app.security import (
    ensure_csrf_token, hash_password, require_admin, verify_csrf, verify_password,
)
from app.sync.service import SyncService


settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def format_date(value: datetime | None, fmt: str = "%Y年%m月%d日") -> str:
    return value.strftime(fmt) if value else "—"


templates.env.filters["date"] = format_date


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title=f"{settings.app_name}官网", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.is_production,
    max_age=8 * 60 * 60,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/media", StaticFiles(directory=str(settings.storage_dir)), name="media")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if not request.url.path.endswith("/content"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; frame-src 'self'; form-action 'self'; base-uri 'self'; object-src 'none'",
        )
    return response


def public_context(request: Request, **extra):
    return {"request": request, "site_name": settings.app_name, **extra}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    latest = db.scalars(select(Article).where(
        Article.status == ArticleStatus.published.value
    ).order_by(desc(Article.published_at)).limit(4)).all()
    total = db.scalar(select(func.count()).select_from(Article).where(
        Article.status == ArticleStatus.published.value
    )) or 0
    return templates.TemplateResponse(
        request, "public/home.html", public_context(request, latest=latest, total=total)
    )


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(request, "public/about.html", public_context(request))


@app.get("/practice", response_class=HTMLResponse)
def practice(request: Request):
    return templates.TemplateResponse(request, "public/practice.html", public_context(request))


@app.get("/team", response_class=HTMLResponse)
def team(request: Request):
    return templates.TemplateResponse(request, "public/team.html", public_context(request))


@app.get("/contact", response_class=HTMLResponse)
def contact(request: Request):
    return templates.TemplateResponse(request, "public/contact.html", public_context(request))


@app.get("/articles", response_class=HTMLResponse)
def article_list(
    request: Request,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    per_page = 9
    conditions = [Article.status == ArticleStatus.published.value]
    if q:
        term = f"%{q}%"
        conditions.append(or_(Article.title.ilike(term), Article.summary.ilike(term)))
    total = db.scalar(select(func.count()).select_from(Article).where(*conditions)) or 0
    articles = db.scalars(
        select(Article).where(*conditions).order_by(desc(Article.published_at))
        .offset((page - 1) * per_page).limit(per_page)
    ).all()
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages and total:
        return RedirectResponse(f"/articles?q={quote(q)}&page={pages}", status_code=302)
    return templates.TemplateResponse(request, "public/articles.html", public_context(
        request, articles=articles, q=q, page=page, pages=pages, total=total
    ))


@app.get("/articles/{slug}", response_class=HTMLResponse)
def article_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    article = db.scalar(select(Article).where(
        Article.slug == slug, Article.status == ArticleStatus.published.value
    ))
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    return templates.TemplateResponse(
        request, "public/article_detail.html", public_context(request, article=article)
    )


@app.get("/articles/{slug}/content", response_class=HTMLResponse)
def article_content(slug: str, db: Session = Depends(get_db)):
    article = db.scalar(select(Article).where(
        Article.slug == slug, Article.status == ArticleStatus.published.value
    ))
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    return HTMLResponse(
        article_document(article.title, article.content_html),
        headers={
            "Content-Security-Policy": "default-src 'none'; img-src 'self' data: https:; "
            "style-src 'unsafe-inline'; font-src 'self' data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'self'",
            "Cache-Control": "public, max-age=300",
        },
    )


@app.get("/sitemap.xml")
def sitemap(db: Session = Depends(get_db)):
    articles = db.scalars(select(Article).where(
        Article.status == ArticleStatus.published.value
    ).order_by(desc(Article.updated_at))).all()
    base = settings.public_base_url.rstrip("/")
    static_urls = ["", "/about", "/practice", "/team", "/articles", "/contact"]
    nodes = [f"<url><loc>{base}{path}</loc></url>" for path in static_urls]
    nodes.extend(
        f"<url><loc>{base}/articles/{quote(a.slug)}</loc><lastmod>{a.updated_at.date()}</lastmod></url>"
        for a in articles
    )
    body = '<?xml version="1.0" encoding="UTF-8"?>' \
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(nodes) + "</urlset>"
    return Response(body, media_type="application/xml")


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {settings.public_base_url}/sitemap.xml\n"


@app.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "time": utcnow().isoformat(), "version": app.version}


def admin_context(request: Request, **extra):
    return {
        "request": request,
        "site_name": settings.app_name,
        "admin_username": request.session.get("admin_username"),
        "csrf_token": ensure_csrf_token(request),
        **extra,
    }


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if request.session.get("admin_username"):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse(
        request, "admin/login.html", admin_context(request, error=None)
    )


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)
    admin = db.scalar(select(AdminProfile).where(AdminProfile.username == username))
    if not admin or not admin.enabled or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(
            request, "admin/login.html", admin_context(request, error="用户名或密码错误"),
            status_code=400,
        )
    request.session.clear()
    request.session["admin_username"] = admin.username
    ensure_csrf_token(request)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/logout")
def admin_logout(request: Request, csrf_token: str = Form(...)):
    require_admin(request)
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    counts = dict(db.execute(select(Article.status, func.count()).group_by(Article.status)).all())
    recent_runs = db.scalars(select(SyncRun).order_by(desc(SyncRun.started_at)).limit(8)).all()
    recent_articles = db.scalars(select(Article).order_by(desc(Article.updated_at)).limit(8)).all()
    return templates.TemplateResponse(request, "admin/dashboard.html", admin_context(
        request, counts=counts, recent_runs=recent_runs, recent_articles=recent_articles
    ))


@app.get("/admin/articles", response_class=HTMLResponse)
def admin_articles(
    request: Request,
    state: str = Query(default=""),
    db: Session = Depends(get_db),
):
    require_admin(request)
    query = select(Article).order_by(desc(Article.updated_at))
    if state:
        query = query.where(Article.status == state)
    articles = db.scalars(query.limit(200)).all()
    return templates.TemplateResponse(request, "admin/articles.html", admin_context(
        request, articles=articles, state=state, states=[item.value for item in ArticleStatus]
    ))


@app.get("/admin/articles/{article_id}", response_class=HTMLResponse)
def admin_article_edit(article_id: str, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    versions = db.scalars(select(ArticleVersion).where(
        ArticleVersion.article_id == article.id
    ).order_by(desc(ArticleVersion.version))).all()
    return templates.TemplateResponse(request, "admin/article_edit.html", admin_context(
        request, article=article, versions=versions, saved=request.query_params.get("saved")
    ))


@app.post("/admin/articles/{article_id}")
def admin_article_save(
    article_id: str,
    request: Request,
    title: str = Form(...),
    summary: str = Form(default=""),
    content_html: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request)
    verify_csrf(request, csrf_token)
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    cleaned = sanitize_article_html(content_html)
    if not title.strip() or not cleaned.strip():
        raise HTTPException(status_code=422, detail="标题和正文不能为空")
    article.title = title.strip()
    article.summary = summary.strip() or None
    article.content_html = cleaned
    article.updated_at = utcnow()
    db.commit()
    return RedirectResponse(f"/admin/articles/{article.id}?saved=1", status_code=303)


@app.post("/admin/articles/{article_id}/status")
def admin_article_status(
    article_id: str,
    request: Request,
    target: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request)
    verify_csrf(request, csrf_token)
    if target not in {ArticleStatus.published.value, ArticleStatus.withdrawn.value}:
        raise HTTPException(status_code=422, detail="不支持的状态")
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    article.status = target
    article.updated_at = utcnow()
    db.commit()
    return RedirectResponse(f"/admin/articles/{article.id}?saved=1", status_code=303)


@app.get("/admin/sync", response_class=HTMLResponse)
def admin_sync_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    runs = db.scalars(select(SyncRun).order_by(desc(SyncRun.started_at)).limit(50)).all()
    return templates.TemplateResponse(
        request, "admin/sync.html", admin_context(request, runs=runs, message=None)
    )


@app.post("/admin/sync", response_class=HTMLResponse)
def admin_sync_run(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request)
    verify_csrf(request, csrf_token)
    try:
        summary = SyncService(db, build_adapter(settings), settings).run(trigger="admin")
        message = f"同步完成：成功 {summary.success}，跳过 {summary.skipped}，失败 {summary.failed}"
    except Exception as exc:
        message = f"同步启动失败：{exc}"
    runs = db.scalars(select(SyncRun).order_by(desc(SyncRun.started_at)).limit(50)).all()
    return templates.TemplateResponse(
        request, "admin/sync.html", admin_context(request, runs=runs, message=message)
    )


@app.post("/admin/bootstrap")
def bootstrap_admin(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    """One-time guarded bootstrap for deployments without shell access."""
    if db.scalar(select(func.count()).select_from(AdminProfile)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="管理员已存在")
    if token != settings.secret_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无效令牌")
    if len(password) < 12:
        raise HTTPException(status_code=422, detail="密码至少需要12个字符")
    db.add(AdminProfile(username=username.strip(), password_hash=hash_password(password)))
    db.commit()
    return {"created": True, "username": username.strip()}


@app.exception_handler(404)
async def not_found(request: Request, _: HTTPException):
    if request.url.path.startswith("/admin"):
        return HTMLResponse("未找到", status_code=404)
    return templates.TemplateResponse(
        request, "public/404.html", public_context(request), status_code=404
    )

