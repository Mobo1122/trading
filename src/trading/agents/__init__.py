"""Agent pipeline package for autonomous options trading.

Contains shared configuration, structured output contracts, LangGraph
pipeline state, and Postgres checkpoint factory used by all agents.

Phase 6 adds market regime detection (``regime.py``) and option
position rolling logic (``rolling.py``). The regime detector classifies
market conditions before the scanner runs, and rolling candidates from
the expiration monitor are injected into the pipeline by the app layer.
"""
