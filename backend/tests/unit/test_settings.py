from __future__ import annotations


def _login(client, email, password) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def test_get_llm_config_defaults_to_env_settings(client, manager_context, manager_password):
    token = _login(client, manager_context.email, manager_password)
    res = client.get("/api/settings/llm-config", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert body["is_default"] is True
    assert "api_key" not in body  # never sent to the client, only whether one is set


def test_put_llm_config_overrides_and_masks_key(client, manager_context, manager_password):
    token = _login(client, manager_context.email, manager_password)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.put(
        "/api/settings/llm-config",
        headers=headers,
        json={"api_base": "https://custom-llm.example.com", "model": "custom-model", "api_key": "sk-secret-123"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["api_base"] == "https://custom-llm.example.com"
    assert body["model"] == "custom-model"
    assert body["api_key_set"] is True
    assert body["is_default"] is False
    assert "sk-secret-123" not in res.text  # the raw key must never round-trip to the client

    # a blank api_key on a later save must not clear the previously stored key
    res2 = client.put(
        "/api/settings/llm-config",
        headers=headers,
        json={"api_base": "https://custom-llm.example.com", "model": "updated-model", "api_key": ""},
    )
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["model"] == "updated-model"
    assert body2["api_key_set"] is True


def test_reset_llm_config_clears_overrides(client, manager_context, manager_password):
    token = _login(client, manager_context.email, manager_password)
    headers = {"Authorization": f"Bearer {token}"}

    client.put(
        "/api/settings/llm-config",
        headers=headers,
        json={"api_base": "https://custom-llm.example.com", "model": "custom-model", "api_key": "sk-secret-123"},
    )
    res = client.post("/api/settings/llm-config/reset", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["is_default"] is True


def test_llm_config_requires_hr_admin(client, candidate_context, candidate_password):
    token = _login(client, candidate_context.email, candidate_password)
    res = client.get("/api/settings/llm-config", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
