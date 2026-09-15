"""Тесты эндпоинта /analytics/calculator."""


async def _register_and_login(client, email: str = "calc@example.com") -> str:
    await client.post(
        "/auth/register",
        json={"email": email, "name": "Seller", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": email, "name": "x", "password": "secret123"},
    )
    return login.json()["access_token"]


# ============================================================
# Доступ
# ============================================================


async def test_calculator_requires_auth(client):
    """Без токена → 401."""
    response = await client.post(
        "/analytics/calculator",
        json={"cost_price": "500.00", "target_price": "1000.00"},
    )
    assert response.status_code == 401


# ============================================================
# Минимальный расчёт
# ============================================================


async def test_calculator_minimal(client):
    """Только цена и себестоимость, налог 0."""
    token = await _register_and_login(client)
    response = await client.post(
        "/analytics/calculator",
        json={
            "cost_price": "500.00",
            "target_price": "1000.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # Никаких комиссий → payout = 1000
    assert data["gross_price"] == "1000.00"
    assert data["spp_amount"] == "0.00"
    assert data["net_price"] == "1000.00"
    assert data["marketplace_costs_total"] == "0.00"
    assert data["payout"] == "1000.00"
    assert data["cogs"] == "500.00"
    assert data["gross_profit"] == "500.00"
    assert data["tax_amount"] in ("0", "0.00")
    assert data["net_profit"] == "500.00"
    assert data["margin_percent"] == "50.00"
    assert data["roi_percent"] == "100.00"
    assert data["profit_per_unit"] == "500.00"
    assert data["warning"] is None


# ============================================================
# С комиссией и логистикой
# ============================================================


async def test_calculator_with_commission_and_logistics(client):
    """Комиссия 22% + логистика 91 ₽ + эквайринг 1.5%."""
    token = await _register_and_login(client)
    response = await client.post(
        "/analytics/calculator",
        json={
            "cost_price": "500.00",
            "target_price": "1500.00",
            "commission_percent": "22.00",
            "logistics_cost": "91.00",
            "acquiring_percent": "1.50",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # net = 1500 (без СПП)
    # commission = 1500 × 22% = 330
    # acquiring = 1500 × 1.5% = 22.50
    # costs = 330 + 91 + 22.50 = 443.50
    # payout = 1500 − 443.50 = 1056.50
    # gross_profit = 1056.50 − 500 = 556.50
    assert data["commission"] == "330.00"
    assert data["acquiring"] == "22.50"
    assert data["marketplace_costs_total"] == "443.50"
    assert data["payout"] == "1056.50"
    assert data["gross_profit"] == "556.50"


# ============================================================
# Со СПП
# ============================================================


async def test_calculator_with_spp(client):
    """СПП 5% снижает net_price."""
    token = await _register_and_login(client)
    response = await client.post(
        "/analytics/calculator",
        json={
            "cost_price": "500.00",
            "target_price": "1000.00",
            "spp_percent": "5.00",
            "commission_percent": "20.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # spp = 1000 × 5% = 50
    # net = 950
    # commission = 950 × 20% = 190
    assert data["spp_amount"] == "50.00"
    assert data["net_price"] == "950.00"
    assert data["commission"] == "190.00"


# ============================================================
# Налоги — явно в запросе
# ============================================================


async def test_calculator_with_tax_in_request(client):
    """tax_system задан в запросе — берётся он, а не БД."""
    token = await _register_and_login(client)
    response = await client.post(
        "/analytics/calculator",
        json={
            "cost_price": "500.00",
            "target_price": "1000.00",
            "tax_system": "USN_INCOME",
            "tax_rate": "6.00",
            "insurance_contributions": "0.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # tax = 1000 × 6% = 60
    # net_profit = 500 − 60 = 440
    assert data["tax_amount"] == "60.00"
    assert data["net_profit"] == "440.00"


# ============================================================
# Налоги — из настроек пользователя
# ============================================================


async def test_calculator_uses_user_tax_settings(client):
    """tax_system=None → налог берётся из TaxSettings пользователя."""
    token = await _register_and_login(client)

    # Создаём налоговые настройки
    await client.put(
        "/tax-settings",
        json={
            "tax_system": "USN_INCOME",
            "tax_rate": "6.00",
            "insurance_contributions": "0.00",
            "vat_enabled": False,
            "vat_rate": "0.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    # Калькулятор без явного tax_system
    response = await client.post(
        "/analytics/calculator",
        json={
            "cost_price": "500.00",
            "target_price": "1000.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # tax = 1000 × 6% = 60 (из настроек пользователя)
    assert data["tax_amount"] == "60.00"
    assert data["net_profit"] == "440.00"


# ============================================================
# Убыток → warning + рекомендованная цена
# ============================================================


async def test_calculator_loss_warning(client):
    """Убыточный расчёт → warning с рекомендованной ценой."""
    token = await _register_and_login(client)
    response = await client.post(
        "/analytics/calculator",
        json={
            "cost_price": "1500.00",
            "target_price": "1000.00",
            "commission_percent": "22.00",
            "logistics_cost": "91.00",
            "acquiring_percent": "1.50",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["net_profit"].startswith("-")
    assert data["warning"] is not None
    assert "Рекомендуемая цена" in data["warning"]


# ============================================================
# Количество
# ============================================================


async def test_calculator_quantity_multiplies_cogs(client):
    """quantity=5 → cogs × 5, revenue × 5."""
    token = await _register_and_login(client)
    response = await client.post(
        "/analytics/calculator",
        json={
            "cost_price": "200.00",
            "target_price": "500.00",
            "quantity": 5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # cogs = 200 × 5 = 1000
    # payout = 500 (за единицу, из UnitEconomics)
    # gross_profit = 500 − 1000 = −500
    assert data["cogs"] == "1000.00"
    assert data["gross_profit"] == "-500.00"
    assert data["net_profit"] == "-500.00"


# ============================================================
# Валидация
# ============================================================


async def test_calculator_missing_required_fields(client):
    """Без cost_price или target_price → 422."""
    token = await _register_and_login(client)
    response = await client.post(
        "/analytics/calculator",
        json={"cost_price": "500.00"},  # нет target_price
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
