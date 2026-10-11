"""
P2.4 — Human Design Sign-Off Gate
====================================
Pauses the pipeline until a human explicitly approves or rejects the
design spec.  The decision and timestamp are logged as events so the
audit trail is complete.

Three operation modes
---------------------
interactive   — prints the design spec to stdout and waits for keyboard
                input ("approve" / "reject").  Used in live demos.

file          — writes the design spec to <gate_dir>/pending/<run_id>.json
                and polls for a sibling file <gate_dir>/decisions/<run_id>.json
                containing {"decision": "approve"|"reject", "comment": "..."}.
                Useful when the reviewer is on a different machine or in CI.

auto_approve  — always approves immediately; no I/O.  Used in stub/test mode
                so that the full pipeline can run unattended.

auto_reject   — always rejects; used to exercise the FB2 loop in tests.

Timeout
-------
In interactive and file modes a configurable timeout (default 300 s) causes
the gate to reject automatically and log a HUMAN_GATE_REJECTED event with
reason "timeout".

Events emitted
--------------
  HUMAN_GATE_OPENED
  HUMAN_GATE_APPROVED  (on approval)
  HUMAN_GATE_REJECTED  (on rejection or timeout)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class GateMode(str, Enum):
    INTERACTIVE  = "interactive"
    FILE         = "file"
    AUTO_APPROVE = "auto_approve"
    AUTO_REJECT  = "auto_reject"


@dataclass
class GateDecision:
    approved: bool
    comment: str = ""
    mode: str = ""
    elapsed_s: float = 0.0


class HumanGate:
    """
    Blocks the pipeline until a human approves or rejects the design spec.

    Parameters
    ----------
    mode : GateMode
        Operation mode (see module docstring).
    gate_dir : Path
        Root directory for file-mode pending/decision files.
    timeout_s : int
        Seconds before auto-rejection in interactive and file modes.
    event_callback : callable, optional
    run_id : str
    node : str
    agent : str
    """

    def __init__(
        self,
        mode: GateMode = GateMode.AUTO_APPROVE,
        gate_dir: Path = Path(".ma_set_gates"),
        timeout_s: int = 300,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        run_id: str = "no-run",
        node: str = "A2",
        agent: str = "human_gate",
    ):
        self._mode = mode
        self._gate_dir = gate_dir
        self._timeout = timeout_s
        self._cb = event_callback
        self._run_id = run_id
        self._node = node
        self._agent = agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, design_spec_text: str, run_id: Optional[str] = None) -> GateDecision:
        """
        Present the design spec to a human (or auto-decide in test modes)
        and return a GateDecision.

        Parameters
        ----------
        design_spec_text : str
            The rendered design spec (DesignSpec.render()).
        run_id : str, optional
            Override the run_id set in __init__.
        """
        rid = run_id or self._run_id
        self._emit(rid, "human_gate_opened", {
            "mode": self._mode,
            "spec_chars": len(design_spec_text),
        })

        start = time.monotonic()

        if self._mode == GateMode.AUTO_APPROVE:
            decision = GateDecision(
                approved=True, comment="auto-approved (stub/test mode)",
                mode=self._mode, elapsed_s=0.0,
            )
        elif self._mode == GateMode.AUTO_REJECT:
            decision = GateDecision(
                approved=False, comment="auto-rejected (test mode)",
                mode=self._mode, elapsed_s=0.0,
            )
        elif self._mode == GateMode.INTERACTIVE:
            decision = self._interactive(design_spec_text, rid, start)
        else:  # FILE
            decision = self._file_mode(design_spec_text, rid, start)

        decision.elapsed_s = round(time.monotonic() - start, 2)
        event_type = "human_gate_approved" if decision.approved else "human_gate_rejected"
        self._emit(rid, event_type, {
            "comment": decision.comment,
            "elapsed_s": decision.elapsed_s,
            "mode": self._mode,
        })
        return decision

    # ------------------------------------------------------------------
    # Mode implementations
    # ------------------------------------------------------------------

    def _interactive(self, spec: str, run_id: str, start: float) -> GateDecision:
        """Print spec and wait for keyboard input."""
        print("\n" + "═" * 70)
        print("  [GATE] HUMAN SIGN-OFF REQUIRED")
        print("═" * 70)
        print(spec)
        print("═" * 70)
        print(f"\nType 'approve' to proceed or 'reject' to send back to Architect.")
        print(f"(Auto-rejects in {self._timeout}s)\n")

        import signal

        def _timeout_handler(sig, frame):
            raise TimeoutError()

        original = signal.signal(signal.SIGALRM, _timeout_handler) \
            if hasattr(signal, 'SIGALRM') else None
        try:
            if hasattr(signal, 'SIGALRM'):
                signal.alarm(self._timeout)
            answer = input("Decision: ").strip().lower()
            if hasattr(signal, 'SIGALRM'):
                signal.alarm(0)
        except (TimeoutError, KeyboardInterrupt):
            return GateDecision(approved=False, comment="timeout", mode=self._mode)
        finally:
            if original and hasattr(signal, 'SIGALRM'):
                signal.signal(signal.SIGALRM, original)

        if answer.startswith("approve"):
            return GateDecision(approved=True, comment=answer, mode=self._mode)
        return GateDecision(approved=False, comment=answer, mode=self._mode)

    def _file_mode(self, spec: str, run_id: str, start: float) -> GateDecision:
        """Write spec to disk and poll for a decision file."""
        pending_dir = self._gate_dir / "pending"
        decision_dir = self._gate_dir / "decisions"
        pending_dir.mkdir(parents=True, exist_ok=True)
        decision_dir.mkdir(parents=True, exist_ok=True)

        pending_file = pending_dir / f"{run_id}.json"
        decision_file = decision_dir / f"{run_id}.json"

        pending_file.write_text(json.dumps({
            "run_id": run_id,
            "design_spec": spec,
            "instructions": (
                f"Write a file to {decision_file} with content: "
                '{"decision": "approve"|"reject", "comment": "your comment"}'
            ),
        }, indent=2))

        print(f"\n[GATE] Gate pending. Write approval to:\n   {decision_file}\n")

        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if decision_file.exists():
                try:
                    data = json.loads(decision_file.read_text())
                    approved = data.get("decision", "").lower().startswith("approve")
                    return GateDecision(
                        approved=approved,
                        comment=data.get("comment", ""),
                        mode=self._mode,
                    )
                except json.JSONDecodeError:
                    pass
            time.sleep(2)

        return GateDecision(approved=False, comment="timeout", mode=self._mode)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        if self._cb:
            try:
                self._cb({
                    "run_id": run_id,
                    "node": self._node,
                    "agent": self._agent,
                    "event_type": event_type,
                    "payload": payload,
                })
            except Exception:
                pass
