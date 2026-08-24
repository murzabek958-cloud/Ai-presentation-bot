"""
presentation/compositions/__init__.py
────────────────────────────────────────────────────────────────────────────
Phase 5 composition handler registry entry point.

Usage (application startup only — not in tests):

    from presentation.compositions import register_all_handlers
    register_all_handlers()

Each concrete handler module exposes a register() function that calls
CompositionSelector.register_handler(..., HandlerStatus.IMPLEMENTED).

This file stays import-side-effect free: no handler is registered merely
by importing this package.  registration happens only when
register_all_handlers() is called explicitly.
"""


def register_all_handlers() -> None:
    """
    Register all implemented Phase 5 composition handlers.

    Called explicitly by the application at startup (e.g. main.py).
    Tests must NOT call this function so that the existing PLACEHOLDER
    registry state remains unchanged during migration.

    As concrete handler modules are added, import and call their
    register() functions here following the same pattern.
    """
    # ── Priority 1 handlers ───────────────────────────────────────────────
    from .hero import register as register_hero
    register_hero()
