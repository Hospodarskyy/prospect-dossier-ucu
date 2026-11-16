"""Offline tests for model settings: thinking level, retries, models."""
import pytest
from google.adk.models.google_llm import Gemini

from dossier_agent import agent
from dossier_agent.agent import model_config, retry_options, thinking_config


def test_judge_thinking_is_low_by_default():
    assert agent.judge.generate_content_config.thinking_config.thinking_level.value == "LOW"


def test_researcher_does_not_get_history():
    assert agent.researcher.include_contents == "none"
    assert agent.judge.include_contents == "none" and agent.writer.include_contents == "none"


def test_no_vertex_only_settings():
    # labels are a Vertex AI billing feature; the agent runs on a Gemini API key too
    for a in (agent.researcher, agent.judge, agent.writer):
        assert not a.generate_content_config.labels


def test_thinking_config_from_env(monkeypatch):
    monkeypatch.delenv("X_LEVEL", raising=False)
    assert thinking_config("X_LEVEL") is None                       # unset, no default
    assert thinking_config("X_LEVEL", default="low").thinking_level.value == "LOW"
    monkeypatch.setenv("X_LEVEL", "")
    assert thinking_config("X_LEVEL", default="low") is None        # set empty: model default
    monkeypatch.setenv("X_LEVEL", " High ")
    assert thinking_config("X_LEVEL").thinking_level.value == "HIGH"
    monkeypatch.setenv("X_LEVEL", "turbo")
    with pytest.raises(ValueError):
        thinking_config("X_LEVEL")


def test_model_config_without_thinking_env():
    assert model_config().thinking_config is None


def test_every_llm_agent_retries_model_requests():
    for a in (agent.researcher, agent.judge, agent.writer):
        assert isinstance(a.model, Gemini)
        assert a.model.retry_options.attempts >= 2


def test_retry_options_from_env(monkeypatch):
    monkeypatch.delenv("MODEL_ATTEMPTS", raising=False)
    assert retry_options().attempts == 4
    monkeypatch.setenv("MODEL_ATTEMPTS", "1")                      # no retries
    assert retry_options().attempts == 1
    monkeypatch.setenv("MODEL_ATTEMPTS", "0")
    with pytest.raises(ValueError):
        retry_options()


def test_writer_model_defaults_to_model():
    assert agent.writer.model.model == agent.WRITER_MODEL
    assert agent.researcher.model.model == agent.judge.model.model == agent.MODEL
