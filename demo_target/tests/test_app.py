"""
P0.3 — Baseline Tests for the Demo Target
==========================================
Records the baseline state of the demo target *before* any agent touches it.
Agents must not regress any test that passes here.

Run with:
    pytest demo_target/tests/ -v
"""

import pytest
from demo_target.app import app, _reset


@pytest.fixture(autouse=True)
def clean_state():
    """Reset in-memory store before every test."""
    _reset()
    yield
    _reset()


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Signup — KNOWN FAILURES (intentional bugs to be fixed by agents)
# ---------------------------------------------------------------------------

class TestSignup:
    def test_signup_valid(self, client):
        resp = client.post("/signup", json={"email": "a@b.com", "password": "pass"})
        assert resp.status_code == 201
        assert resp.get_json()["email"] == "a@b.com"

    def test_signup_duplicate_returns_409(self, client):
        client.post("/signup", json={"email": "a@b.com", "password": "pass"})
        resp = client.post("/signup", json={"email": "a@b.com", "password": "pass"})
        assert resp.status_code == 409

    @pytest.mark.xfail(reason="KNOWN BUG: missing validation — to be fixed by Developer agent")
    def test_signup_missing_email_returns_400(self, client):
        resp = client.post("/signup", json={"password": "pass"})
        assert resp.status_code == 400

    @pytest.mark.xfail(reason="KNOWN BUG: missing validation — to be fixed by Developer agent")
    def test_signup_missing_password_returns_400(self, client):
        resp = client.post("/signup", json={"email": "a@b.com"})
        assert resp.status_code == 400

    @pytest.mark.xfail(reason="KNOWN BUG: missing validation — to be fixed by Developer agent")
    def test_signup_empty_body_returns_400(self, client):
        resp = client.post("/signup", json={})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TestTasks:
    def test_list_tasks_empty(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_create_task(self, client):
        resp = client.post("/tasks", json={"title": "Write tests"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Write tests"
        assert data["done"] is False
        assert "id" in data

    def test_create_task_missing_title_returns_400(self, client):
        resp = client.post("/tasks", json={})
        assert resp.status_code == 400

    def test_update_task(self, client):
        create = client.post("/tasks", json={"title": "Do something"})
        task_id = create.get_json()["id"]
        resp = client.patch(f"/tasks/{task_id}", json={"done": True})
        assert resp.status_code == 200
        assert resp.get_json()["done"] is True

    def test_update_task_not_found(self, client):
        resp = client.patch("/tasks/9999", json={"done": True})
        assert resp.status_code == 404

    def test_delete_task(self, client):
        create = client.post("/tasks", json={"title": "Delete me"})
        task_id = create.get_json()["id"]
        resp = client.delete(f"/tasks/{task_id}")
        assert resp.status_code == 200
        # Confirm it's gone
        assert client.get("/tasks").get_json() == []

    def test_delete_task_not_found(self, client):
        resp = client.delete("/tasks/9999")
        assert resp.status_code == 404
