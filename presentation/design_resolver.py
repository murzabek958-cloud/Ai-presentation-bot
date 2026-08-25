"""
presentation/design_resolver.py
────────────────────────────────────────────────────────────────────────────
DesignResolver — passes Gemini's design decisions through without overriding.

Gemini provides the full visual design (fonts, colors, layout, spacing).
This resolver only applies explicit user DesignIntent overrides on top.
No preset style logic (academic/modern/minimal) is applied here.
"""

from __future__ import annotations

import logging

from ai.design_intent import DesignIntent
from presentation.design_spec import BrandConfig, DesignSpec
from presentation.theme_selector import Palette, get_palette

logger = logging.getLogger(__name__)


class DesignResolver:
    """
    Resolves a DesignSpec from DesignIntent and optional fallback palette.

    Priority:
        0. Explicit DesignIntent colors/fonts  → user overrides
        1. Neutral palette defaults            → fallback only
    """

    def resolve(
        self,
        topic: str,
        style: str = "",
        style_is_explicit: bool = False,
        design_intent: DesignIntent | None = None,
    ) -> DesignSpec:
        """
        Return a DesignSpec.

        When design_intent is provided and non-empty, its values take priority.
        The style/topic parameters are accepted for backward compatibility
        but no longer select a preset theme.
        """
        if design_intent is not None and not design_intent.is_empty():
            return self._from_intent(design_intent)

        return self._default()

    def _from_intent(self, intent: DesignIntent) -> DesignSpec:
        """Apply explicit user DesignIntent over a neutral base palette."""
        try:
            base_palette = get_palette("neutral")
        except KeyError:
            base_palette = _minimal_palette()

        bg      = intent.background_color or base_palette.background
        primary = intent.primary_color    or base_palette.primary
        accent  = intent.accent_color     or base_palette.accent

        overridden = Palette(
            name="intent_override",
            background=bg,
            surface=bg,
            text_primary=base_palette.text_primary,
            text_secondary=base_palette.text_secondary,
            text_on_dark=base_palette.text_on_dark,
            primary=primary,
            accent=accent,
            border=base_palette.border,
            success=base_palette.success,
            warning=base_palette.warning,
        )

        font_h = intent.font_heading or "Calibri"
        font_b = intent.font_body    or "Calibri"
        family = intent.style_hint   or "default"
        density = intent.density_hint or "normal"

        logger.info(
            "DesignResolver: intent | bg=%s primary=%s accent=%s "
            "font_h=%s font_b=%s density=%s",
            intent.background_color,
            intent.primary_color,
            intent.accent_color,
            font_h, font_b, density,
        )

        return DesignSpec(
            palette=overridden,
            font_heading=font_h,
            font_body=font_b,
            style_family=family,
            density=density,
            brand=None,
            resolved_from="design_intent",
        )

    def _default(self) -> DesignSpec:
        """Neutral fallback — no preset style imposed."""
        try:
            palette = get_palette("neutral")
        except KeyError:
            palette = _minimal_palette()

        logger.debug("DesignResolver: using neutral default palette")

        return DesignSpec(
            palette=palette,
            font_heading="Calibri",
            font_body="Calibri",
            style_family="default",
            density="normal",
            brand=None,
            resolved_from="default",
        )


def _minimal_palette() -> Palette:
    """Emergency fallback Palette when theme_selector has no 'neutral'."""
    return Palette(
        name="fallback",
        background="#FFFFFF",
        surface="#FFFFFF",
        text_primary="#111111",
        text_secondary="#555555",
        text_on_dark="#FFFFFF",
        primary="#1E3A5F",
        accent="#E67E22",
        border="#CCCCCC",
        success="#27AE60",
        warning="#F39C12",
    )
