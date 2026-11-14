import json

import pytest

from ai import llm
from ai.privacy import short_name


@pytest.fixture(autouse=True)
def no_waiting_no_env(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm, "ENV_FILE", llm.ENV_FILE.with_name("does-not-exist.env"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)


def reply(text):
    return 200, json.dumps({"choices": [{"message": {"content": text}}]})


def test_no_key_raises_unavailable_without_network(monkeypatch):
    monkeypatch.setattr(llm, "_send", lambda *a: pytest.fail("must not call the network"))
    assert not llm.is_configured()
    with pytest.raises(llm.LLMUnavailable):
        llm.chat([{"role": "user", "content": "hi"}])


def test_key_and_model_from_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    monkeypatch.setattr(llm, "_send", lambda payload, headers: (seen.update(p=payload, h=headers), reply(" hello "))[1])
    assert llm.chat([{"role": "user", "content": "hi"}]) == "hello"
    assert seen["p"]["model"] == "openai/gpt-4o-mini" and seen["h"]["Authorization"] == "Bearer k"
    monkeypatch.setenv("OPENROUTER_MODEL", "other/model")
    llm.chat([{"role": "user", "content": "hi"}])
    assert seen["p"]["model"] == "other/model"


def test_retries_on_429_then_works(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    answers = iter([(429, ""), (429, ""), reply("ok")])
    monkeypatch.setattr(llm, "_send", lambda *a: next(answers))
    assert llm.chat([]) == "ok"


def test_gives_up_after_429s(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm, "_send", lambda *a: (429, ""))
    with pytest.raises(llm.LLMError, match="rate limiting"):
        llm.chat([])


@pytest.mark.parametrize("answer", [(500, "boom"), (200, "not json"), (200, '{"choices": []}'), reply("   ")])
def test_bad_answers_are_llm_errors(monkeypatch, answer):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm, "_send", lambda *a: answer)
    with pytest.raises(llm.LLMError):
        llm.chat([])


def test_extract_json_handles_fences():
    assert llm.extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(llm.LLMError):
        llm.extract_json("no json here")


def test_short_name():
    assert short_name("Sara Khaled Al-Ali") == "Sara A."
    assert short_name("فاطمة المليفي") == "فاطمة م."
    assert short_name("فاطمة م.") == "فاطمة م."
    assert short_name("فاطمة المليفي (2)") == "فاطمة م. (2)"
    assert short_name("شاهندا") == "شاهندا"
