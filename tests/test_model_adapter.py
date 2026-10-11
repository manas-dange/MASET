"""
Tests for P0.5 — Model Adapter (stub mode only — no API keys needed)
"""
from ma_set.model.adapter import ModelAdapter, ModelConfig, Provider


def test_stub_adapter_returns_string():
    adapter = ModelAdapter(ModelConfig(provider=Provider.STUB))
    result = adapter.complete("Plan the ticket", run_id="t1", node="A1", agent="planner")
    assert isinstance(result, str)
    assert len(result) > 0


def test_stub_adapter_picks_different_responses():
    adapter = ModelAdapter(ModelConfig(provider=Provider.STUB))
    plan = adapter.complete("Plan the ticket breakdown", run_id="t1", node="A1", agent="planner")
    design = adapter.complete("Design the spec", run_id="t1", node="A2", agent="architect")
    diff = adapter.complete("Implement the diff", run_id="t1", node="A3", agent="developer")
    assert plan != design
    assert design != diff


def test_stub_adapter_increments_call_count():
    adapter = ModelAdapter(ModelConfig(provider=Provider.STUB))
    for _ in range(3):
        adapter.complete("hello", run_id="t1", node="A1", agent="test")
    assert adapter.stats["call_count"] == 3


def test_stub_adapter_fires_event_callback():
    events = []
    adapter = ModelAdapter(
        ModelConfig(provider=Provider.STUB),
        event_callback=events.append,
    )
    adapter.complete("Plan something", run_id="t1", node="A1", agent="planner")
    assert len(events) == 1
    assert events[0]["event_type"] == "llm_stub_response"


def test_from_env_defaults_to_stub(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = ModelConfig.from_env()
    assert cfg.provider == Provider.STUB
