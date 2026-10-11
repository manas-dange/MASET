"""
Demo Target — Messy Python Flask Web App
=========================================
This is the *target* repository that MA-SET agents will work on.
It is intentionally imperfect:
  - Missing input validation on several routes
  - No error handling on the signup endpoint
  - A protected legacy billing module (agents MUST NOT edit it)
  - Inconsistent response formats

MA-SET agents will receive tickets asking them to improve this app.
"""

from flask import Flask, jsonify, request

app = Flask(__name__)

# In-memory store (no persistence — keeps the demo self-contained)
_users: dict = {}      # email -> {password, name}
_tasks: dict = {}      # task_id -> {title, done, owner}
_task_counter: list = [0]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@app.route("/signup", methods=["POST"])
def signup():
    data = request.json or {}
    email = data["email"]
    password = data["password"]
    name = data.get("name", "")

    if email in _users:
        return jsonify({"error": "user already exists"}), 409

    _users[email] = {"password": password, "name": name}
    return jsonify({"message": "created", "email": email}), 201


@app.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email")
    password = data.get("password")

    user = _users.get(email)
    if not user or user["password"] != password:
        return jsonify({"error": "invalid credentials"}), 401

    # Calls the protected billing module to activate the free trial
    from demo_target import legacy_billing
    legacy_billing.activate_trial(email)

    return jsonify({"message": "logged in", "email": email})


# ---------------------------------------------------------------------------
# Tasks — some validation present, some missing
# ---------------------------------------------------------------------------

@app.route("/tasks", methods=["GET"])
def list_tasks():
    return jsonify(list(_tasks.values()))


@app.route("/tasks", methods=["POST"])
def create_task():
    data = request.json or {}
    title = data.get("title")
    if not title:
        return jsonify({"error": "title required"}), 400

    _task_counter[0] += 1
    task_id = _task_counter[0]
    _tasks[task_id] = {"id": task_id, "title": title, "done": False, "owner": data.get("owner", "")}
    return jsonify(_tasks[task_id]), 201


@app.route("/tasks/<int:task_id>", methods=["PATCH"])
def update_task(task_id):
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404

    data = request.json or {}
    if "done" in data:
        task["done"] = bool(data["done"])
    if "title" in data:
        task["title"] = data["title"]

    return jsonify(task)


@app.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    if task_id not in _tasks:
        return jsonify({"error": "not found"}), 404
    del _tasks[task_id]
    return jsonify({"message": "deleted"})


# ---------------------------------------------------------------------------
# Utility — clears in-memory state (test helper)
# ---------------------------------------------------------------------------

def _reset():
    _users.clear()
    _tasks.clear()
    _task_counter[0] = 0


if __name__ == "__main__":
    app.run(debug=True, port=5050)
