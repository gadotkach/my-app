async def test_first_registration_gets_trial(client):
    response = await client.post(
        "/auth/register",
        json={"email": "trial1@example.com", "name": "Trial", "password": "secret123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["subscription_status"] == "trialing"
    assert data["trial_ends_at"] is not None


async def test_second_registration_same_identity_no_trial(client):
    first = await client.post(
        "/auth/register",
        json={"email": "user1@example.com", "name": "U1", "password": "secret123"},
    )
    assert first.status_code == 201
    assert first.json()["subscription_status"] == "trialing"

    second = await client.post(
        "/auth/register",
        json={"email": "user2@example.com", "name": "U2", "password": "secret123"},
    )
    assert second.status_code == 201
    assert second.json()["subscription_status"] == "none"
    assert second.json()["trial_ends_at"] is None
