"""
Event log writer
=================
Writes Event objects to a JSON-Lines file (one event per line).
The file is named  runs/<run_id>.jsonl  and is created automatically.

Usage
-----
    from ma_set.events.log import EventLog

    log = EventLog(run_id="abc-123")
    log.write(event)
    for event in log.replay():
        print(event)
"""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path
from typing import Iterator

from ma_set.events.schema import Event


_LOG_DIR = Path("runs")


class EventLog:
    """Append-only JSON-Lines log for a single pipeline run."""

    def __init__(self, run_id: str, log_dir: Path = _LOG_DIR):
        self.run_id = run_id
        self._path = log_dir / f"{run_id}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = count(0)

    @property
    def path(self) -> Path:
        return self._path

    def write(self, event: Event) -> None:
        """Append *event* to the log, stamping its sequence number."""
        event = event.model_copy(update={"sequence": next(self._seq)})
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(event.to_jsonl())

    def write_dict(self, event_dict: dict) -> None:
        """Accept a raw dict (from the model adapter callback) and write it."""
        # Ensure required fields have defaults
        event_dict.setdefault("sequence", next(self._seq))
        if not event_dict.get("timestamp"):
            from datetime import datetime, timezone
            event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event_dict) + "\n")

    def replay(self) -> Iterator[dict]:
        """Yield each event dict from the log file in order."""
        return self.replay_file(self._path)

    @classmethod
    def replay_file(cls, path: Path | str) -> Iterator[dict]:
        """Yield each event dict from a given JSONL log file."""
        p = Path(path).resolve()
        if not p.exists():
            return
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

