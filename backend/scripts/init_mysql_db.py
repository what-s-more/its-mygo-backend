import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create the MySQL database configured by DATABASE_URL.")
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="drop the configured database before recreating it; this deletes all data",
    )
    parser.add_argument(
        "--collation",
        default="utf8mb4_0900_ai_ci",
        help="database collation, use utf8mb4_unicode_ci if your MySQL version does not support the default",
    )
    return parser


async def init_mysql_database(drop_existing: bool, collation: str) -> None:
    url = make_url(settings.database_url)
    if not url.drivername.startswith("mysql"):
        raise SystemExit(f"DATABASE_URL is not MySQL: {url.drivername}")
    if not url.database:
        raise SystemExit("DATABASE_URL must include a database name, for example /its_mygo")

    database_name = url.database
    server_url = url.set(database=None)
    engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
    quoted_database = f"`{database_name.replace('`', '``')}`"
    async with engine.begin() as conn:
        if drop_existing:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
        try:
            await conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS {quoted_database} "
                    f"DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE {collation}"
                )
            )
        except Exception as exc:
            if collation == "utf8mb4_0900_ai_ci":
                raise SystemExit(
                    "Failed to create database with utf8mb4_0900_ai_ci. "
                    "Try: .\\.venv\\Scripts\\python.exe scripts\\init_mysql_db.py --collation utf8mb4_unicode_ci"
                ) from exc
            raise
    await engine.dispose()
    action = "dropped and recreated" if drop_existing else "created or verified"
    print(f"MySQL database {database_name!r} {action}.")


async def main() -> None:
    args = build_parser().parse_args()
    await init_mysql_database(args.drop_existing, args.collation)


if __name__ == "__main__":
    asyncio.run(main())
