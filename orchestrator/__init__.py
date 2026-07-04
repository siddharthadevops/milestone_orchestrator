"""Deterministic orchestrator for the impl_roadmap_canon delivery flow.

Modules:
  contracts  JSON protocol between driver and LLM CLI workers
  state      append-only state machine with structural gate enforcement
  runners    subprocess + mock runners, JSON extraction/validation
  prompts    prompt builders per worker call kind
  driver     the hardcoded control loop and CLI
  webapp     read-only progress dashboard
"""

__version__ = "0.1.0"
