# 📋 SPEC — SaaS-агрегатор маркетплейсов

**Версия:** 2.2 (обновлено 2026-10-08)
**Статус:** production-ready, работает из РФ без VPN

---

# ЧАСТЬ 1: ОПИСАНИЕ ПРОДУКТА

## Что это

SaaS-платформа для селлеров маркетплейсов. Селлер заходит в один личный кабинет и видит **consolidated-данные** со всех площадок (Ozon, Wildberries, Я.Маркет, AliExpress): товары, продажи, финансы, аналитику, юнит-экономику.

**Ключевая ценность:** селлер видит **реальную прибыль** по каждому товару с учётом комиссий, СПП, логистики, налогов и себестоимости — то, чего не даёт ни одна площадка в отдельности.

## Целевая аудитория

Селлеры на Ozon и Wildberries, работающие по FBO/FBS, с оборотом от 500 тыс ₽/мес.

## Ключевые отличия от конкурентов

| | Наш сервис | MPProfit | MPStatus |
|---|---|---|---|
| **Фокус** | Аналитика + юнит-экономика | Аналитика + реклама + 1С | Комбайн: аналитика + операционка |
| **Цена** | **990 ₽/мес** | 1500–5000 ₽/мес | 2000–6000 ₽/мес |
| **Юнит-экономика** | ✅ | ✅ | ✅ |
| **Калькулятор до закупки** | ✅ | ✅ | ✅ |
| **Реклама (ДРР)** | 🟡 roadmap | ✅ | ✅ |
| **Операционка FBS** | 🟢 roadmap | ❌ | ✅ |
| **PIM** | 🟢 roadmap | ⚠️ | ✅ |
| **1С-экспорт** | 🟡 roadmap | ✅ | ⚠️ |
| **Telegram-уведомления** | 🟡 roadmap | ✅ | ✅ |

**Стратегия:** узкий фокус на «реальной прибыли» + агрессивная цена. Не пытаемся догнать MPStatus в операционке.

---

# ЧАСТЬ 2: ТЕКУЩИЙ СТАТУС (production)

## Живые ссылки

| Что | URL |
|---|---|
| Frontend | https://agregators.su |
| Backend API | https://api.agregators.su |
| Swagger | https://api.agregators.su/docs |
| Health | https://api.agregators.su/health |
| GitHub backend | github.com/gadotkach/my-app |
| GitHub frontend | github.com/gadotkach/my-app-frontend |
| Neon (БД) | console.neon.tech |
| Cloudflare (DNS) | dash.cloudflare.com |

## Тестовые пользователи

Пароль: `secret123`

| Email | Подписка | Что делает |
|---|---|---|
| `trial-1789389840@example.com` | trialing | Доступ в кабинет, жёлтый бейдж |
| `alice@example.com` | none | Редирект на `/pricing` |

## Что работает в проде

### Backend
- ✅ Auth: JWT + refresh, trial 30 дней, защита от повторного получения
- ✅ Ozon: connect + sync products + sync sales (FBS + FBO), scheduler каждые 30 мин
- ✅ WB: connect + sync products, scheduler каждые 180 мин
- ⚠️ WB Sales API — deprecated (WB закрыл `reportDetailByPeriod`)
- ✅ Юнит-экономика: полный расчёт
- ✅ Аналитика: 9 эндпоинтов (см. Часть 4)
- ✅ Tax settings: CRUD
- ✅ **PATCH /products/{id}** — редактирование товаров (NEW)
- ✅ **Пропорциональные страховые взносы** в расчёте налогов
- ✅ **Ozon Ads API** (Performance API) — полный цикл
- ✅ **Ozon Ads UI** — карточка на `/integrations`
- ✅ **Scheduler: Ozon Ads** — раз в 6 часов
- ✅ **Telegram-уведомления** (NEW 2026-10-08) — connect/disconnect/settings/test
- ✅ **Telegram Scheduler**: `check_loss_making_products` (6h), `send_daily_reports` (6:00 UTC)
- ✅ **Telegram Proxy** — Cloudflare Worker `tg-proxy-agregators`
- ✅ **143 теста** (было 128, ранее 113)
- ✅ **Workflow `git pull`** на VPS — вместо `scp`
- ✅ **LoginRequest** — отдельная схема для `/auth/login` (без `name`)
- ✅ Авто-миграции Alembic при старте контейнера
- ✅ Шифрование API-ключей Fernet
- ✅ Авто-sync через `POST /integrations/sync-if-stale` (пороги: Ozon 15 мин, WB products 60 мин, WB sales 180 мин)

### Frontend
- ✅ Auth flow (login/register/refresh/logout)
- ✅ Dashboard со сводкой и фильтром 7/30/90 дней
- ✅ `/products` — список товаров + **модалка редактирования** (себестоимость, габариты)
- ✅ `/sales` — список продаж
- ✅ `/integrations` — connect Ozon + WB
- ✅ `/calculator` — калькулятор юнит-экономики
- ✅ `/unit-economics` — таблица прибыли по товарам (NEW)
- ✅ `/tax-settings` — форма налогов (NEW)
- ✅ `/pricing` — 990 ₽/мес
- ✅ `/expired` — окончание trial
- ✅ `/notifications` — Telegram-уведомления (NEW 2026-10-08): connect, настройки, тест
- ✅ **Mobile UI** — карточки / бургер / скролл (NEW 2026-10-08)
- ✅ **Favicon + title «Agregators»** (NEW 2026-10-08)
- ✅ Авто-sync при заходе на страницы (без кнопок)

### Mobile UI (NEW 2026-10-08)

**Принцип:** Tailwind `hidden md:block` + `md:hidden` карточки (breakpoint 768px).

**Карточки на mobile (< 768px):**

- `/sales` — карточки (Заказ / Цена / Комиссия / Логистика / Продано)
- `/products` — карточки + кнопка «Редактировать»
- `/advertising` — карточки + кнопка «Удалить»

**Скролл на mobile (< 768px):**

- `/dashboard` — «По площадкам» (6 колонок)
- `/profit` — 12 колонок
- `/abc` — 5 колонок + pie-chart
- `/unit-economics` — 13 колонок

**Layout — бургер-меню:**

- Desktop (md+): горизонтальное меню (11 ссылок).
- Mobile (< md): бургер (три полоски) → выпадающее меню.

**Интеграции — flex-col на mobile:**

- `/integrations`: карточки Ozon / WB / Ozon Ads — `flex flex-col md:flex-row`.
- Кнопки — `flex flex-wrap` (переносятся в столбик).

### Брендинг (NEW 2026-10-08)

- **Название:** Agregators — аналитика маркетплейсов.
- **Favicon:** `public/favicon.png` (120 KB).
- **`<title>`:** `Agregators — аналитика маркетплейсов`.
- **`<meta name="description">`:** SEO-описание.
- **`theme-color`:** `#2563eb`.
- **`apple-touch-icon`:** `/favicon.png`.
- **`lang="ru"`.**

### Инфраструктура
- ✅ VPS #1 (91.142.73.226, РФ) — backend + frontend
- ✅ Caddy (SSL Let's Encrypt, reverse-proxy)
- ✅ Neon PostgreSQL (managed, Frankfurt)
- ✅ Cloudflare DNS (DNS only для всех записей)
- ✅ GitHub Actions — автодеплой фронта (rsync через SSH)
- ✅ Docker Compose для backend
- ✅ Scheduler: Ozon 30 мин, WB 180 мин, Ozon Ads 6ч, Loss check 6ч, Daily reports 6:00 UTC
- ✅ **Cloudflare Worker** `tg-proxy-agregators` — edge-прокси для Telegram API

### Качество
- ✅ **143 теста**, все зелёные (Mac + VPS)
- ✅ mypy strict, ruff, pre-commit
- ⚠️ CI не настроен для backend (pre-push hook есть)
- ✅ **GitHub Actions** — автодеплой (CI #75 - #90, Deploy #15 - #21)

---

# ЧАСТЬ 3: СТЕК ТЕХНОЛОГИЙ

## Backend
| Слой | Технология |
|---|---|
| Фреймворк | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0.36 (async) |
| Драйвер БД | asyncpg 0.30 |
| БД прод | Neon PostgreSQL (Frankfurt) |
| Миграции | Alembic 1.13 (async) |
| Auth | JWT (access + refresh, HttpOnly cookie) |
| Пароли | bcrypt через passlib |
| Шифрование ключей | Fernet (`ENCRYPTION_KEY` в env) |
| Scheduler | APScheduler 3.10 (async) |
| HTTP-клиент | httpx |
| Pydantic | 2.9.2 |
| Тесты | pytest + pytest-asyncio, 113 тестов |

## Frontend
| Слой | Технология |
|---|---|
| Фреймворк | React 18 + TypeScript |
| Сборка | Vite 4 |
| Стили | Tailwind CSS 3 |
| Состояние | Zustand |
| HTTP | axios + interceptors (auto-refresh) |
| Роутинг | React Router 6 |
| Хостинг | VPS #1 (РФ), статика через Caddy |

## Инфраструктура
| Компонент | Где |
|---|---|
| Backend + Frontend | VPS #1 (91.142.73.226, РФ) |
| Reverse-proxy + SSL | Caddy (Let's Encrypt) |
| БД | Neon PostgreSQL |
| DNS | Cloudflare |
| CI/CD фронта | GitHub Actions |
| Локально | Docker Compose (my-app-api + my-app-db) |

---

# ЧАСТЬ 4: МОДЕЛИ ДАННЫХ

## `User`
- `id`, `email` (unique), `name`, `hashed_password`
- `subscription_status` (`none` / `trialing` / `active` / `expired`)
- `trial_started_at`, `trial_ends_at`, `subscription_ends_at`
- `created_at`

## `Marketplace` (справочник)
- `id`, `code` (unique), `name`
- Known: `ozon`, `wildberries`, `yandex_market`, `aliexpress`, `avito`
- ⚠️ WB в БД имеет код `wildberries`, хотя API-пути — `/integrations/wb/*`

## `DeliveryService` (справочник)
- `id`, `code` (unique), `name`
- Known: `cdek`, `boxberry`, `russian_post`, `dhl`

## `Product`
- `id`, `user_id`, `sku` (unique с user_id), `name`, `description`
- **Юнит-экономика:** `cost_price`, `volume_liters`, `length_cm`, `width_cm`, `height_cm`
- `created_at`

## `Sale`
- `id`, `user_id`, `marketplace_id`, `product_id`, `delivery_service_id`
- `external_id`, `quantity`, `price`, `sold_at`, `created_at`
- **Юнит-экономика:**
  - `commission`, `commission_percent`
  - `logistics_cost`, `return_logistics_cost`
  - `acquiring_fee`, `acquiring_percent`
  - `storage_cost`
  - `spp_percent`, `spp_amount`, `retail_price_with_spp`
  - `payout_amount`
- **🟡 ROADMAP: реклама** — `advertising_cost`, `advertising_type` (internal/external)

## `MarketplaceAccount`
- `id`, `user_id`, `marketplace_id`
- `client_id` (nullable — у WB нет)
- `api_key_encrypted` (Fernet)
- `created_at`, `updated_at`, **`last_sync_at`** (NEW)
- `user`, `marketplace` (relationships)

## `TaxSettings`
- `id`, `user_id` (unique — one-to-one)
- `tax_system` (`NPD` / `USN_INCOME` / `USN_INCOME_EXPENSE` / `PSN`)
- `tax_rate` (Decimal 5,2)
- `insurance_contributions` (default 57390 ₽ — взносы ИП 2026)
- `vat_enabled`, `vat_rate`
- `created_at`, `updated_at`

## `OzonAdsAccount` (NEW 2026-10-08)
- `id`, `user_id` (unique — one-to-one)
- `client_id` — Ozon Performance API Client ID (не секрет)
- `client_secret_encrypted` — Fernet
- `last_sync_at`, `created_at`, `updated_at`

## `TelegramSubscription` (NEW 2026-10-08)
- `id`, `user_id` (unique — one-to-one)
- `chat_id` (unique) — Telegram chat ID
- `telegram_username` — @username (опционально)
- Флаги: `notify_new_sales`, `notify_loss_making`, `notify_daily_report`, `notify_drr_high`
- `drr_threshold` (Decimal 5,2, default 50.00)
- `connected_at`, `last_notification_at`

## `RefreshToken`, `TrialIdentity`, `Payment`
- `RefreshToken` — refresh-токены с ротацией
- `TrialIdentity` — защита от повторного trial
- `Payment` — история платежей (для ЮKassa, готово но отключено)

---

# ЧАСТЬ 5: API-ЭНДПОИНТЫ

## Auth
- `POST /auth/register` — регистрация + trial 30 дней (`UserCreate`: email, name, password)
- `POST /auth/login` — вход, access + refresh (`LoginRequest`: email, password — без name)
- `POST /auth/refresh` — обновление access
- `POST /auth/logout` — выход
- `GET /users/me` — текущий юзер с подпиской

## Products
- `POST /products` — создание
- `GET /products` — список
- `GET /products/{id}` — детали
- 🟡 **ROADMAP: `PATCH /products/{id}`** — обновление (себестоимость, габариты)

## Sales
- `POST /sales`, `GET /sales`

## Marketplaces, DeliveryServices
- `GET /marketplaces`, `GET /delivery-services` — публичные справочники

## Integrations
### Ozon
- `POST /integrations/ozon/connect`
- `POST /integrations/ozon/sync/products`
- `POST /integrations/ozon/sync/sales?from=...&to=...`
- Внутри sync — **FBS + FBO** (универсально)

### WB
- `POST /integrations/wb/connect`
- `POST /integrations/wb/sync/products`
- `POST /integrations/wb/sync/sales?from=...&to=...` — ⚠️ API deprecated
- ⚠️ Лимиты Базового токена: products 1/час, sales 1/3 часа

### Ozon Ads (Performance API)
- `POST /integrations/ozon-ads/connect` — сохранение credentials
- `GET /integrations/ozon-ads/account` — статус подключения
- `DELETE /integrations/ozon-ads/account` — отключение
- `POST /integrations/ozon-ads/sync?from=&to=` — sync расходов

### Общие
- `GET /integrations/accounts` — список подключённых
- `POST /integrations/sync-if-stale` — авто-sync (NEW, пороги)

## Tax Settings
- `GET /tax-settings`, `PUT /tax-settings`, `DELETE /tax-settings`

## Analytics (9 эндпоинтов)
- `GET /analytics/summary?from=...&to=...`
- `GET /analytics/by-marketplace?from=...&to=...`
- `GET /analytics/by-product?from=...&to=...`
- `GET /analytics/unit-economics?product_id=...&from=...&to=...` — по одному товару
- `GET /analytics/unit-economics/all?from=...&to=...` — **по всем товарам (NEW)**
- `GET /analytics/profit?from=...&to=...` — сводка прибыли по площадкам
- `GET /analytics/abc?from=...&to=...` — ABC-анализ
- `POST /analytics/calculator` — калькулятор до закупки

## Utility
- `GET /health` — health check
- `GET /docs` — Swagger

---

# ЧАСТЬ 6: FRONTEND-СТРАНИЦЫ

| URL | Что показывает | Статус |
|---|---|---|
| `/login`, `/register` | Auth | ✅ |
| `/` | Dashboard (сводка, 5 карточек, фильтр 7/30/90, авто-sync) | ✅ |
| `/products` | Список товаров | ✅ |
| `/sales` | Список продаж | ✅ |
| `/integrations` | Ozon + WB + **Ozon Ads** карточки + sync | ✅ |
| `/calculator` | Калькулятор юнит-экономики | ✅ |
| `/unit-economics` | **Таблица прибыли по товарам** (фильтр убыточных, сортировка) | ✅ |
| `/pricing` | Тариф 990 ₽/мес | ✅ |
| `/expired` | Окончание trial | ✅ |

## ✅ ЗАКРЫТО: Mobile UI (2026-10-08)

- Sales / Products / Advertising — карточки на mobile.
- Layout — бургер-меню.
- Integrations — flex-col.
- Dashboard / Profit / Abc / UnitEconomics — скролл.
- Favicon + title «Agregators».
- Deploy #19–#21.

## 🟢 ROADMAP v2.5+: новые фичи (2026-10-08)

### 1. SEO-анализ карточки (приоритет 1, 6-10 ч)

**Цель:** ключевые запросы по товару — по каким запросам находят WB/Ozon.

**Данные:**
- WB: `analytics.wildberries.ru/api/v2/search-queries`.
- Ozon: `api-seller.ozon.ru/v1/analytics/query`.

**Модель:** `ProductSEOQuery` (product_id, query, position, frequency, date).

**UI:** `/seo` или вкладка в `/products/{id}`.

**Backend:** `app/services/seo_analyzer.py`, роутер `/analytics/seo`.

### 2. Воронка продаж (приоритет 1, 4-6 ч)

**Цель:** показы → клики → корзина → заказ — по каждому товару.

**Данные:**
- WB: `suppliers-analytics.wildberries.ru/api/v2/funnel`.
- Ozon: `api-seller.ozon.ru/v1/analytics/data`.

**Модель:** `ProductFunnel` (product_id, date, impressions, clicks, add_to_cart, orders).

**UI:** вкладка в `/products/{id}` или `/funnel`.

**Backend:** `app/services/funnel_analyzer.py`, роутер `/analytics/funnel`.

### 3. Бенчмарки (приоритет 2, 1-2 дня)

**Цель:** сравнить твои метрики с медианой категории.

**Данные:**
- Парсинг WB/Ozon каталога (топ-100 по категории).
- Или WB API `content/v2/get/cards/list` + публичные.

**Модель:** `Benchmark` (category, metric, median_value, computed_at).

**UI:** `/benchmarks` или блок в `/dashboard`.

**Backend:** `app/services/benchmark.py`.

### 4. AI-помощник (приоритет 3, 2-3 дня)

**Цель:** чат с данными — «почему упала прибыль?», «какой товар убыточный?».

**LLM:** YandexGPT (для РФ, оплата в рублях) или OpenAI.

**Backend:** `app/services/ai_assistant.py`.

**UI:** плавающий виджет чата.

**Модель:** `AIConversation`.

### NOT DOING (есть у mpstats — нам не нужно)

- Фоторедактор AI — не наша компетенция.
- Биддер — риск (нужно доверие).
- Плагин для браузера — неудобно поддерживать.
- Внешняя аналитика всего WB/Ozon — дорого.
- Автоответы — не наша тема.
- Управление ценой — риск.

### Сравнение с mpstats

| Функция | Мы | mpstats |
|---|---|---|
| Юнит-экономика | точная | оценка |
| ДРР по источникам | есть | оценка |
| Telegram-уведомления | есть | нет |
| Цена | 990 руб | 3000+ руб |
| Простой UI | да | перегружен |
| SEO-анализ | roadmap | есть |
| Воронка | roadmap | есть |
| Внешняя аналитика | нет | есть |
| AI-фоторедактор | нет | есть |

**Позиционирование:** «Точный расчёт прибыли за 990 руб/мес»
vs mpstats «Аналитика рынка + AI за 30000 руб/мес».

## 🔴 Селлер (Т-Банк) — анализ конкурента (2026-10-08)

**Игрок:** Т-Банк (бывший Тинькофф) — крупнейший российский банк.
**Продукт:** «Селлер» — аналитика маркетплейсов.
**Позиционирование:** «Единое окно для работы с WB и Ozon».

### Тарифы Селлера

| Тариф | Цена | Что входит |
|---|---|---|
| Селлер S | Бесплатно | Базовое (изменение цен/остатков, напоминания) |
| Селлер M | 10 000 руб/мес (4 000 при годовой) | Всё |
| Свой тариф | От 2 999 руб/мес | Выбор инструментов |

### Функции Селлера

- Аналитика ниш (поиск прибыльных товаров, топ-100 по категории).
- Аналитика продаж (динамика заказов, расходы, заработок).
- Расчёт прибыльности (юнит-экономика).
- Управление ценами и остатками.
- Напоминания о пополнении.
- Нейросеть для автоответов на отзывы WB.
- SEO-описания от нейросети.
- Анализ конкурентов.
- Рекомендации по продвижению WB.
- Управление рекламой WB.

### Что НЕ делает Селлер (наши плюсы)

- Нет Ozon Ads API (авто-расходы на рекламу).
- Нет Telegram-уведомлений.
- Нет точной юнит-экономики с налогами.
- Нет WB Ads (Продвижение).
- Нет ДРР по источникам (только оценка).
- Нет mobile UI (предположительно).

### Что делает Селлер (наши пробелы)

- Аналитика ниш — парсинг WB/Ozon каталога.
- Анализ конкурентов — сравнение SKU.
- Нейросеть для отзывов (автоответы).
- SEO-описания (LLM).
- Управление ценами/остатками (операционка).
- Бесплатный тариф S (freemium).
- Интеграция с Т-Банком (расчётный счёт, эквайринг).

### Таблица: Мы vs mpstats vs Селлер

| Функция | Мы (Agregators) | mpstats | Селлер (Т-Банк) |
|---|---|---|---|
| Цена | 990 руб/мес | 3 000-30 000 руб | 2 999-10 000 руб |
| Юнит-экономика | Точная (все налоги) | Оценка | Есть |
| ДРР по источникам | Есть (Ozon Ads + WB) | Оценка | Оценка |
| Авто-расходы Ozon Ads | Есть | Нет | Нет |
| Telegram-уведомления | Есть | Нет | Нет |
| Аналитика ниш | Roadmap | Есть | Есть |
| SEO-анализ | Roadmap | Есть | Есть |
| Анализ конкурентов | Roadmap | Есть | Есть |
| AI (отзывы/SEO) | Roadmap | Частично | Есть |
| Плагин браузера | Нет | Есть | Нет |
| Бесплатный тариф | Trial 30 дней | Нет | Селлер S |
| Mobile UI | Есть | Частично | Неизвестно |
| Бренд | Нет | Есть | Т-Банк |

### Наше позиционирование

**Против mpstats:** «Точная прибыль за 990 руб vs аналитика рынка за 30 000 руб».

**Против Селлера:** «Точная прибыль + Telegram-уведомления за 990 руб vs всё-в-одном от банка за 10 000 руб».

**Наше УТП:**
1. Точная юнит-экономика (все налоги, комиссии, ДРР).
2. Авто-расходы на рекламу (Ozon Ads API) — уникально.
3. Telegram-уведомления — проактивно.
4. Простой UI — 5 минут.
5. 990 руб/мес — в 3-10 раз дешевле.

### Новые фичи из анализа Селлера (ROADMAP v2.6+)

**Приоритет 1 (1-2 недели):**

- Аналитика ниш — парсинг WB/Ozon каталога, топ-100 товаров по категории.
  - Модель: `NicheAnalysis` (category, query, budget_from, budget_to, products[]).
  - UI: страница `/niches` с поиском + фильтрами.
  - Backend: `app/services/niche_analyzer.py` (парсер + агрегатор).
  - Данные: WB `content/v2/get/cards/list` + публичный каталог, Ozon `v1/product/list`.

- Анализ конкурентов — сравнение своих SKU с топ-10 в категории.
  - Модель: `CompetitorAnalysis` (product_id, competitor_sku, price, rating, reviews_count).
  - UI: вкладка в `/products/{id}` — «Конкуренты».
  - Backend: `app/services/competitor_analyzer.py`.

**Приоритет 2 (2-4 недели):**

- SEO-описания от LLM (YandexGPT) — генерация title/description.
- Автоответы на отзывы (LLM + WB API).
- Бесплатный тариф (freemium, 10 SKU) — для виральности.

**Приоритет 3 (не берём):**

- Управление ценами/остатками (операционка).
- Интеграция с банком (недоступно).
- Плагин для браузера (неудобно поддерживать).

## 🔴 Конкурент C — WB-only аналитика + AI (2026-10-08)

**Продукт:** сервис оцифровки и аналитики для WB (название не указываем).

**Позиционирование:** аналитика ниш + AI + SEO + плагин.

**Фокус:** ТОЛЬКО Wildberries (не работает с Ozon).

### Тарифы

| Тариф | Цена | Что входит |
|---|---|---|
| Старт | 2 250 руб/мес | 1 магазин, до 2 млн оборота |
| Оптимальный | 4 490 руб/мес | 3 магазина, до 7 млн |
| Расширенный | 7 990 руб/мес | 5 магазинов, от 7 млн |

Скидки: 3 мес - 15%, 6 мес - 25%, 12 мес - 35%.

### Функции

- Внутренняя аналитика (динамика продаж/прибыли/оборачиваемости, ABC).
- Отчётность (авто-подгрузка WB отчётов, анализ списаний).
- Рыночные данные и конкуренты (частота запросов, топы карточек, SEO).
- AI-модуль (подбор ассортимента, сезонность, прогноз закупок).
- Финансовая аналитика (60+ метрик, PnL, регионы, склады).
- SEO и ключевые запросы (SEO-прокачка, сравнение с ТОПами).
- Поиск ниш и трендов (с 2022 года).
- Плагин для браузера (мгновенный доступ).
- Автопоиск ниш (фильтры по бюджету/категориям).

### Что НЕ делает (наши плюсы)

- Только WB (нет Ozon).
- Нет Ozon Ads API (авто-расходы).
- Нет Telegram-уведомлений.
- Нет WB Ads (Продвижение).
- Нет ДРР по источникам.
- Нет mobile UI (предположительно).

### Что делает (наши пробелы)

- Аналитика ниш (с 2022 года).
- AI-модуль для ассортимента (сезонность, прогноз закупок).
- Анализ конкурентов (топы карточек).
- SEO-прокачка (ключевые запросы, сравнение с ТОПами).
- Плагин для браузера.
- 60+ метрик.
- История данных с 2022.

### Таблица: 4 конкурента

| Функция | Мы | mpstats | Селлер (Т) | Конкурент C |
|---|---|---|---|---|
| МП | Ozon + WB | WB + Ozon | Ozon + WB | Только WB |
| Цена | 990 руб | 3 000-30 000 руб | 2 999-10 000 руб | 2 250-7 990 руб |
| Юнит-экономика | Точная | Оценка | Есть | Есть |
| ДРР по источникам | Есть | Оценка | Оценка | Оценка |
| Авто-расходы Ozon Ads | Есть | Нет | Нет | Нет |
| Telegram | Есть | Нет | Нет | Нет |
| Аналитика ниш | Roadmap | Есть | Есть | Есть |
| AI (ассортимент) | Roadmap | Частично | Частично | Есть |
| SEO | Roadmap | Есть | Есть | Есть |
| Анализ конкурентов | Roadmap | Есть | Есть | Есть |
| Плагин | Нет | Есть | Нет | Есть |
| Бесплатный тест | 30 дней | Нет | S (freemium) | Заявка |
| Mobile UI | Есть | Частично | Неизвестно | Неизвестно |

### Новые фичи из анализа (ROADMAP v2.8+)

**Приоритет 2 (1-2 месяца):**

- AI-модуль для ассортимента — подбор товаров по бюджету, сезонность, прогноз закупок.
  - Модель: `AIAssortment` (user_id, category, budget, season, recommendations[]).
  - Backend: `app/services/ai_assortment.py` (YandexGPT + данные WB/Ozon).
  - UI: страница `/assortment` или вкладка в `/niches`.

- Плагин для браузера — расширение для WB/Ozon (Chrome/Firefox).
  - Показывает: юнит-экономику, ДРР, прибыль — прямо на странице товара.
  - Backend: API `/plugin/*` (публичный, с rate limit).
  - Frontend: расширение (TypeScript + Chrome Extension API).

**Приоритет 2 (сейчас):**

- История данных с 2022 — накопление через периодический парсинг/API.
  - Ценно через год (тренды, сезонность).
  - Начать сейчас — задача scheduler.

- 60+ метрик — расширить аналитику (сейчас ~20).
  - Добавить: оборачиваемость, средний чек, LTV, retention, конверсии.

**Приоритет 3 (не берём):**

- Фокус только на WB (у нас Ozon + WB).

## 🔐 ФЗ-152: Защита персональных данных (NEW 2026-10-09)

**ФЗ-152** — «О персональных данных» (2006). Обязателен для SaaS в РФ.

**Ответственный за ПДн:** владелец продукта (он же юрист).

### Что считаем ПДн

- ФИО, email, телефон (при регистрации).
- IP-адрес, cookie, user-agent (логи).
- Данные о продажах (если привязаны к физлицу).
- Реквизиты для оплаты (ЮKassa обрабатывает отдельно).

### Что НЕ считаем ПДн

- SKU, названия товаров (публичные).
- Агрегированные метрики (выручка, прибыль).
- API-ключи маркетплейсов (шифруются, но не ПДн).

### Хранение данных

- VPS в РФ (91.142.73.226) — соответствует локализации.
- **Neon PostgreSQL (Frankfurt) — ⚠️ КРИТИЧНО.**
  - Требование ФЗ-152: ПДн граждан РФ — на территории РФ.
  - Германия — не соответствует.
  - **План: переезд на Yandex Cloud PostgreSQL (РФ) — 2-3 дня.**
- Шифрование API-ключей — Fernet (уже).
- Пароли — bcrypt (уже).

### Юридические документы (юрист — владелец)

- Политика конфиденциальности — страница `/privacy` + текст от юриста.
- Согласие на обработку ПДн — чекбокс на регистрации.
- Уведомление Роскомнадзора — подать (форма на сайте РКН).
- Приказ о назначении ответственного за ПДн.
- Журнал учёта обращений субъектов ПДн.
- Модель угроз ИСПДн.
- Соглашение об обработке с подрядчиками (Neon, Yandex, Cloudflare).

### Технические меры (backend + frontend)

**1. Согласие на регистрации**

- Frontend: чекбокс «Согласен с обработкой ПДн» (обязательный).
- Backend: модель `UserConsent` (user_id, consent_type, granted_at, ip, user_agent).
- При регистрации: `POST /auth/register` пишет consent.
- При отзыве: `DELETE /users/me/consent` → soft delete аккаунта через 30 дней.

**2. Политика конфиденциальности**

- Frontend: страница `/privacy`.
- Ссылки в футере + при регистрации.
- Текст: юрист.

**3. Право на экспорт**

- `GET /users/me/export` — вернуть все данные пользователя (JSON).
- Включает: user, products, sales, integrations, subscriptions, consents.
- Формат: JSON, скачивается как файл.

**4. Право на удаление**

- `DELETE /users/me` — soft delete (30 дней), потом hard delete.
- Каскадное удаление: products, sales, integrations, subscriptions.
- Анонимизация: email → `deleted_<uuid>@deleted.local`.

**5. Логирование доступа к ПДн**

- Модель `AuditLog` (user_id, action, resource, ip, user_agent, created_at).
- Middleware на роутерах `/users/*`, `/auth/*`, `/integrations/*`.
- Хранение: 1 год (требование РКН).
- Действия: login, register, update_profile, delete_account, export.

**6. Обезличивание в логах**

- Middleware: маскировать email (`a***@example.com`), phone (`+7***1234`).
- В логах не хранить ПДн в открытом виде.
- Отдельный logger для security-events.

### Процедуры

- Уведомление об утечке — 72 часа (РКН + субъекты).
- Ответственный за ПДн — владелец (приказом).
- Журнал обращений субъектов ПДн (Excel или отдельная таблица).
- Аудит ИСПДн — раз в 3 года.

### Roadmap: ФЗ-152

**Фаза 1 (2-3 дня):**

- Чекбокс согласия на регистрации (frontend).
- Модель `UserConsent` + миграция (backend).
- `POST /auth/register` — запись consent.
- Страница `/privacy` (frontend).
- `GET /users/me/export` (backend).
- `DELETE /users/me` — soft delete (backend).

**Фаза 2 (3-5 дней):**

- Модель `AuditLog` + middleware (backend).
- Обезличивание в логах (backend).
- **Neon → Yandex Cloud PostgreSQL** (инфра).
- Обновить `.env` на VPS.

**Фаза 3 (юрист):**

- Уведомление РКН.
- Модель угроз ИСПДн.
- Приказ о назначении ответственного.
- Журнал обращений.
- Соглашение с подрядчиками.

**Фаза 4 (постоянно):**

- Журнал обращений субъектов.
- Аудит ИСПДн (раз в 3 года).
- Обновление политики при изменениях.

### Штрафы за несоответствие

- До 300 000 руб — за нарушения.
- До 500 000 руб — за утечку.
- До 3 000 000 руб — за повторные.
- Уголовная — за утечку (ст. 272.1 УК).

### НЕ ДЕЛАЕМ

- Биометрия — не собираем.
- Паспортные данные — не собираем.
- Медицинские данные — не собираем.

## 🟢 Расширяемая архитектура интеграций (NEW 2026-10-08)

**Цель:** добавление нового маркетплейса — за 1-2 часа (не за день).

### 3 уровня абстракции

**Уровень 1. BaseMarketplaceClient (ABC)**

Общий интерфейс для всех МП:

- `code`, `name`, `api_base` — атрибуты класса.
- `_authenticate()` — обязательный, получить токен.
- `list_products()` — обязательный.
- `list_sales()` — обязательный.
- `list_advertising_expenses()` — опциональный (по умолчанию пусто).
- `get_warehouse_stocks()` — опциональный.
- `_get_token()` — общий, с кешем.
- `_request()` — общий, httpx + retry + rate limit + 401-handling.

**Уровень 2. MarketplaceRegistry**

Реестр клиентов:

- `@MarketplaceRegistry.register` — декоратор.
- `MarketplaceRegistry.get(code)` — получить класс.
- `MarketplaceRegistry.all()` — все зарегистрированные.
- Авто-импорт в `app/marketplaces/__init__.py`.

**Уровень 3. UI генерируется из config**

Backend отдаёт `GET /marketplaces`:

```json
{
  "marketplaces": [
    {
      "code": "ozon",
      "name": "Ozon",
      "fields": [
        {"name": "client_id", "label": "Client-Id", "type": "text"},
        {"name": "api_key", "label": "API-Key", "type": "password"}
      ],
      "has_ads": true,
      "has_products": true,
      "has_sales": true
    }
  ]
}
Frontend рендерит форму из fields + карточку на /integrations. 0 правок на новый МП.

Добавление нового МП (пример: Мегамаркет)
app/marketplaces/megamarket.py — ~150 строк (config + 4 метода).

@MarketplaceRegistry.register — 1 строка.

Миграция seed — 1 запись в Marketplace.

Frontend — 0 правок (форма сгенерируется).

Scheduler — auto (обходит все зарегистрированные).

Итого: 1-2 часа (vs день).

Roadmap: фазы
Фаза 1 (1 день) — BaseMarketplaceClient + MarketplaceRegistry.

Фаза 2 (1 день) — Рефакторинг Ozon (наследник Base).

Фаза 3 (1 день) — Рефакторинг WB (наследник Base).

Фаза 4 (1 день) — Frontend: генерация форм.

Фаза 5 (2 ч) — Новый МП (Яндекс.Маркет) — проверка архитектуры.

Итого: ~3-4 дня.

🟢 Яндекс.Маркет — интеграция (приоритет 1)
Почему Яндекс.Маркет: есть API, есть спрос, в SPEC уже code = "yandex_market".

API:

URL: https://api.partner.market.yandex.ru.

Авторизация: OAuth (получается в ЛК Яндекс.Маркета).

Endpoints:

/campaigns — кампании.

/campaigns/{id}/offers — товары.

/campaigns/{id}/orders — заказы.

/campaigns/{id}/stats — статистика.

План (по новой архитектуре):

app/marketplaces/yandex_market.py — клиент (наследник Base).

MarketplaceAccount — работает (уже универсальный).

Миграция: seed yandex_market в Marketplace.

UI: карточка на /integrations (сгенерируется).

Scheduler: sync_yandex_market_all_accounts.

Оценка: 1 день (после Фазы 1-4).

Пилот: Яндекс.Маркет — проверка расширяемой архитектуры.

🟢 1С — интеграция (приоритет 2)
Что: обмен данными с 1С (бухгалтерия, склад, себестоимость).

Зачем:

Себестоимость товаров из 1С (автоматически).

Остатки из 1С (для FBS).

Выгрузка продаж в 1С (для бухгалтерии).

API 1С:

1С:Предприятие имеет HTTP-сервисы (REST).

Или: OData (стандартный протокол).

Или: обмен через файлы (XML, CSV).

План:

app/integrations/1c_client.py — клиент (httpx).

Настройки: URL 1С + логин/пароль.

Модель: OneCAccount (user_id, url, credentials_encrypted).

Роутер: /integrations/1c/* — connect/disconnect/sync.

Синк: себестоимость — Product.cost_price, остатки — Product.stock.

UI: карточка на /integrations (по аналогии с МП).

Оценка: 2-3 дня (зависит от версии 1С).

Приоритет: 2 (после Яндекс.Маркета).

🟡 Банк — подготовка интеграции (приоритет 3)
Что: интеграция с банком (Сбер, Т-Банк, Альфа) для:

Расчётный счёт (выписки — авто-учёт).

Эквайринг (поступления от покупателей).

Кредиты (кредитная линия для селлеров).

API банков:

Сбер: https://api.sberbank.ru (СберБизнес API).

Т-Банк: https://business.tinkoff.ru/openapi.

Альфа: https://api.alfabank.ru.

План (подготовка, не делать сразу):

Изучить API (3 банка).

Выбрать 1 банк (приоритет).

Модель: BankAccount (user_id, bank_code, credentials).

Клиент: app/integrations/bank_client.py.

Синк: выписки — транзакции.

UI: карточка на /integrations.

Оценка: 3-5 дней (зависит от банка).

Приоритет: 3 (пока не нужно для core-функций).

🟡 ROADMAP: страницы

| URL | Что | Эндпоинт готов? |
|---|---|---|
| `/profit` | Дашборд по площадкам | ✅ |
| `/abc` | ABC-анализ (pie-chart) | ✅ |
| `/tax-settings` | Форма налогов | ✅ |
| `/products/{id}` | Карточка товара + редактирование | 🟡 нужен бэкенд |

## Mobile UI паттерны (NEW 2026-10-08)

### Карточки на mobile (небольшие таблицы, до 6 колонок)

Desktop: div.hidden.md:block.overflow-x-auto > table.

Mobile: div.md:hidden.divide-y > карточки.

Карточка: div.p-4.space-y-2, внутри:
- flex justify-between — SKU + дата.
- flex justify-between — label + value (несколько строк).
- Кнопка действия (например, "Редактировать").

### Скролл на mobile (большие таблицы, > 8 колонок)

Обёртка div.overflow-x-auto вокруг table.

### Бургер-меню (Layout.tsx)

- useState(false) → menuOpen.
- Кнопка md:hidden с SVG (три полоски / крестик).
- Desktop-меню: hidden md:flex.
- Mobile-dropdown: {menuOpen && div.md:hidden}.

### flex-col на mobile (карточки с кнопками)

div.flex.flex-col.md:flex-row.md:items-center.md:justify-between.gap-3
внутри — div.flex.flex-wrap.gap-3 с кнопками.

## Стиль фронта
- `max-w-6xl` / `max-w-7xl` для страниц, `text-2xl font-bold` для заголовков
- Карточки: `bg-white rounded-lg shadow-sm p-5`
- Формат денег: `Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" })`
- Ошибки: `bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md`
- Убыточные строки: `bg-red-50`, прибыльные значения — `text-green-600`

---

# ЧАСТЬ 7: ИНФРАСТРУКТУРА

## VPS #1 (91.142.73.226, РФ, Ubuntu 22.04)
- **1 vCPU, 1.9 ГБ RAM, 50 ГБ SSD, 2 ГБ swap**
- Боты (не трогаем): `pairs-bot.service`, `pairs-moex.service`
- Backend: `/opt/my-app`, Docker Compose
- Frontend: `/var/www/agregators/` (статика)
- Caddy: `/etc/caddy/Caddyfile`

### Caddyfile
```caddy
agregators.su {
    root * /var/www/agregators
    file_server
    try_files {path} /index.html
    encode gzip
}

www.agregators.su {
    redir https://agregators.su{uri} permanent
}

api.agregators.su {
    reverse_proxy localhost:8000
    encode gzip
}
```

## Cloudflare DNS

| Name | Type | Content | Proxy |
|---|---|---|---|
| `agregators.su` | A | `91.142.73.226` | DNS only ⚪ |
| `www.agregators.su` | A | `91.142.73.226` | DNS only ⚪ |
| `api.agregators.su` | A | `91.142.73.226` | DNS only ⚪ |

## Neon (PostgreSQL)

- Region: `aws-eu-central-1` (Frankfurt)
- Plan: Free
- **URL:** без `-pooler` (asyncpg не работает с PgBouncer в transaction mode)

## GitHub Actions (автодеплой фронта)

- **Триггер:** push в `main`
- **Шаги:** checkout → Node 20 → `npm ci` → `npm run build` → rsync на VPS
- **Секреты:** `VPS_SSH_KEY`, `VPS_HOST`, `VPS_USER`
- **SSH-ключ:** `~/.ssh/github_actions_deploy` (на Mac), публичная часть — `authorized_keys` на VPS
- **Время:** ~40–120 секунд

## Docker Compose (прод)

```yaml
# /opt/my-app/docker-compose.prod.yml
services:
  api:
    build: .
    container_name: my-app-api
    restart: unless-stopped
    env_file: .env
    ports:
      - "127.0.0.1:8000:8000"
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"
```

## Workflow деплоя (NEW 2026-10-08)

**На Mac:** `git push`

**На VPS:** одна команда — `git pull origin main && docker compose build api && up -d`.

**При изменениях requirements.txt или Dockerfile** — обязательно флаг `--no-cache`.

### Правило: все VPS-проверки — через ssh с Mac

Плохо: заходишь интерактивно (ssh root@...), остаёшься в сессии, путаешь Mac/VPS.

Хорошо: одна команда — один результат, всегда с Mac:

    ssh root@91.142.73.226 "cd /opt/my-app && docker compose -f docker-compose.prod.yml exec -T api python3 -c \"...\""

Плюсы:
- Не застреваешь в root@pairs-bot:
- История команд на Mac — легко повторить
- Работает в &&-цепочках
- exec -T — без tty, чисто для скриптов

curl в контейнере нет — используем python3 -c для проверок.

## Переменные окружения (`.env`)

```env
DATABASE_URL=postgresql+asyncpg://...@ep-xxx.neon.tech/neondb?ssl=require
JWT_SECRET=<...>
ENCRYPTION_KEY=<fernet-key>
COOKIE_SECURE=true
COOKIE_DOMAIN=.agregators.su
TRIAL_PERIOD_DAYS=30
SUBSCRIPTION_PERIOD_DAYS=30
SUBSCRIPTION_PRICE_RUB=990
TELEGRAM_BOT_TOKEN=<token от @BotFather>
TELEGRAM_PROXY_URL=https://tg-proxy-agregators.shvaboe.workers.dev
```

---

# ЧАСТЬ 8: АРХИТЕКТУРА BACKEND

```
my-app/
├── app/
│   ├── main.py                    # точка входа, роутеры, CORS, lifespan
│   ├── config.py                  # Settings (pydantic)
│   ├── database.py                # engine, AsyncSessionLocal
│   ├── models.py                  # User, Marketplace, Product, Sale, TaxSettings...
│   ├── schemas.py                 # Pydantic-схемы
│   ├── security.py                # bcrypt, JWT
│   ├── crypto.py                  # Fernet (ENCRYPTION_KEY)
│   ├── deps.py                    # get_session, get_current_user, require_active_subscription
│   ├── trial.py                   # hash_identity, hash_email
│   ├── scheduler.py               # APScheduler + sync Ozon/WB
│   ├── sync_service.py            # NEW: sync-if-stale, пороги устаревания
│   ├── ozon_client.py             # httpx-клиент Ozon (FBS + FBO)
│   ├── wb_client.py               # httpx-клиент WB
│   ├── ozon_ads_client.py         # httpx-клиент Ozon Performance API
│   ├── telegram_notifier.py       # NEW: sendMessage через Cloudflare Worker proxy
│   ├── yookassa_client.py         # ЮKassa (отключён)
│   ├── routers/
│   │   ├── auth.py, users.py, products.py, sales.py
│   │   ├── marketplaces.py, delivery_services.py
│   │   ├── analytics.py           # 8 эндпоинтов + unit-economics/all
│   │   ├── integrations.py        # Ozon + WB + sync-if-stale
│   │   ├── ozon_ads.py            # Ozon Ads API (connect/sync/account)
│   │   ├── notifications.py       # NEW: Telegram connect/settings/test
│   │   ├── tax_settings.py
│   │   └── subscriptions.py       # ЮKassa (отключён)
│   └── services/
│       ├── unit_economics.py      # расчёт юнит-экономики
│       └── ozon_ads_sync.py       # sync Ozon Ads -> AdvertisingExpense
├── alembic/versions/              # миграции
├── tests/                         # 113 тестов
├── Dockerfile
├── docker-compose.yml             # dev
├── docker-compose.prod.yml        # prod (без db)
├── pyproject.toml                 # ruff + mypy
└── .pre-commit-config.yaml
```

## Cloudflare Worker — обход блокировки Telegram API (NEW 2026-10-08)

**Проблема:** Telegram API (api.telegram.org) заблокирован в РФ — недоступен с VPS.

**Решение:** Cloudflare Worker как edge-прокси.

**Worker:** tg-proxy-agregators.shvaboe.workers.dev
- Универсальный роут /bot<TOKEN>/* -> https://api.telegram.org/bot<TOKEN>/*
- Переиспользуется для всех Telegram-ботов

**В коде (1 строка):**

    base_url = settings.telegram_proxy_url or TELEGRAM_API_BASE

**В .env:**

    TELEGRAM_PROXY_URL=https://tg-proxy-agregators.shvaboe.workers.dev

**Плюсы:**
- Легко откатить (убрать TELEGRAM_PROXY_URL)
- Конфиг на уровне окружения, не в git
- Диагностика через getMe / getWebhookInfo / getUpdates

**Время решения:** ~1.5 часа (Worker + 2 патча + .env + smoke)

**Куда применить ещё:** любые внешние API, заблокированные в РФ.

## `sync_service.py` — авто-sync

**Пороги устаревания (в минутах):**
```python
STALE_THRESHOLDS = {
    "ozon": 15,                    # Ozon — каждые 15 минут
    "wildberries_product": 60,     # WB products — 1 час (лимит Базового токена)
    "wildberries_sales": 180,      # WB sales — 3 часа
}
```

**Эндпоинт `POST /integrations/sync-if-stale`:**
1. Проверяет `last_sync_at` для каждого аккаунта.
2. Для устаревших — запускает sync в фоне (`asyncio.create_task`).
3. Возвращает **сразу** — не блокирует UI.
4. In-memory lock — не запускает дубли.

**Frontend** вызывает этот эндпоинт через `useSyncOnMount()` хук:
- Загрузка данных мгновенно (из БД).
- Через 1 сек — триггер `sync-if-stale`.
- Если sync запущен — polling каждые 5 сек (60 сек максимум).

## `unit_economics.py`

**Формула:**
```
net_price = price − spp_amount
marketplace_costs = commission + logistics + return_logistics + acquiring + storage
payout = net_price − marketplace_costs
cogs = cost_price × quantity
gross_profit = payout − cogs
tax = calculate_tax(...)
net_profit = gross_profit − tax
margin_percent = net_profit / net_revenue × 100
roi_percent = net_profit / cogs × 100
```

## Клиенты маркетплейсов

### `OzonClient` (httpx)
- `get_seller_info()`, `list_products()`, `get_product_info()`
- `list_postings_for_range()` — **FBS**
- `list_fbo_postings_for_range()` — **FBO (NEW)**
- Заголовки: `Client-Id`, `Api-Key`
- Разбивка периода на 30-дневные чанки

**Sync продаж** вызывает **оба** метода (FBS + FBO) и объединяет.

### `WBClient` (httpx)
- `ping()`, `list_products()`, `list_sales_report(date_from, date_to)`
- Заголовок: `Authorization: <token>` (без `Bearer`!)
- Домены: `common-api`, `content-api`, `statistics-api` WB

---

# ЧАСТЬ 9: КОНКУРЕНТНЫЙ АНАЛИЗ

## MPProfit

**Что:** финансовая аналитика для WB/Ozon. Ядро — реальная прибыль с учётом комиссий, логистики, СПП, хранения, **рекламы**, налогов, себестоимости.

**Сильные стороны:**
- Рекламный блок (ДРР — внутренняя + внешняя реклама).
- Интеграция с 1С, бухгалтерией.
- Прогнозы, планирование закупок.
- API-доступ.
- Юнит-экономика + ABC.

**Цена:** 1500–5000 ₽/мес.

**Слабые стороны:**
- Дороже.
- Перегруженный интерфейс (общая проблема финансовых сервисов).

## MPStatus

**Что:** комбайн. Аналитика + операционка FBS + PIM + управление остатками + автоматизация цен + отзывы/вопросы + чат-боты.

**Сильные стороны:**
- **Единая лента заказов** (Ozon + WB).
- **Печать этикеток** пачкой.
- **PIM** — работа с карточками.
- **Управление поставками на FBO**.
- Автоматизация цен и акций.
- Отзывы/вопросы.
- Telegram-уведомления.

**Цена:** 2000–6000 ₽/мес.

**Слабые стороны:**
- Огромный функционал — сложно освоить.
- Требует времени на настройку.

## Наши позиции

**Сильные:**
1. **Фокус** — только реальная прибыль + юнит-экономика. Не комбайн.
2. **Цена** — 990 ₽/мес. Ниже MPProfit в 2–5 раз.
3. **Простой UI** — минимум кликов, автоматическая синхронизация.
4. **Доступ из РФ** без VPN.

**Слабые (пробелы):**
1. 🟡 **Нет рекламного блока** — главный пробел vs MPProfit.
2. 🟡 **Нет 1С** — может быть блокером для ЦА 500к+.
3. 🟡 **Нет Telegram-уведомлений**.
4. 🟢 **Нет FBS-операционки** — не пытаемся догнать MPStatus.
5. 🟢 **Нет PIM**.
6. 🟢 **Нет отзывов/вопросов**.

**Стратегия:** узкий фокус на «реальной прибыли» + агрессивная цена. **Не пытаемся догнать MPStatus** в операционке. Закрываем **пробелы vs MPProfit** (реклама, 1С).

---

# ЧАСТЬ 10: ROADMAP

## 🔴 Высокий приоритет (2–4 недели)

### 1. `/unit-economics` — есть ✅
Таблица прибыли по товарам с сортировкой и фильтром убыточных. **Уже в проде.**

### 1a. Ozon Ads API — ЗАКРЫТО (2026-10-08)
- Модель OzonAdsAccount + миграция
- OzonAdsClient (6 методов)
- Роутер /integrations/ozon-ads/* (4 эндпоинта)
- Сервис sync_ozon_ads — батчи + upsert
- Scheduler — раз в 6 часов
- UI — карточка на /integrations
- 15 тестов (7 endpoint + 8 client)

### 1b. Workflow git pull — ЗАКРЫТО (2026-10-08)
- VPS = git-репозиторий
- git pull вместо scp
- --no-cache при изменениях requirements

### 2. Редактирование себестоимости (D) 🟡
- Backend: `PATCH /products/{id}`, схема `ProductUpdate` (все поля optional).
- Frontend: модалка «Редактировать товар» на `/products`.
- **Зачем:** без себестоимости ROI = 0, часть аналитики не работает.

### 3. Рекламный блок (ДРР) 🔴
**Закрывает главный пробел vs MPProfit.**
- Model: `AdvertisingCost` (или поля `advertising_cost`, `advertising_type` в `Sale`).
- Формула: `net_profit_with_ads = net_profit − advertising_cost`.
- Метрика: **ДРР** = advertising_cost / revenue × 100.
- Эндпоинт: `GET /analytics/profit?include_ads=true`.
- Frontend: колонки «Прибыль с рекламой» и «ДРР» на `/unit-economics`.
- **Источник данных:** ручной ввод (быстро) → API Ozon Ads / WB Ads (сложно).
- **Оценка:** 1–2 дня.

### 4. Frontend-страницы аналитики
- `/profit` — дашборд по площадкам (эндпоинт готов).
- `/abc` — ABC-анализ + pie-chart (эндпоинт готов).
- **Оценка:** ~1 ч каждая.

### 5. 🎯 Рефакторинг интеграций в модули (стратегически важно)

**Проблема:** сейчас добавление новой площадки (Я.Маркет, AliExpress) требует правок в 5+ файлах:
- Новый `<code>_client.py`
- 3+ новых эндпоинта в `routers/integrations.py`
- Новый job в `scheduler.py`
- Новый порог в `sync_service.py`
- Карточка на `/integrations`
- **~4–6 часов работы**, файл `integrations.py` растёт линейно.

**Решение:** модульная структура `app/integrations/<code>/`:
app/integrations/
├── init.py # реестр
├── base.py # BaseMarketplaceClient
├── registry.py # @register("ozon")
├── ozon/
│ ├── client.py # OzonClient
│ ├── sync.py # sync_ozon_products, sync_ozon_sales
│ └── router.py # /integrations/ozon/*
├── wb/
│ ├── client.py
│ ├── sync.py
│ └── router.py
└── yandex/ # ← новая площадка = 1 папка
├── client.py
├── sync.py
└── router.py

text

**Плюсы:**
- Добавление новой площадки = **1 папка** + 1 запись в реестре.
- Роутер, sync, scheduler, пороги — **подключаются автоматически**.
- Оценка добавления новой площадки: **~2–3 часа** (вместо 4–6).
- Код чистый, тесты изолированы.

**Оценка рефакторинга:** ~6–7 часов.
**Когда делать:** после быстрых фич (`/profit`, `/abc`), до добавления 3-й площадки.

**Приоритет:** 🔴 высокий (архитектурный).

## 🟡 Средний приоритет (1–2 месяца)

### 5. WB Sales API fix
- WB закрыл `statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod`.
- Нужен новый эндпоинт (см. `dev.wildberries.ru/release-notes?id=498`).
- **Оценка:** 1–2 часа.

### 6. Экспорт в 1С
- `GET /export/1c?from=...&to=...` → Excel/CSV.
- Формат: `Дата | Номер заказа | SKU | Количество | Цена | Комиссия | Логистика | Налог | Прибыль`.
- Позже — API 1С через OData.
- **Оценка:** 1–2 дня.

### 7. Telegram-уведомления
- Бот + подписки в БД.
- Уведомления: «Новый заказ», «Товар стал убыточным», «Ежедневный отчёт».
- **Оценка:** 1–2 дня.

### 8. ЮKassa (монетизация)
- Раскомментировать `subscriptions.router` в `main.py`.
- Настроить webhook URL.
- Environment: `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`.
- **Оценка:** 2–4 часа.

### 9. Регистрация на WB API (Сервисный токен)
- Оформить юрлицо/ИП.
- Заявка на `business-solutions@rwb.ru`.
- Получить **Сервисный токен** (расширенные лимиты).
- **1–2 недели** (организационный процесс, параллельно).

### 10. Третий маркетплейс (Я.Маркет)
- По образцу Ozon: клиент, connect, 2 sync, scheduler, фронт-карточка.
- **Оценка:** 1 день (архитектура готова).

## 🟢 Низкий приоритет (потом)

### 11. PIM — управление карточками
- Создание/редактирование товаров в одном интерфейсе.
- «Разлив» карточки на Ozon + WB.
- ИИ-генерация описаний.
- **Оценка:** 3–5 дней.

### 12. Операционка FBS
- Единая лента заказов.
- Печать этикеток пачкой.
- Синхронизация остатков.
- Telegram-уведомления о новых заказах.
- **Оценка:** 5–7 дней.
- ⚠️ **Это уже конкуренция с MPStatus** — не приоритет без команды.

### 13. AliExpress
- По образцу Я.Маркета.

### 14. Email-подтверждение
- Resend (бесплатно 3000 писем/мес).
- Поля `email_verified`, `email_verification_token`.
- Страница `/verify`.

---

# ЧАСТЬ 11: ИЗВЕСТНЫЕ ПРОБЛЕМЫ И ДОЛГИ

## Backend

1. **WB Sales API deprecated** — sync продаж WB не работает (нужен Сервисный токен).
2. **WB Ads API** — аналогично (Сервисный токен).
3. **Docker Bake** — игнорирует changes requirements*. **--no-cache** обязателен.
2. **`ENCRYPTION_KEY` vs `FERNET_KEY`** — в коде используется `ENCRYPTION_KEY`, но в старой спеке упоминался `FERNET_KEY`. Если кто-то путает — будет ошибка Fernet.
3. **Docker `.pyc` кэш** — при `docker cp` код не перечитывается, нужен `restart`. Правильно — `docker compose build && up -d`.
4. **CORS захардкожен** в `main.py` (не читается из env).
5. **`docker-compose.prod.yml` не монтирует `/opt/my-app`** — правильно для прода, но правки кода требуют `--build`.

## Frontend

1. **`.env.production` закоммичен** — содержит `VITE_API_URL`. Не секрет, но некрасиво. Можно вынести в GitHub Actions env.
2. **Vite dev-сервер** — при `npm run dev` нужен `VITE_API_URL=http://localhost:8000` (в `.env.local`).

## Инфраструктура

1. **VPS — 1 vCPU, 1.9 ГБ RAM** — на пределе. Апгрейд до 2 vCPU / 4 ГБ, когда вырастет нагрузка.
2. **Neon — Frankfurt** — задержка ~30–50 мс. Можно перенести Postgres на VPS (когда нагрузка вырастет).

## Качество

1. **Backend CI не настроен** (только pre-push hook). Pre-commit работает локально.
2. **113 тестов** — покрытие неполное (нет тестов на sync_service, unit_economics/all).

---

# ЧАСТЬ 12: ПРАВИЛА РАЗРАБОТКИ

## При работе с кодом

1. **Decimal vs float** — деньги всегда `Decimal`, в тестах строки `"1000.00"`.
2. **`Decimal("0")` сериализуется в `"0.00"`** — в тестах сравнивать с `"0.00"`.
3. **YAML чувствителен к отступам** — не вставлять блоки целиком из чата.
4. **При вставке в конец файла** — сначала `Cmd + End` → `Enter Enter` → `Cmd + V`.
5. **Патчить классы в тестах** через полный путь: `app.routers.integrations.WBClient.ping`.
6. **venv обязательно активировать** перед `pre-commit`, `alembic`, `pytest`.

## При деплое

1. **Миграции — автоматически** при старте контейнера (`alembic upgrade head` в `CMD`).
2. **FastAPI Cloud больше не используется** — всё на VPS.
3. **Docker-кэш** — при правке роутеров делать `--build` (или `--no-cache` для гарантии).
4. **CORS на проде** — `main.py` захардкожен, при смене домена править вручную.

## При работе с маркетплейсами

1. **WB Базовый токен жёсткие лимиты:** products 1/час, sales 1/3 часа.
2. **WB API меняется** — следить за `dev.wildberries.ru/release-notes`.
3. **Ozon имеет FBS и FBO** — sync продаж должен вызывать оба метода.
4. **WB заголовок без `Bearer`** — просто `Authorization: <token>`.
5. **URL `/wb/*`, а marketplace code `wildberries`** — осознанное решение.
6. **🎯 При добавлении новой площадки** — см. пункт «Рефакторинг интеграций» в ROADMAP. Сначала рефакторинг, потом добавление.

## При деплое на VPS (NEW 2026-10-08)

1. Workflow: git push на Mac, git pull на VPS.
2. Изменения requirements*.txt — обязательно --no-cache.
3. .env и docker-compose.prod.yml — не в git.
4. Миграции Alembic — автоматически при старте контейнера.
5. Логи: docker compose logs api --tail=30.

## При работе с фронтом

1. **GitHub Actions автодеплой** — `git push` → прод через 1–2 минуты.
2. **`npx tsc --noEmit`** — проверка типов без сборки.
3. **`npm run build`** — продакшн-сборка.
4. **Hard-refresh после деплоя** — `Cmd+Shift+R` для обновления кэша.

## При работе с VPS

1. **Файлы в `/opt/my-app/`** — источник правды, но требуют `--build` для контейнера.
2. **`docker cp`** — временно, слетит при рестарте.
3. **`SPEC.md`** — этот файл, обновлять при крупных изменениях.

---

# ЧАСТЬ 13: ПОЛЕЗНЫЕ КОМАНДЫ

## Локальная разработка (Mac)
```bash
cd ~/projects/my-app
source .venv/bin/activate
docker compose up -d
docker compose exec api pytest -v
docker compose exec api pre-commit run --all-files
```

## Frontend (Mac)
```bash
cd ~/projects/my-app-frontend
npm run dev              # dev-сервер
npx tsc --noEmit         # проверка типов
npm run build            # прод-сборка
git push                 # автодеплой
```

## VPS — backend
```bash
ssh root@91.142.73.226
cd /opt/my-app

# Перезапуск
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d

# Пересборка при правках кода
docker compose -f docker-compose.prod.yml build api
docker compose -f docker-compose.prod.yml up -d

# Логи
docker compose -f docker-compose.prod.yml logs --tail=50 api

# Миграции
docker compose -f docker-compose.prod.yml exec -T api alembic upgrade head
docker compose -f docker-compose.prod.yml exec -T api alembic revision --autogenerate -m "..."
```

## VPS — Caddy
```bash
nano /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
systemctl status caddy
journalctl -u caddy --no-pager | tail -30
```

## VPS — frontend
```bash
ls -la /var/www/agregators/
ls -la /var/www/agregators/assets/
# При ручном обновлении: scp -r dist/* root@91.142.73.226:/var/www/agregators/
```

## Полезные запросы
```bash
# Проверка backend
curl https://api.agregators.su/health

# Логин
TOKEN=$(curl -s -X POST https://api.agregators.su/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"trial-1789389840@example.com","password":"secret123","name":"ignored"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Sync-if-stale
curl -X POST https://api.agregators.su/integrations/sync-if-stale \
  -H "Authorization: Bearer $TOKEN"

# Юнит-экономика
curl -s "https://api.agregators.su/analytics/unit-economics/all?from=2026-09-06T00:00:00Z&to=2026-10-06T23:59:59Z" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

# ФИНАЛЬНАЯ ЗАМЕТКА

**Проект в сильной точке:** backend production-ready, frontend с ключевыми фичами, авто-sync, автодеплой, доступ из РФ без VPN.

**Ключевое конкурентное преимущество:** реальная прибыль с учётом СПП и налогов.

**Главный пробел vs MPProfit:** реклама (ДРР). **Следующий шаг** — закрыть его.

**Стратегия:** узкий фокус + агрессивная цена (990 ₽) + простой UI. Не пытаемся догнать MPStatus в операционке.
).
