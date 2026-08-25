"""
presentation/design_spec.py
────────────────────────────────────────────────────────────────────────────
DesignSpec — carries Gemini's design decisions through the pipeline.

No preset style logic (academic/modern/minimal).
Gemini provides fonts, colors, spacing, and layout — this class holds them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from presentation.styles import Theme
from presentation.theme_selector import Palette, palette_to_theme


# ── BrandConfig (Phase 5 stub) ────────────────────────────────────────────

@dataclass(frozen=True)
class BrandConfig:
    """
    University / organisation brand constraints.
    Phase 1: all fields optional. Full implementation deferred to Phase 5.
    """
    name: str = ""
    primary_color: str = ""
    secondary_color: str = ""
    accent_color: str = ""
    font_heading: str = ""
    font_body: str = ""
    logo_path: str = ""

    def has_brand(self) -> bool:
        return bool(self.primary_color)


# ── DesignSpec ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DesignSpec:
    """
    Presentation-level design specification.

    Holds Gemini's design decisions: palette, fonts, style_family, density.
    No preset style selection — Gemini decides everything.
    """

    palette:       Palette
    font_heading:  str
    font_body:     str
    style_family:  str        = "default"
    density:       str        = "normal"
    brand:         BrandConfig | None = None
    resolved_from: str        = "default"

    def to_theme(self) -> Theme:
        """
        Convert DesignSpec → Theme expected by PPTXBuilder / render_* functions.
        """
        base_theme = palette_to_theme(self.palette)

        if (
            base_theme.font_heading != self.font_heading
            or base_theme.font_body  != self.font_body
        ):
            return base_theme.model_copy(update={
                "font_heading": self.font_heading,
                "font_body":    self.font_body,
            })

        return base_theme
