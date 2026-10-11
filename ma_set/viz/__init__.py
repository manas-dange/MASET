"""
MA-SET Visualization Package (Phase 5)
=====================================
FastAPI backend service and rich real-time dashboard for live pipeline execution
and post-hoc run replay.
"""

from ma_set.viz.server import create_app

__all__ = ["create_app"]
