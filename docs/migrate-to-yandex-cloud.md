# Миграция Neon → Yandex Cloud PostgreSQL

**Статус:** подготовлено (pre-pilot). Не выполнять до триггера.

**Триггер:** первый платящий клиент (ПДн клиентов) или требование РКН.

**Время:** 1 день.

---

## 10 шагов миграции

### 1. Создать Yandex Cloud PostgreSQL

- Yandex Cloud Console → Managed PostgreSQL.
- Версия: 15 (как Neon).
- Конфигурация: s2.micro (2 vCPU, 8 GB RAM).
- Диск: 50 GB SSD.
- Публичный доступ: да (для миграции), потом — нет.
- Цена: ~2 000-3 000 руб/мес.

### 2. Создать БД и пользователя

- БД: myapp_prod.
- Пользователь: myapp_user.
- Пароль: сохранить в 1Password.

### 3. Получить DATABASE_URL

Формат:

    postgresql+asyncpg://myapp_user:PASSWORD@rc1b-xxxxx.mdb.yandexcloud.net:6432/myapp_prod

Порт 6432 (PgBouncer) — для asyncpg.

### 4. Проверить доступ

    psql "postgresql://myapp_user:PASSWORD@rc1b-xxxxx.mdb.yandexcloud.net:6432/myapp_prod" -c "SELECT version();"

Ожидаемо: PostgreSQL 15.x.

### 5. Миграция данных (dump + restore)

Через скрипт:

    cd ~/projects/my-app
    source .venv/bin/activate

    # Установить pg_dump/pg_restore
    brew install postgresql  # macOS
    # или
    apt install postgresql-client  # Ubuntu

    python scripts/migrate_db.py \
        "postgresql://user:pass@neon.tech/neondb" \
        "postgresql://myapp_user:pass@yandex.cloud:6432/myapp_prod"

Скрипт делает:
1. Считает записи в SRC (before).
2. pg_dump → временный файл.
3. pg_restore → DST.
4. Считает записи в DST (after).
5. Сравнивает — verify.

Ожидаемо: Migration successful.

### 6. Применить Alembic (если нужно)

    docker compose -f docker-compose.prod.yml exec -T api alembic current
    docker compose -f docker-compose.prod.yml exec -T api alembic upgrade head

Ожидаемо: та же версия, что на Neon.

### 7. Обновить .env на VPS

    ssh root@91.142.73.226
    cd /opt/my-app
    nano .env

Заменить DATABASE_URL:

    DATABASE_URL=postgresql+asyncpg://myapp_user:PASSWORD@rc1b-xxxxx.mdb.yandexcloud.net:6432/myapp_prod

### 8. Перезапустить контейнер

    docker compose -f docker-compose.prod.yml up -d

Ожидаемо: Container my-app-api Started.

### 9. Проверить

    curl -s https://api.agregators.su/health

Ожидаемо: {"status":"ok","db":true}.

Проверка данных:

    docker compose -f docker-compose.prod.yml exec -T api python3 -c "
    import asyncio
    from sqlalchemy import text
    from app.database import AsyncSessionLocal

    async def main():
        async with AsyncSessionLocal() as s:
            r = await s.execute(text('SELECT COUNT(*) FROM users'))
            print('users:', r.scalar())

    asyncio.run(main())
    "

Ожидаемо: количество юзеров = SRC.

### 10. Отключить Neon (через неделю)

Не сразу — на случай rollback.
Проверить логи VPS 7 дней.
Если всё ок — отключить Neon.

---

## Rollback

    ssh root@91.142.73.226
    cd /opt/my-app
    nano .env
    # Вернуть старый DATABASE_URL (Neon)
    docker compose -f docker-compose.prod.yml up -d

Neon не удаляем — 30 дней после миграции.

---

## Чек-лист

- [ ] Yandex Cloud PostgreSQL создан (версия 15).
- [ ] БД myapp_prod + пользователь myapp_user.
- [ ] DATABASE_URL получен.
- [ ] psql работает.
- [ ] scripts/migrate_db.py выполнен успешно.
- [ ] Alembic: current совпадает.
- [ ] .env на VPS обновлён.
- [ ] Контейнер перезапущен.
- [ ] /health → db: true.
- [ ] Данные проверены.
- [ ] Логи 7 дней.
- [ ] Neon отключён.

---

## Стоимость

| Компонент | Цена/мес |
|---|---|
| Yandex Cloud PostgreSQL (s2.micro) | ~2 500 руб |
| Диск 50 GB SSD | ~500 руб |
| Итого | ~3 000 руб/мес |

Neon (free tier) — бесплатно, но:
- Не соответствует ФЗ-152 (Франкфурт, Германия).
- Ограничения по connections.
- Медленнее (Германия → VPS РФ).

Yandex Cloud:
- Соответствует ФЗ-152.
- Быстрее (РФ → РФ).
- Managed (бэкапы, обновления).

---

## Когда мигрировать

Триггеры:
1. Первый платящий клиент (ПДн клиентов).
2. Требование РКН (проверка).
3. Neon поднимает цену / проблемы с производительностью.

До этого — Neon (free) + VPS РФ (достаточно).
