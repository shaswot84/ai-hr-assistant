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
    assert "api_key" in body  # shown as-is now, not masked behind a boolean


def test_put_llm_config_overrides_and_shows_the_real_key(client, manager_context, manager_password):
    """Regression case for the redesign: the settings form now shows the
    manager's own key back to them (an HR_ADMIN-only internal page), rather
    than the old write-only/masked design.
    """
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
    assert body["api_key"] == "sk-secret-123"
    assert body["is_default"] is False

    # fetching again returns the same real value, not a masked placeholder
    res2 = client.get("/api/settings/llm-config", headers=headers)
    assert res2.json()["api_key"] == "sk-secret-123"


def test_put_llm_config_empty_key_clears_it(client, manager_context, manager_password):
    """The form is no longer write-only, so submitting a blank key now means
    'no key configured' — there's no more 'blank leaves it unchanged' magic.
    """
    token = _login(client, manager_context.email, manager_password)
    headers = {"Authorization": f"Bearer {token}"}

    client.put(
        "/api/settings/llm-config",
        headers=headers,
        json={"api_base": "https://custom-llm.example.com", "model": "custom-model", "api_key": "sk-secret-123"},
    )
    res = client.put(
        "/api/settings/llm-config",
        headers=headers,
        json={"api_base": "https://custom-llm.example.com", "model": "updated-model", "api_key": ""},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["model"] == "updated-model"
    assert body["api_key"] == ""


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


def test_resume_review_prompt_round_trips_through_env_file(client, manager_context, manager_password):
    token = _login(client, manager_context.email, manager_password)
    headers = {"Authorization": f"Bearer {token}"}

    get_res = client.get("/api/settings/resume-review-prompt", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["is_default"] is True

    custom = "Line one.\nLine two with a \"quote\" in it."
    put_res = client.put(
        "/api/settings/resume-review-prompt", headers=headers, json={"prompt": custom}
    )
    assert put_res.status_code == 200
    assert put_res.json()["prompt"] == custom
    assert put_res.json()["is_default"] is False

    get_res2 = client.get("/api/settings/resume-review-prompt", headers=headers)
    assert get_res2.json()["prompt"] == custom

    reset_res = client.post("/api/settings/resume-review-prompt/reset", headers=headers)
    assert reset_res.status_code == 200
    assert reset_res.json()["is_default"] is True


def test_keyword_suggestion_prompt_round_trips_through_env_file(client, manager_context, manager_password):
    token = _login(client, manager_context.email, manager_password)
    headers = {"Authorization": f"Bearer {token}"}

    get_res = client.get("/api/settings/keyword-suggestion-prompt", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["is_default"] is True

    custom = "Weight leadership keywords heavily for any title containing 'Manager' or 'Lead'."
    put_res = client.put(
        "/api/settings/keyword-suggestion-prompt", headers=headers, json={"prompt": custom}
    )
    assert put_res.status_code == 200
    assert put_res.json()["prompt"] == custom
    assert put_res.json()["is_default"] is False

    get_res2 = client.get("/api/settings/keyword-suggestion-prompt", headers=headers)
    assert get_res2.json()["prompt"] == custom

    reset_res = client.post("/api/settings/keyword-suggestion-prompt/reset", headers=headers)
    assert reset_res.status_code == 200
    assert reset_res.json()["is_default"] is True


def test_keyword_suggestion_prompt_requires_hr_admin(client, candidate_context, candidate_password):
    token = _login(client, candidate_context.email, candidate_password)
    res = client.get(
        "/api/settings/keyword-suggestion-prompt", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403
