"""Тесты эндпоинтов /tax-settings."""


async def _register_and_login(client, email: str = "tax@example.com") -> str:
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
# GET /tax-settings
# ============================================================


async def test_get_tax_settings_empty(client):
    """У нового пользователя нет налоговых настроек — вернётся null."""
    token = await _register_and_login(client)
    response = await client.get(
        "/tax-settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() is None


async def test_get_tax_settings_requires_auth(client):
    """Без токена — 401."""
    response = await client.get("/tax-settings")
    assert response.status_code == 401


# ============================================================
# PUT /tax-settings
# ============================================================


async def test_create_tax_settings(client):
    """Создание налоговых настроек с нуля (upsert)."""
    token = await _register_and_login(client)

    response = await client.put(
        "/tax-settings",
        json={
            "tax_system": "USN_INCOME",
            "tax_rate": "6.00",
            "insurance_contributions": "57390.00",
            "vat_enabled": False,
            "vat_rate": "0.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tax_system"] == "USN_INCOME"
    assert data["tax_rate"] == "6.00"
    assert data["insurance_contributions"] == "57390.00"
    assert data["vat_enabled"] is False
    assert data["id"] is not None
    assert data["created_at"] is not None


async def test_update_tax_settings(client):
    """Повторный PUT обновляет существующую запись, а не создаёт дубль."""
    token = await _register_and_login(client)

    # Первый PUT — создание
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

    # Второй PUT — обновление
    response = await client.put(
        "/tax-settings",
        json={
            "tax_system": "USN_INCOME_EXPENSE",
            "tax_rate": "15.00",
            "insurance_contributions": "57390.00",
            "vat_enabled": True,
            "vat_rate": "20.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tax_system"] == "USN_INCOME_EXPENSE"
    assert data["tax_rate"] == "15.00"
    assert data["vat_enabled"] is True
    assert data["vat_rate"] == "20.00"

    # GET — убедиться, что запись одна и с новыми данными
    get_response = await client.get(
        "/tax-settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_response.status_code == 200
    assert get_response.json()["tax_system"] == "USN_INCOME_EXPENSE"


async def test_tax_settings_invalid_system(client):
    """Неизвестная система налогообложения → 422."""
    token = await _register_and_login(client)

    response = await client.put(
        "/tax-settings",
        json={
            "tax_system": "WRONG_SYSTEM",
            "tax_rate": "6.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert "tax_system" in response.json()["detail"]


async def test_tax_settings_negative_rate(client):
    """Отрицательная ставка → 422."""
    token = await _register_and_login(client)

    response = await client.put(
        "/tax-settings",
        json={
            "tax_system": "USN_INCOME",
            "tax_rate": "-5.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert "tax_rate" in response.json()["detail"]


async def test_tax_settings_isolated_per_user(client):
    """У разных пользователей — разные настройки."""
    token_a = await _register_and_login(client, email="a@example.com")
    token_b = await _register_and_login(client, email="b@example.com")

    # Пользователь A создаёт настройки
    await client.put(
        "/tax-settings",
        json={"tax_system": "NPD", "tax_rate": "4.00"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # Пользователь B — пусто
    response_b = await client.get(
        "/tax-settings",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response_b.status_code == 200
    assert response_b.json() is None

    # Пользователь A — видит свои
    response_a = await client.get(
        "/tax-settings",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response_a.json()["tax_system"] == "NPD"


# ============================================================
# DELETE /tax-settings
# ============================================================


async def test_delete_tax_settings(client):
    """DELETE удаляет настройки, после — GET возвращает null."""
    token = await _register_and_login(client)

    await client.put(
        "/tax-settings",
        json={"tax_system": "USN_INCOME", "tax_rate": "6.00"},
        headers={"Authorization": f"Bearer {token}"},
    )

    delete_response = await client.delete(
        "/tax-settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 204

    get_response = await client.get(
        "/tax-settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_response.status_code == 200
    assert get_response.json() is None


async def test_delete_tax_settings_idempotent(client):
    """DELETE без существующих настроек — не падает, 204."""
    token = await _register_and_login(client)

    response = await client.delete(
        "/tax-settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204
