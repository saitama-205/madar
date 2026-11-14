import json

import pytest

from ai import llm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setattr(llm, "ENV_FILE", llm.ENV_FILE.with_name("does-not-exist.env"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)


def test_get_shows_the_active_model_and_the_whitelist(api):
    body = api.get("/api/settings/ai").json()
    assert body["model"] == "openai/gpt-4o-mini" == body["default"]
    assert [m["id"] for m in body["models"]] == ["openai/gpt-4o-mini", "google/gemini-2.0-flash-001", "anthropic/claude-3.5-haiku"]
    assert all(m["label"] for m in body["models"]) and body["ai_configured"] is False
    assert set(body) == {"model", "default", "models", "ai_configured"}     # no key anywhere


def test_default_comes_from_openrouter_model(api, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")
    assert api.get("/api/settings/ai").json()["model"] == "google/gemini-2.0-flash-001"


def test_put_switches_the_model_used_by_the_ai_calls(api, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")
    sent = {}
    monkeypatch.setattr(llm, "_send", lambda payload, headers: (sent.update(p=payload), (200, json.dumps({"choices": [{"message": {"content": "hi"}}]})))[1])
    r = api.put("/api/settings/ai", json={"model": "google/gemini-2.0-flash-001"})
    assert r.status_code == 200 and r.json()["model"] == "google/gemini-2.0-flash-001"
    assert "secret-key" not in r.text
    llm.chat([{"role": "user", "content": "x"}])
    assert sent["p"]["model"] == "google/gemini-2.0-flash-001"
    assert api.get("/api/settings/ai").json()["model"] == "google/gemini-2.0-flash-001"      # remembered in memory
    api.put("/api/settings/ai", json={"model": "openai/gpt-4o-mini"})
    llm.chat([{"role": "user", "content": "x"}])
    assert sent["p"]["model"] == "openai/gpt-4o-mini"


@pytest.mark.parametrize("bad", ["gpt-5", "", "openai/gpt-4o", "OPENAI/GPT-4O-MINI", " openai/gpt-4o-mini", "../x"])
def test_only_whitelisted_models_are_accepted(api, bad):
    r = api.put("/api/settings/ai", json={"model": bad})
    assert r.status_code == 400 and r.json()["error"] == "invalid_model" and r.json()["message"]
    assert api.get("/api/settings/ai").json()["model"] == "openai/gpt-4o-mini"


def test_bad_bodies_are_rejected_and_there_is_no_key_field(api):
    assert api.put("/api/settings/ai", json={}).status_code == 422
    assert api.put("/api/settings/ai", json={"model": 5}).status_code == 422
    r = api.put("/api/settings/ai", json={"model": "openai/gpt-4o-mini", "api_key": "k"})     # extra fields are ignored
    assert r.status_code == 200 and "api_key" not in r.text
