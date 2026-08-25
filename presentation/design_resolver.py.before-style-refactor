"""
presentation/design_resolver.py
────────────────────────────────────────────────────────────────────────────
Phase 2: DesignResolver — priority-based resolution of DesignSpec.

Priority order (Phase 2)
-------------------------
0. Explicit DesignIntent  →  user said "red background", "Arial font", etc.
1. Explicit user style    →  academic / modern / minimal
2. Topic-aware            →  ThemeSelector / TopicClassifier
3. Default                →  neutral palette + academic fonts

Phase 5 will add:
    between 0 and 1: BrandConfig constraints

Backward compatibility
-----------------------
If design_intent is None (or empty), behavior is IDENTICAL to Phase 1.
"""

from __future__ import annotations

import logging

from ai.design_intent import DesignIntent
from presentation.styles import get_theme
from presentation.theme_selector import (
    ThemeSelector,
    TopicProfile,
    Palette,
    get_palette,
    palette_to_theme,
)
from presentation.design_spec import (
    BrandConfig,
    DesignSpec,
    STYLE_FAMILY_MAP,
    _FONT_PAIRS,
)

logger = logging.getLogger(__name__)

# ── Singleton theme selector (mirrors renderer.py's current singleton) ────
_theme_selector = ThemeSelector()

# ── Styles that count as an explicit user choice ──────────────────────────
_EXPLICIT_STYLES = frozenset({"academic", "modern", "minimal"})


class DesignResolver:
    """
    Resolves a DesignSpec from plan metadata and optional DesignIntent.

    Usage (Phase 2)::

        resolver = DesignResolver()

        # With explicit intent
        intent = DesignIntent(background_color="#C0392B", style_hint="minimal")
        spec = resolver.resolve(topic="Табиғат", style="minimal",
                                style_is_explicit=True, design_intent=intent)

        # Without intent — identical to Phase 1 behavior
        spec = resolver.resolve(topic="Ғарыш", style="modern",
                                style_is_explicit=True)

        theme = spec.to_theme()
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        topic: str,
        style: str,
        style_is_explicit: bool = False,
        design_intent: DesignIntent | None = None,
    ) -> DesignSpec:
        """
        Return a DesignSpec applying the priority hierarchy.

        Parameters
        ----------
        topic            : Presentation topic (any language).
        style            : "academic" | "modern" | "minimal" from PresentationPlan.
        style_is_explicit: True when the user actively chose the style.
        design_intent    : Explicit visual preferences; None = no preferences.
        """
        # Priority 0 — explicit DesignIntent (Phase 2)
        if design_intent is not None and not design_intent.is_empty():
            return self._from_intent(
                design_intent, topic, style, style_is_explicit
            )

        # Priority 1 — explicit style choice (Phase 1 behavior)
        if style_is_explicit and style in _EXPLICIT_STYLES:
            return self._from_explicit_style(style)

        # Priority 2 — topic-aware (Phase 1 behavior)
        return self._from_topic(topic, style)

    # ------------------------------------------------------------------
    # Private resolution paths
    # ------------------------------------------------------------------

    def _from_intent(
        self,
        intent: DesignIntent,
        topic: str,
        style: str,
        style_is_explicit: bool,
    ) -> DesignSpec:
        """
        Priority 0 — user stated explicit design preferences.

        Strategy:
        1. Start from the base DesignSpec that would have been chosen by
           Priority 1 or 2 (style or topic) — this provides sensible defaults
           for anything the user did NOT specify.
        2. Apply DesignIntent overrides field-by-field on top of the base.

        This means:
        - "red background, nature topic" → nature palette colors EXCEPT
          background, which becomes red.
        - "minimal style, Arial heading font" → minimal palette + Arial heading.
        - "red background only" → topic palette with red background override.
        """
        # Step 1: resolve base spec from lower-priority rules
        if style_is_explicit and style in _EXPLICIT_STYLES:
            base_spec = self._from_explicit_style(style)
        else:
            base_spec = self._from_topic(topic, style)

        # Step 2: build an overridden Palette from intent
        base_palette  = base_spec.palette
        overridden    = self._apply_intent_to_palette(base_palette, intent)

        # Step 3: derive fonts — intent explicit fonts take priority
        font_h = intent.font_heading or base_spec.font_heading
        font_b = intent.font_body    or base_spec.font_body

        # Step 4: style_family — intent style_hint overrides base if present
        if intent.style_hint:
            family  = STYLE_FAMILY_MAP.get(intent.style_hint, base_spec.style_family)
        else:
            family  = base_spec.style_family

        # Step 5: density
        density = intent.density_hint or base_spec.density

        logger.info(
            "DesignResolver: intent | bg=%s primary=%s accent=%s "
            "font_h=%s font_b=%s style=%s density=%s",
            intent.background_color,
            intent.primary_color,
            intent.accent_color,
            font_h, font_b, family, density,
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

    @staticmethod
    def _apply_intent_to_palette(base: Palette, intent: DesignIntent) -> Palette:
        """
        Return a new Palette with intent overrides applied.

        Only fields explicitly set in DesignIntent are changed;
        everything else is inherited from base.
        """
        # Palette is a frozen dataclass — recreate with overrides
        bg      = intent.background_color or base.background
        primary = intent.primary_color    or base.primary
        accent  = intent.accent_color     or base.accent

        # Derive text_on_dark based on background brightness:
        # if user set a dark background keep existing text_on_dark,
        # if they set a light background keep it too — we don't auto-invert.
        return Palette(
            name=f"intent_override",
            background=bg,
            surface=bg,                   # surface mirrors background
            text_primary=base.text_primary,
            text_secondary=base.text_secondary,
            text_on_dark=base.text_on_dark,
            primary=primary,
            accent=accent,
            border=base.border,
            success=base.success,
            warning=base.warning,
        )

    def _from_explicit_style(self, style: str) -> DesignSpec:
        """Priority 1 — user explicitly chose academic / modern / minimal."""
        # Reuse the existing get_theme() so Theme stays the authority on
        # fixed-style palettes.  We then reverse-map back to a Palette.
        theme = get_theme(style)
        palette = self._palette_from_theme(theme, style)

        font_h, font_b = _FONT_PAIRS.get(style, _FONT_PAIRS["default"])

        logger.info(
            "DesignResolver: explicit style=%r → palette=%r fonts=%s/%s",
            style, palette.name, font_h, font_b,
        )

        return DesignSpec(
            palette=palette,
            font_heading=font_h,
            font_body=font_b,
            style_family=STYLE_FAMILY_MAP.get(style, "academic"),
            density="normal",
            brand=None,
            resolved_from="explicit_style",
        )

    def _from_topic(self, topic: str, style: str) -> DesignSpec:
        """Priority 2 — topic-aware via ThemeSelector."""
        theme, profile = _theme_selector.select_with_profile(topic)
        try:
            palette = get_palette(profile.palette_name)
        except KeyError:
            palette = get_palette("neutral")

        # Font pair: derive from palette mood (same logic as palette_to_theme)
        font_h, font_b = self._fonts_from_palette(palette.name)

        logger.info(
            "DesignResolver: topic-aware | topic=%r → category=%r "
            "palette=%r confidence=%.2f primary=%s accent=%s",
            topic,
            profile.primary_category,
            profile.palette_name,
            profile.confidence,
            theme.primary,
            theme.accent,
        )

        return DesignSpec(
            palette=palette,
            font_heading=font_h,
            font_body=font_b,
            style_family=self._family_from_profile(profile),
            density="normal",
            brand=None,
            resolved_from="topic_aware",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _palette_from_theme(theme, style: str):
        """
        Map a fixed Theme back to a Palette for DesignSpec.

        For the three explicit styles we keep a direct mapping so we don't
        duplicate any color values — the Theme remains the authority.
        We synthesise a minimal Palette that round-trips correctly through
        palette_to_theme().
        """
        from presentation.theme_selector import Palette as _Palette

        # Map style name → closest topic palette (same colours as the fixed Theme)
        _STYLE_PALETTE_MAP = {
            "academic": "neutral",    # Deep navy / gold → closest neutral
            "modern":   "technology", # Indigo / cyan → tech palette
            "minimal":  "neutral",    # Greyscale → neutral
        }

        base_palette_name = _STYLE_PALETTE_MAP.get(style, "neutral")
        try:
            base = get_palette(base_palette_name)
        except KeyError:
            base = get_palette("neutral")

        # Override the base palette's brand colors with the fixed Theme's
        # values so DesignSpec.to_theme() produces an identical Theme.
        return _Palette(
            name=style,
            background=theme.background,
            surface=theme.background,      # no separate surface in Theme
            text_primary=theme.text_dark,
            text_secondary=theme.secondary,
            text_on_dark=theme.text_light,
            primary=theme.primary,
            accent=theme.accent,
            border=theme.secondary,
            success=base.success,           # inherit from base
            warning=base.warning,
        )

    @staticmethod
    def _fonts_from_palette(palette_name: str) -> tuple[str, str]:
        """Derive font pair from palette name — mirrors palette_to_theme() logic."""
        warm = {"history", "agriculture", "nature"}
        tech = {"technology", "technology_business", "space"}

        if palette_name in warm:
            return "Georgia", "Calibri"
        if palette_name in tech:
            return "Arial", "Arial"
        return "Cambria", "Calibri"

    @staticmethod
    def _family_from_profile(profile: TopicProfile) -> str:
        """Map topic mood → style_family token."""
        mood_map = {
            "organic":              "editorial",
            "fluid":                "minimal",
            "clinical":             "academic",
            "digital":              "modern",
            "professional-digital": "modern",
            "authoritative":        "academic",
            "warm-heritage":        "editorial",
            "cosmic":               "modern",
            "scholarly":            "academic",
            "professional":         "academic",
            "earthy":               "editorial",
            "natural-fluid":        "editorial",
        }
        return mood_map.get(profile.visual_mood, "academic")
