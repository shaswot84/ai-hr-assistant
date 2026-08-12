from __future__ import annotations

from app.model_gateway.ollama import OllamaChatProvider


class _FakeChatSettings:
    api_base = "https://default.example.com"
    model = "default-model"
    api_key = "default-real-key"
    request_timeout = 60.0


class _FakeAppSettings:
    chat = _FakeChatSettings()


def _patch_settings(monkeypatch):
    monkeypatch.setattr("app.model_gateway.ollama.get_settings", lambda: _FakeAppSettings())


def test_explicit_blank_api_key_override_is_honored_not_defaulted(monkeypatch):
    """Regression: a manager clearing the API key in Settings writes an empty
    string to .env, not an absent line — `resolved_llm_overrides()` then
    returns "" (not None) for api_key. The provider must treat that blank as
    a real, explicit override rather than silently falling back to the
    cached container-boot default: `api_key or self._settings.chat.api_key`
    couldn't tell "no override" (None) apart from "explicitly blank" ("")
    since both are falsy, so a cleared key kept using the old cached key.
    """
    _patch_settings(monkeypatch)
    provider = OllamaChatProvider(api_key="")
    assert provider._api_key == ""
    assert provider.is_configured() is False


def test_no_override_falls_back_to_settings_default(monkeypatch):
    _patch_settings(monkeypatch)
    provider = OllamaChatProvider()
    assert provider._api_key == "default-real-key"
    assert provider.is_configured() is True


def test_explicit_override_key_is_used_over_default(monkeypatch):
    _patch_settings(monkeypatch)
    provider = OllamaChatProvider(api_key="sk-override")
    assert provider._api_key == "sk-override"


def test_blank_api_base_and_model_overrides_are_also_honored(monkeypatch):
    """Same None-vs-blank distinction applies to api_base/model, not just api_key."""
    _patch_settings(monkeypatch)
    provider = OllamaChatProvider(api_base="", model="")
    assert provider._base == ""
    assert provider._model == ""
