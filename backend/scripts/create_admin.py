import asyncio
import argparse
import sys
from getpass import getpass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.db.session import AsyncSessionLocal, init_db
from app.models.user import AdminUser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or maintain backend admin accounts.")
    parser.add_argument("--list", action="store_true", help="list admin accounts")
    parser.add_argument("--verify", metavar="USERNAME", help="verify a password for an admin account")
    parser.add_argument("--reset-password", metavar="USERNAME", help="reset password for an admin account")
    parser.add_argument("--delete", metavar="USERNAME", help="delete an admin account")
    parser.add_argument("--yes", action="store_true", help="skip delete confirmation")
    parser.add_argument("--username", help="username for non-interactive create")
    parser.add_argument("--real-name", help="real name for non-interactive create")
    parser.add_argument("--role", default="platform_operator", help="platform_operator or merchant_operator")
    parser.add_argument("--merchant-id", type=int, default=None, help="merchant id for merchant operator")
    return parser


def read_new_password() -> str:
    password = getpass("password: ")
    password_confirm = getpass("password again: ")
    if password != password_confirm:
        raise SystemExit("passwords do not match")
    if len(password) < 8 or len(password) > 64:
        raise SystemExit("password length must be 8-64 characters")
    return password


async def get_admin(session, username: str) -> AdminUser | None:
    result = await session.execute(select(AdminUser).where(AdminUser.username == username))
    return result.scalar_one_or_none()


async def list_admins() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AdminUser).order_by(AdminUser.id))
        admins = result.scalars().all()
        if not admins:
            print("no admin accounts")
            return
        for admin in admins:
            print(
                f"id={admin.id} username={admin.username} real_name={admin.real_name} "
                f"role={admin.role} merchant_id={admin.merchant_id} is_active={admin.is_active}"
            )


async def verify_admin_password(username: str) -> None:
    await init_db()
    password = getpass("password to verify: ")
    async with AsyncSessionLocal() as session:
        admin = await get_admin(session, username)
        if admin is None:
            raise SystemExit("admin username does not exist")
        if verify_password(password, admin.password_hash):
            print("password matched")
        else:
            raise SystemExit("password not matched")


async def reset_admin_password(username: str) -> None:
    await init_db()
    password = read_new_password()
    async with AsyncSessionLocal() as session:
        admin = await get_admin(session, username)
        if admin is None:
            raise SystemExit("admin username does not exist")
        admin.password_hash = hash_password(password)
        await session.commit()
    print("admin password reset")


async def delete_admin(username: str, *, yes: bool) -> None:
    await init_db()
    if not yes:
        confirm = input(f'delete admin "{username}"? type YES to continue: ').strip()
        if confirm != "YES":
            raise SystemExit("delete cancelled")
    async with AsyncSessionLocal() as session:
        admin = await get_admin(session, username)
        if admin is None:
            raise SystemExit("admin username does not exist")
        await session.delete(admin)
        await session.commit()
    print("admin deleted")


async def create_admin(args: argparse.Namespace) -> None:
    await init_db()
    username = args.username or input("username: ").strip()
    real_name = args.real_name or input("real_name: ").strip() or username
    role = args.role or input("role [platform_operator/merchant_operator]: ").strip() or "platform_operator"
    merchant_id = args.merchant_id
    if merchant_id is None:
        merchant_id_raw = input("merchant_id [empty for platform]: ").strip()
        merchant_id = int(merchant_id_raw) if merchant_id_raw else None
    password = read_new_password()

    async with AsyncSessionLocal() as session:
        if await get_admin(session, username) is not None:
            raise SystemExit("admin username already exists")
        admin = AdminUser(
            username=username,
            real_name=real_name,
            role=role,
            merchant_id=merchant_id,
            password_hash=hash_password(password),
        )
        session.add(admin)
        await session.commit()
    print("admin created")


async def main() -> None:
    args = build_parser().parse_args()
    if args.list:
        await list_admins()
    elif args.verify:
        await verify_admin_password(args.verify)
    elif args.reset_password:
        await reset_admin_password(args.reset_password)
    elif args.delete:
        await delete_admin(args.delete, yes=args.yes)
    else:
        await create_admin(args)


if __name__ == "__main__":
    asyncio.run(main())
