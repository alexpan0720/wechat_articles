from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.dependencies import build_adapter
from app.models import AdminProfile
from app.security import hash_password
from app.sync.service import SyncService


def create_admin(username: str | None = None, password: str | None = None) -> None:
    init_db()
    settings = get_settings()
    username = username or settings.admin_username
    password = password or getpass.getpass("管理员密码: ")
    if len(password) < 12:
        raise SystemExit("管理员密码至少需要 12 个字符")
    with SessionLocal() as db:
        existing = db.scalar(select(AdminProfile).where(AdminProfile.username == username))
        if existing:
            existing.password_hash = hash_password(password)
            existing.enabled = True
            action = "updated"
        else:
            db.add(AdminProfile(username=username, password_hash=hash_password(password)))
            action = "created"
        db.commit()
    print(f"Admin {username!r} {action}.")


def run_sync(trigger: str = "cli") -> None:
    init_db()
    settings = get_settings()
    with SessionLocal() as db:
        summary = SyncService(db, build_adapter(settings), settings).run(trigger=trigger)
    print(
        f"run={summary.run_id} success={summary.success} "
        f"skipped={summary.skipped} failed={summary.failed}"
    )
    if summary.failed:
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="律所官网及公众号同步系统")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="创建数据库表")
    admin = sub.add_parser("create-admin", help="创建或重置管理员")
    admin.add_argument("--username")
    admin.add_argument("--password", help="建议省略并在提示中输入，避免出现在命令历史")
    sync = sub.add_parser("sync", help="立即执行一次文章同步")
    sync.add_argument("--trigger", default="cli")
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
        print("Database initialized.")
    elif args.command == "create-admin":
        create_admin(args.username, args.password)
    elif args.command == "sync":
        run_sync(args.trigger)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

