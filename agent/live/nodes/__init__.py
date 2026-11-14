"""Graph nodes (spec section 9.8). Each module exposes factories that close over the runtime.

- start.py:   ingest, first_response, verify, request_confirm, voice_check
- decide.py:  await_signal (the signal inbox), classify
- speak.py:   announce, guide
- actions.py: dispatch, brief_911, police, staff, fall_timer
- handoff.py: handoff (Utstein-style card)
"""
