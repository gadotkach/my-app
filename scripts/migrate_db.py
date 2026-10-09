"""Миграция данных PostgreSQL: dump + restore + проверка.

Использование:
    python scripts/migrate_db.py <SRC_URL> <DST_URL>

Пример:
    python scripts/migrate_db.py \\
        postgresql://user:pass@neon.tech/neondb \\
        postgresql://user:pass@yandex.cloud/db

Или с интерактивным вводом:
    python scripts/migrate_db.py
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def get_table_counts(db_url: str) -> dict[str, int]:
    """Возвращает количество записей в ключевых таблицах."""
    # Конвертируем URL для asyncpg
    async_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, echo=False)

    counts: dict[str, int] = {}
    async with engine.connect() as conn:
        for table in [
            "users",
            "marketplaces",
            "products",
            "sales",
            "marketplace_accounts",
            "user_consents",
            "audit_logs",
            "api_request_logs",
            "telegram_subscriptions",
            "ozon_ads_accounts",
            "tax_settings",
        ]:
            try:
                result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = result.scalar() or 0
            except Exception:
                counts[table] = -1  # таблица не найдена

    await engine.dispose()
    return counts


def pg_dump(src_url: str, output_file: str) -> None:
    """pg_dump в custom-формате (сжатый)."""
    print(f"→ Dumping from {src_url[:40]}...")
    # pg_dump не понимает postgresql+asyncpg://
    clean_url = src_url.replace("postgresql+asyncpg://", "postgresql://")

    result = subprocess.run(
        [
            "pg_dump",
            "--no-owner",
            "--no-acl",
            "--format=custom",
            f"--file={output_file}",
            clean_url,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: pg_dump failed: {result.stderr}")
        sys.exit(1)
    size_mb = Path(output_file).stat().st_size / 1024 / 1024
    print(f"  OK: {output_file} ({size_mb:.2f} MB)")


def pg_restore(dst_url: str, input_file: str) -> None:
    """pg_restore в целевую БД."""
    print(f"→ Restoring to {dst_url[:40]}...")
    clean_url = dst_url.replace("postgresql+asyncpg://", "postgresql://")

    result = subprocess.run(
        [
            "pg_restore",
            "--no-owner",
            "--no-acl",
            "--clean",
            "--if-exists",
            f"--dbname={clean_url}",
            input_file,
        ],
        capture_output=True,
        text=True,
    )
    # pg_restore может возвращать warning'и (не ошибки)
    if result.returncode != 0 and "errors ignored" not in result.stderr.lower():
        print(f"WARN: pg_restore returned {result.returncode}")
        print(f"  stderr: {result.stderr[:500]}")


async def main() -> None:
    # Проверим pg_dump в PATH
    if not shutil.which("pg_dump"):
        print("ERROR: pg_dump не найден в PATH")
        print(
            "Установите: brew install postgresql (macOS) "
            "или apt install postgresql-client (Ubuntu)"
        )
        sys.exit(1)

    # Аргументы
    if len(sys.argv) >= 3:
        src_url = sys.argv[1]
        dst_url = sys.argv[2]
    else:
        src_url = input("SRC DATABASE_URL: ").strip()
        dst_url = input("DST DATABASE_URL: ").strip()

    if not src_url or not dst_url:
        print("ERROR: пустые URL")
        sys.exit(1)

    # 1. Считаем записи ДО
    print("\n=== BEFORE (SRC) ===")
    src_counts = await get_table_counts(src_url)
    for table, count in src_counts.items():
        status = "OK" if count >= 0 else "не найдена"
        print(f"  {table:30} {count if count >= 0 else status}")

    # 2. Dump
    print()
    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as f:
        dump_file = f.name
    try:
        pg_dump(src_url, dump_file)

        # 3. Restore
        print()
        pg_restore(dst_url, dump_file)

        # 4. Считаем записи ПОСЛЕ
        print("\n=== AFTER (DST) ===")
        dst_counts = await get_table_counts(dst_url)
        for table, count in dst_counts.items():
            status = "OK" if count >= 0 else "не найдена"
            print(f"  {table:30} {count if count >= 0 else status}")

        # 5. Верификация
        print("\n=== VERIFY ===")
        all_ok = True
        for table in src_counts:
            src = src_counts[table]
            dst = dst_counts.get(table, -1)
            if src >= 0 and src == dst:
                print(f"  ✓ {table:30} {src} == {dst}")
            elif src == -1:
                print(f"  - {table:30} (не было в src)")
            else:
                print(f"  ✗ {table:30} src={src} dst={dst}")
                all_ok = False

        if all_ok:
            print("\n✅ Migration successful!")
        else:
            print("\n⚠️  Migration has differences — проверь вручную")

    finally:
        # Удалить временный dump
        if os.path.exists(dump_file):
            os.unlink(dump_file)
            print(f"\n→ Cleaned up {dump_file}")


if __name__ == "__main__":
    asyncio.run(main())
