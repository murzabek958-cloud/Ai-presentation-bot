"""
presentation/design_spec.py
────────────────────────────────────────────────────────────────────────────
Phase 1: DesignSpec — a thin abstraction layer above the existing Theme system.

Purpose
-------
DesignSpec carries design intent through the pipeline so that future phases
(explicit user colors, brand constraints, composition hints) can be plugged
in WITHOUT changing the rendering layer.

Phase 1 scope
-------------
- Wraps an existing Palette and produces a Theme via to_theme().
- BrandConfig is a stub — populated in Phase 5 (university branding).
- No AI-based parsing, no new color system, no composition selector.

Backward compatibility guarantee
---------------------------------
DesignSpec.to_theme() always returns the same Theme type expected by
PPTXBuilder and all existing _render_* functions.  Nothing in the rendering
layer needs to know about DesignSpec yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from presentation.styles import Theme
from presentation.theme_selector import Palette, palette_to_theme


# ── Style families ────────────────────────────────────────────────────────
# Maps the three existing user-facing style names to an internal family token
# that future composition logic can read without depending on raw style strings.

STYLE_FAMILY_MAP: dict[str, str] = {
    "academic": "academic",
    "modern":   "modern",
    "minimal":  "minimal",
}

# Default font pairs per family (mirrors palette_to_theme() heuristic)
_FONT_PAIRS: dict[str, tuple[str, str]] = {
    "academic":  ("Cambria",  "Calibri"),
    "modern":    ("Arial",    "Arial"),
    "minimal":   ("Georgia",  "Georgia"),
    # topic-derived families reuse the same logic as palette_to_theme()
    "organic":   ("Georgia",  "Calibri"),
    "cosmic":    ("Arial",    "Arial"),
    "clinical":  ("Cambria",  "Calibri"),
    "scholarly": ("Cambria",  "Calibri"),
    "default":   ("Cambria",  "Calibri"),
}


# ── BrandConfig (Phase 5 stub) ────────────────────────────────────────────

@dataclass(frozen=True)
class BrandConfig:
    """
    University / organisation brand constraints.

    Phase 1: all fields optional; has_brand() returns False unless
    primary_color is set.  Full implementation deferred to Phase 5.
    """
    name: str = ""
    primary_color: str = ""       # '#RRGGBB' or ""
    secondary_color: str = ""
    accent_color: str = ""
    font_heading: str = ""
    font_body: str = ""
    logo_path: str = ""           # local path, set in Phase 5

    def has_brand(self) -> bool:
        """Return True only when meaningful brand data is present."""
        return bool(self.primary_color)


# ── DesignSpec ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DesignSpec:
    """
    Presentation-level design specification.

    Fields
    ------
    palette       : Palette from theme_selector — single source of color truth.
    font_heading  : Heading typeface string (e.g. "Cambria").
    font_body     : Body typeface string (e.g. "Calibri").
    style_family  : Visual style token — "academic" | "modern" | "minimal"
                    or a topic-derived mood ("cosmic", "clinical", …).
                    Future composition code reads this instead of raw style str.
    density       : Layout density hint — "spacious" | "normal" | "dense".
                    Phase 1: always "normal". Phase 3 will use it in
                    CompositionSelector.
    brand         : Optional BrandConfig; None in Phase 1.
    resolved_from : Debug string describing which priority rule fired.
                    Values: "explicit_style" | "topic_aware" | "default"
    """

    palette:       Palette
    font_heading:  str
    font_body:     str
    style_family:  str
    density:       str        = "normal"
    brand:         BrandConfig | None = None
    resolved_from: str        = "default"

    # ── Adapter ──────────────────────────────────────────────────────────

    def to_theme(self) -> Theme:
        """
        Convert DesignSpec → Theme expected by PPTXBuilder / render_* functions.

        Uses palette_to_theme() from the existing theme_selector module so
        that no color logic is duplicated.  Font overrides are applied on top.
        """
        base_theme = palette_to_theme(self.palette)

        # If our fonts differ from what palette_to_theme chose, rebuild Theme
        # with the correct pair.  Theme is frozen so we use model_copy().
        if (
            base_theme.font_heading != self.font_heading
            or base_theme.font_body  != self.font_body
        ):
            return base_theme.model_copy(update={
                "font_heading": self.font_heading,
                "font_body":    self.font_body,
            })

        return base_theme
