"""
Tests for P0.4 — Event Schema
"""
import json
import pytest
from ma_set.events.schema import Event, EventType, new_run_id


def test_new_run_id_is_unique():
    assert new_run_id() != new_run_id()


def test_event_make_sets_timestamp():
    ev = Event.make(
        run_id="r1",
        node="A1",
        agent="planner",
        event_type=EventType.AGENT_STARTED,
    )
    assert ev.timestamp  # non-empty
    assert ev.node == "A1"
    assert ev.event_type == EventType.AGENT_STARTED.value


def test_event_to_jsonl_is_valid_json():
    ev = Event.make(
        run_id="r1",
        node="A2",
        agent="architect",
        event_type=EventType.DESIGN_SPEC,
        payload={"files": ["app.py"]},
    )
    line = ev.to_jsonl()
    assert line.endswith("\n")
    parsed = json.loads(line)
    assert parsed["node"] == "A2"
    assert parsed["payload"]["files"] == ["app.py"]


def test_invalid_node_raises():
    with pytest.raises(Exception):
        Event(
            run_id="r1",
            timestamp="2026-10-08T00:00:00Z",
            node="X9",          # invalid
            agent="test",
            event_type=EventType.AGENT_STARTED,
        )
