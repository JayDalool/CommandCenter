"""Phase 1 validation harness: `python -m ccd.validation phase1-readiness`.

Deterministic, side-effect free evidence for the Phase 1 graduation gate (findings doc, 2026-10-22). It replays
decisions through the shadow Autonomy Engine, checks them against an independent statement of the hard rules
(`oracle`), classifies every disagreement, and scores the 15 gate rows. It can never merge, deploy, write to a
live database or call GitHub: every write path is blocked before any scenario runs (`guard`), and a self-check
proves it.

Nothing here is imported by the daemon, and it adds no route.
"""
