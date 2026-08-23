"""
presentation/composition_selector.py
────────────────────────────────────────────────────────────────────────────
CompositionSelector — archetype-to-handler dispatch layer.

Role in the pipeline
--------------------
    PresentationDesignPlan  (from DesignIntelligence)
            ↓
    PresentationRenderer.directive_for(slide.index)
            ↓
    SlideDesignDirective.archetype
            ↓
    CompositionSelector.select()          ← this module
            ↓
    CompositionResult.handler             ← callable or placeholder
            ↓
    PPTXBuilder / concrete composition

Responsibility
--------------
This module is ONLY responsible for:
  1. Mapping every LayoutArchetype to a CompositionHandler descriptor.
  2. Providing a safe, deterministic select() method that never crashes.
  3. Defining the CompositionHandler protocol that Phase 5 composition
     modules must implement.

This module does NOT:
  - Call Gemini or any external API.
  - Modify python-pptx objects directly.
  - Change renderer, builder, handlers, or schema files.
  - Implement full visual rendering for each archetype (Phase 5).

Fallback guarantee
------------------
If directive is None, archetype is None, or archetype is unrecognised,
select() returns a safe fallback CompositionResult derived from the
slide's SlideLayout — identical to the existing builder dispatch.

Design decisions
----------------
- Protocol-based handler typing: concrete implementations remain decoupled.
- Registry is a plain dict built once at import time: O(1) lookup, zero
  runtime overhead.
- All 32 LayoutArchetype values are registered; missing keys are impossible.
- Placeholder handlers are callable stubs that delegate to PPTXBuilder's
  existing _render_* methods — no visual regression in Phase 4.

Archetype coverage
------------------
All 32 LayoutArchetype values from ai/slide_design_schema.py are covered:

  Title group (3):     hero, hero_split, hero_image_overlay
  Section (1):         section_divider
  Single-column (4):   title_text, title_bullets, large_statement, editorial
  Two-column (4):      two_columns_equal, two_columns_asymmetric,
                       card_duo, icon_columns
  Image+text (4):      image_left_text_right, image_right_text_left,
                       full_bleed, image_sidebar
  Data/metrics (5):    three_cards, four_cards, big_number,
                       horizontal_metrics, chart_focus
  Structured (6):      timeline_horizontal, timeline_vertical, process_steps,
                       comparison_split, comparison_table, agenda
  Quote (3):           quote_centered, quote_side, large_typography
  Closing (2):         closing, minimal_final
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

from ai.schemas import SlideData, SlideLayout
from ai.slide_design_schema import (
    LayoutArchetype,
    SlideDesignDirective,
    _COMPATIBLE_ARCHETYPES,
    _DEFAULT_ARCHETYPE,
    safe_default_directive,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Handler protocol — contract every composition must satisfy
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class CompositionHandler(Protocol):
    """
    Protocol that every concrete composition renderer must implement.

    Phase 5 will provide one concrete CompositionHandler per archetype.
    Until then, PlaceholderHandler delegates to PPTXBuilder's existing
    _render_* methods so there is zero visual regression.

    Parameters
    ----------
    pptx_slide  : python-pptx Slide object (already added to the Presentation)
    slide       : SlideData with content fields
    directive   : SlideDesignDirective with spacing/alignment/accent data
    builder     : PPTXBuilder instance (for helper methods and theme access)

    The handler must not return a value — it mutates pptx_slide in-place.
    """

    def __call__(
        self,
        pptx_slide: Any,
        slide: SlideData,
        directive: SlideDesignDirective,
        builder: Any,
    ) -> None: ...


# ═══════════════════════════════════════════════════════════════════════════
# 2. Implementation status enum
# ═══════════════════════════════════════════════════════════════════════════

class HandlerStatus(str, Enum):
    """Lifecycle status of a composition handler."""
    IMPLEMENTED = "implemented"   # Full Phase 5 visual composition
    PLACEHOLDER = "placeholder"   # Delegates to existing builder._render_*
    PENDING     = "pending"       # Not yet implemented; fallback to layout


# ═══════════════════════════════════════════════════════════════════════════
# 3. CompositionResult — what select() returns
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CompositionResult:
    """
    Output of CompositionSelector.select().

    Fields
    ------
    archetype       : Resolved LayoutArchetype (may differ from directive if
                      fallback was applied).
    handler         : Callable implementing CompositionHandler protocol.
    status          : Whether the handler is a full implementation or placeholder.
    directive       : The resolved SlideDesignDirective (never None; may be a
                      safe default if the original was missing).
    fallback_used   : True when the original archetype was replaced by a
                      layout-derived default.
    fallback_reason : Human-readable explanation of why fallback was applied.
    """
    archetype:      LayoutArchetype
    handler:        Callable
    status:         HandlerStatus
    directive:      SlideDesignDirective
    fallback_used:  bool        = False
    fallback_reason: str        = ""


# ═══════════════════════════════════════════════════════════════════════════
# 4. Placeholder handler factory
# ═══════════════════════════════════════════════════════════════════════════

def _make_placeholder(
    archetype: LayoutArchetype,
    layout: SlideLayout,
) -> Callable:
    """
    Return a placeholder CompositionHandler for *archetype*.

    The placeholder delegates to the PPTXBuilder's existing _render_*
    dispatch so Phase 4 introduces zero visual regression.  When Phase 5
    provides a real implementation for this archetype, the registry entry
    is replaced with the concrete handler.

    The builder's existing dispatch is keyed on SlideLayout, so the
    placeholder maps archetype → parent SlideLayout → builder method.
    """
    # Map archetype → parent SlideLayout for builder delegation
    _ARCHETYPE_LAYOUT: dict[LayoutArchetype, SlideLayout] = {
        # Title
        LayoutArchetype.HERO:                   SlideLayout.TITLE,
        LayoutArchetype.HERO_SPLIT:             SlideLayout.TITLE,
        LayoutArchetype.HERO_IMAGE_OVERLAY:     SlideLayout.TITLE,
        # Section divider — no dedicated SlideLayout; delegate to TITLE
        LayoutArchetype.SECTION_DIVIDER:        SlideLayout.TITLE,
        # Single-column
        LayoutArchetype.TITLE_TEXT:             SlideLayout.TITLE_TEXT,
        LayoutArchetype.TITLE_BULLETS:          SlideLayout.TITLE_TEXT,
        LayoutArchetype.LARGE_STATEMENT:        SlideLayout.TITLE_TEXT,
        LayoutArchetype.EDITORIAL:              SlideLayout.TITLE_TEXT,
        # Two-column
        LayoutArchetype.TWO_COLUMNS_EQUAL:      SlideLayout.TWO_COLUMNS,
        LayoutArchetype.TWO_COLUMNS_ASYMMETRIC: SlideLayout.TWO_COLUMNS,
        LayoutArchetype.CARD_DUO:               SlideLayout.TWO_COLUMNS,
        LayoutArchetype.ICON_COLUMNS:           SlideLayout.TWO_COLUMNS,
        # Image + text
        LayoutArchetype.IMAGE_LEFT_TEXT_RIGHT:  SlideLayout.IMAGE_TEXT,
        LayoutArchetype.IMAGE_RIGHT_TEXT_LEFT:  SlideLayout.IMAGE_TEXT,
        LayoutArchetype.FULL_BLEED:             SlideLayout.IMAGE_TEXT,
        LayoutArchetype.IMAGE_SIDEBAR:          SlideLayout.IMAGE_TEXT,
        # Data / metrics
        LayoutArchetype.THREE_CARDS:            SlideLayout.STATISTICS,
        LayoutArchetype.FOUR_CARDS:             SlideLayout.STATISTICS,
        LayoutArchetype.BIG_NUMBER:             SlideLayout.STATISTICS,
        LayoutArchetype.HORIZONTAL_METRICS:     SlideLayout.STATISTICS,
        LayoutArchetype.CHART_FOCUS:            SlideLayout.CHART,
        # Structured
        LayoutArchetype.TIMELINE_HORIZONTAL:    SlideLayout.TIMELINE,
        LayoutArchetype.TIMELINE_VERTICAL:      SlideLayout.TIMELINE,
        LayoutArchetype.PROCESS_STEPS:          SlideLayout.TIMELINE,
        LayoutArchetype.COMPARISON_SPLIT:       SlideLayout.COMPARISON,
        LayoutArchetype.COMPARISON_TABLE:       SlideLayout.COMPARISON,
        LayoutArchetype.AGENDA:                 SlideLayout.AGENDA,
        # Quote
        LayoutArchetype.QUOTE_CENTERED:         SlideLayout.QUOTE,
        LayoutArchetype.QUOTE_SIDE:             SlideLayout.QUOTE,
        LayoutArchetype.LARGE_TYPOGRAPHY:       SlideLayout.QUOTE,
        # Closing
        LayoutArchetype.CLOSING:                SlideLayout.CONCLUSION,
        LayoutArchetype.MINIMAL_FINAL:          SlideLayout.CONCLUSION,
    }

    delegate_layout = _ARCHETYPE_LAYOUT.get(archetype, layout)

    def _placeholder_handler(
        pptx_slide: Any,
        slide: SlideData,
        directive: SlideDesignDirective,
        builder: Any,
    ) -> None:
        """
        Delegate to PPTXBuilder's existing layout-based renderer.

        This is the Phase 4 implementation.  Phase 5 will replace this
        with an archetype-specific composition that uses directive.spacing,
        directive.accent_shape, directive.title_width_ratio, etc.
        """
        # Builder's internal dispatch: SlideLayout → _render_* method
        _dispatch: dict[SlideLayout, Callable] = {
            SlideLayout.TITLE:       builder._render_title,
            SlideLayout.TITLE_TEXT:  builder._render_title_text,
            SlideLayout.IMAGE_TEXT:  builder._render_image_text,
            SlideLayout.TWO_COLUMNS: builder._render_two_columns,
            SlideLayout.COMPARISON:  builder._render_comparison,
            SlideLayout.TIMELINE:    builder._render_timeline,
            SlideLayout.STATISTICS:  builder._render_statistics,
            SlideLayout.CHART:       builder._render_chart,
            SlideLayout.QUOTE:       builder._render_quote,
            SlideLayout.CONCLUSION:  builder._render_conclusion,
        }
        render_fn = _dispatch.get(delegate_layout, builder._render_fallback)

        # builder._render_* signature: (pptx_slide, slide, variant)
        # variant is resolved by builder's VariantSelector — pass empty string
        # to let the builder decide (backward-compatible behaviour).
        from presentation.variants import VariantSelector, get_variants
        _variant_selector = VariantSelector()
        variants = get_variants(slide.layout)
        variant = _variant_selector.select(slide, variants) if variants else ""

        logger.debug(
            "CompositionSelector: placeholder for archetype=%s "
            "→ delegating to layout=%s render_fn=%s variant=%r",
            archetype.value,
            delegate_layout.value,
            render_fn.__name__,
            variant,
        )
        render_fn(pptx_slide, slide, variant)

    _placeholder_handler.__name__ = f"_placeholder_{archetype.value}"
    _placeholder_handler.__qualname__ = f"_placeholder_{archetype.value}"
    return _placeholder_handler


# ═══════════════════════════════════════════════════════════════════════════
# 5. Registry — one entry per LayoutArchetype
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class _RegistryEntry:
    """Internal registry record for one archetype."""
    archetype:   LayoutArchetype
    layout:      SlideLayout       # parent SlideLayout (for fallback)
    handler:     Callable
    status:      HandlerStatus
    description: str               # human-readable (logging / debug)


def _build_registry() -> dict[LayoutArchetype, _RegistryEntry]:
    """
    Build the archetype → _RegistryEntry mapping.

    Every LayoutArchetype must appear exactly once.  Phase 5 will replace
    PLACEHOLDER entries with IMPLEMENTED ones by updating this registry
    (or by injecting concrete handlers via register_handler()).

    The registry is built once at import time from _COMPATIBLE_ARCHETYPES,
    so it automatically stays in sync with slide_design_schema.py.
    """
    # Invert _COMPATIBLE_ARCHETYPES: archetype → parent SlideLayout
    _arch_to_layout: dict[LayoutArchetype, SlideLayout] = {}
    for layout, archs in _COMPATIBLE_ARCHETYPES.items():
        for arch in archs:
            _arch_to_layout[arch] = layout

    # Human-readable descriptions (mirrors _ARCHETYPE_DESCRIPTIONS in
    # design_intelligence.py — kept here for selector-level logging).
    _DESCRIPTIONS: dict[LayoutArchetype, str] = {
        LayoutArchetype.HERO:                   "Centred large title on solid colour background",
        LayoutArchetype.HERO_SPLIT:             "Title left / full-height image right",
        LayoutArchetype.HERO_IMAGE_OVERLAY:     "Full-bleed photo with dark overlay + title",
        LayoutArchetype.SECTION_DIVIDER:        "Large section number + label",
        LayoutArchetype.TITLE_TEXT:             "Heading + flowing body paragraph",
        LayoutArchetype.TITLE_BULLETS:          "Heading + concise bullet list",
        LayoutArchetype.LARGE_STATEMENT:        "One oversized statement sentence",
        LayoutArchetype.EDITORIAL:              "Heading left, body right — magazine style",
        LayoutArchetype.TWO_COLUMNS_EQUAL:      "Symmetric 50/50 columns",
        LayoutArchetype.TWO_COLUMNS_ASYMMETRIC: "40/60 split — context / content",
        LayoutArchetype.CARD_DUO:               "Two rounded dark cards with icon + text",
        LayoutArchetype.ICON_COLUMNS:           "Icon above each column",
        LayoutArchetype.IMAGE_LEFT_TEXT_RIGHT:  "Image left half, text right half",
        LayoutArchetype.IMAGE_RIGHT_TEXT_LEFT:  "Text left, image right",
        LayoutArchetype.FULL_BLEED:             "Photo edge-to-edge, caption box overlaid",
        LayoutArchetype.IMAGE_SIDEBAR:          "Narrow image strip + wide text area",
        LayoutArchetype.THREE_CARDS:            "Three stat/metric cards in a row",
        LayoutArchetype.FOUR_CARDS:             "2×2 grid of KPI cards",
        LayoutArchetype.BIG_NUMBER:             "One giant metric dominates the slide",
        LayoutArchetype.HORIZONTAL_METRICS:     "Metrics in a horizontal band",
        LayoutArchetype.CHART_FOCUS:            "Chart centred with label below",
        LayoutArchetype.TIMELINE_HORIZONTAL:    "Events along a horizontal axis",
        LayoutArchetype.TIMELINE_VERTICAL:      "Events stacked vertically",
        LayoutArchetype.PROCESS_STEPS:          "Numbered circular steps 1→2→3→4",
        LayoutArchetype.COMPARISON_SPLIT:       "Left vs right with distinct labels",
        LayoutArchetype.COMPARISON_TABLE:       "Feature × option matrix",
        LayoutArchetype.AGENDA:                 "Numbered table of contents",
        LayoutArchetype.QUOTE_CENTERED:         "Large centred quotation",
        LayoutArchetype.QUOTE_SIDE:             "Quote with attribution on the side",
        LayoutArchetype.LARGE_TYPOGRAPHY:       "Oversized type fills the slide",
        LayoutArchetype.CLOSING:                "Summary headline + call-to-action",
        LayoutArchetype.MINIMAL_FINAL:          "Just the topic line on a clean background",
    }

    registry: dict[LayoutArchetype, _RegistryEntry] = {}

    for arch in LayoutArchetype:
        layout = _arch_to_layout.get(arch, SlideLayout.TITLE_TEXT)
        handler = _make_placeholder(arch, layout)
        registry[arch] = _RegistryEntry(
            archetype=arch,
            layout=layout,
            handler=handler,
            status=HandlerStatus.PLACEHOLDER,
            description=_DESCRIPTIONS.get(arch, arch.value),
        )

    # Validate completeness at build time.
    missing = [a for a in LayoutArchetype if a not in registry]
    if missing:  # pragma: no cover
        raise RuntimeError(
            f"CompositionSelector registry is incomplete. "
            f"Missing archetypes: {[a.value for a in missing]}"
        )

    logger.debug(
        "CompositionSelector: registry built with %d archetype(s).",
        len(registry),
    )
    return registry


# Module-level registry — built once, shared by all CompositionSelector instances.
_REGISTRY: dict[LayoutArchetype, _RegistryEntry] = _build_registry()


# ═══════════════════════════════════════════════════════════════════════════
# 6. Public API — CompositionSelector
# ═══════════════════════════════════════════════════════════════════════════

class CompositionSelector:
    """
    Maps a SlideDesignDirective to the appropriate composition handler.

    Usage (Phase 4 — PresentationRenderer.render())::

        selector = CompositionSelector()

        for slide in plan.slides:
            directive = renderer.directive_for(slide.index)
            result    = selector.select(directive, slide)

            # result.handler is always callable — never None
            result.handler(
                pptx_slide=pptx_slide,
                slide=slide,
                directive=result.directive,
                builder=builder,
            )

    The selector is stateless and thread-safe; a single instance may be
    shared across the entire application lifetime.

    Fallback hierarchy
    ------------------
    1. directive.archetype found in registry          → registered handler
    2. directive is None or archetype is None         → layout-default archetype
    3. archetype not in registry (unknown value)      → layout-default archetype
    4. slide.layout not in _DEFAULT_ARCHETYPE         → TITLE_TEXT handler

    At every level the fallback is logged at WARNING so design failures
    are visible without crashing the pipeline.
    """

    # ------------------------------------------------------------------
    # Core select() method
    # ------------------------------------------------------------------

    def select(
        self,
        directive: SlideDesignDirective | None,
        slide: SlideData,
    ) -> CompositionResult:
        """
        Return a CompositionResult for *slide* based on *directive*.

        Parameters
        ----------
        directive:
            SlideDesignDirective from PresentationRenderer.directive_for().
            May be None if no design_plan is available for this slide.
        slide:
            SlideData carrying layout, title, and content for this slide.

        Returns
        -------
        CompositionResult — always valid, never raises.

        Guarantees
        ----------
        - result.handler is always callable.
        - result.directive is always a complete SlideDesignDirective.
        - result.archetype is always a valid LayoutArchetype in the registry.
        """
        # ── Case 1: no directive at all ───────────────────────────────────
        if directive is None:
            return self._layout_fallback(
                slide,
                reason="directive is None — no design_plan available",
            )

        # ── Case 2: archetype is None ─────────────────────────────────────
        if directive.archetype is None:
            return self._layout_fallback(
                slide,
                directive=directive,
                reason="directive.archetype is None",
            )

        # ── Case 3: archetype not in registry (schema mismatch) ───────────
        archetype: LayoutArchetype = directive.archetype
        entry = _REGISTRY.get(archetype)
        if entry is None:
            logger.warning(
                "CompositionSelector: unknown archetype %r for slide "
                "index=%d layout=%s — falling back to layout default.",
                archetype,
                slide.index,
                slide.layout.value,
            )
            return self._layout_fallback(
                slide,
                directive=directive,
                reason=f"archetype {archetype!r} not in registry",
            )

        # ── Case 4: happy path — dispatch to registered handler ───────────
        logger.debug(
            "CompositionSelector: slide index=%d → archetype=%s "
            "status=%s handler=%s",
            slide.index,
            archetype.value,
            entry.status.value,
            entry.handler.__name__,
        )
        return CompositionResult(
            archetype=archetype,
            handler=entry.handler,
            status=entry.status,
            directive=directive,
            fallback_used=False,
        )

    # ------------------------------------------------------------------
    # Registry introspection helpers (useful for tests & logging)
    # ------------------------------------------------------------------

    def registered_archetypes(self) -> list[LayoutArchetype]:
        """Return all archetypes currently in the registry, in definition order."""
        return list(_REGISTRY.keys())

    def status_for(self, archetype: LayoutArchetype) -> HandlerStatus:
        """Return the HandlerStatus for *archetype*."""
        entry = _REGISTRY.get(archetype)
        if entry is None:
            raise KeyError(f"Archetype {archetype!r} not in registry.")
        return entry.status

    def coverage_report(self) -> str:
        """
        Return a human-readable coverage report for all archetypes.

        Useful for CI / logging::

            selector = CompositionSelector()
            print(selector.coverage_report())
        """
        implemented = [
            e for e in _REGISTRY.values()
            if e.status == HandlerStatus.IMPLEMENTED
        ]
        placeholder = [
            e for e in _REGISTRY.values()
            if e.status == HandlerStatus.PLACEHOLDER
        ]
        pending = [
            e for e in _REGISTRY.values()
            if e.status == HandlerStatus.PENDING
        ]
        lines = [
            f"CompositionSelector — {len(_REGISTRY)} archetype(s) registered",
            f"  ✅ IMPLEMENTED : {len(implemented)}",
            f"  🔲 PLACEHOLDER : {len(placeholder)}",
            f"  ⏳ PENDING     : {len(pending)}",
            "",
            "Details:",
        ]
        for entry in _REGISTRY.values():
            icon = {"implemented": "✅", "placeholder": "🔲", "pending": "⏳"}[
                entry.status.value
            ]
            lines.append(
                f"  {icon} [{entry.layout.value:14s}] "
                f"{entry.archetype.value:30s}  {entry.description}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase 5 hook — register a concrete handler for one archetype
    # ------------------------------------------------------------------

    @staticmethod
    def register_handler(
        archetype: LayoutArchetype,
        handler: Callable,
        layout: SlideLayout | None = None,
        description: str = "",
    ) -> None:
        """
        Register a concrete CompositionHandler for *archetype*.

        Phase 5 modules call this at import time to replace the placeholder
        handler with a real visual composition::

            # In presentation/compositions/hero.py:
            from presentation.composition_selector import (
                CompositionSelector, HandlerStatus,
            )
            from ai.slide_design_schema import LayoutArchetype
            from ai.schemas import SlideLayout

            def render_hero(pptx_slide, slide, directive, builder): ...

            CompositionSelector.register_handler(
                archetype=LayoutArchetype.HERO,
                handler=render_hero,
                layout=SlideLayout.TITLE,
                description="Full HERO composition with gradient background",
            )

        Parameters
        ----------
        archetype   : LayoutArchetype to register for.
        handler     : Callable satisfying CompositionHandler protocol.
        layout      : Parent SlideLayout; defaults to existing registry value.
        description : Human-readable description (overwrites placeholder text).
        """
        existing = _REGISTRY.get(archetype)
        resolved_layout = layout or (existing.layout if existing else SlideLayout.TITLE_TEXT)
        resolved_desc   = description or (existing.description if existing else archetype.value)

        _REGISTRY[archetype] = _RegistryEntry(
            archetype=archetype,
            layout=resolved_layout,
            handler=handler,
            status=HandlerStatus.IMPLEMENTED,
            description=resolved_desc,
        )
        logger.info(
            "CompositionSelector: registered IMPLEMENTED handler for "
            "archetype=%s layout=%s",
            archetype.value,
            resolved_layout.value,
        )

    # ------------------------------------------------------------------
    # Internal fallback helper
    # ------------------------------------------------------------------

    def _layout_fallback(
        self,
        slide: SlideData,
        directive: SlideDesignDirective | None = None,
        reason: str = "",
    ) -> CompositionResult:
        """
        Produce a fallback CompositionResult derived from slide.layout.

        Uses _DEFAULT_ARCHETYPE to find the canonical archetype for the
        slide's SlideLayout, then looks it up in the registry.  This mirrors
        the existing PPTXBuilder dispatch so the visual output is identical
        to Phase 3 (no regression).

        If even the layout default is missing (should never happen given
        the registry build-time assertion), falls back to TITLE_TEXT.
        """
        from ai.slide_design_schema import SpacingDensity

        # Resolve default archetype for this layout
        default_arch = _DEFAULT_ARCHETYPE.get(slide.layout, LayoutArchetype.TITLE_TEXT)
        entry        = _REGISTRY.get(default_arch)

        if entry is None:
            # Absolute last resort — should be unreachable
            default_arch = LayoutArchetype.TITLE_TEXT
            entry        = _REGISTRY[default_arch]
            logger.error(
                "CompositionSelector: layout default archetype for "
                "layout=%s also missing from registry — using TITLE_TEXT.",
                slide.layout.value,
            )

        # Build a safe directive if none was provided
        resolved_directive = directive or safe_default_directive(
            slide_index=slide.index,
            layout=slide.layout,
            spacing=SpacingDensity.NORMAL,
        )

        if reason:
            logger.warning(
                "CompositionSelector: fallback for slide index=%d "
                "layout=%s → archetype=%s. Reason: %s",
                slide.index,
                slide.layout.value,
                default_arch.value,
                reason,
            )

        return CompositionResult(
            archetype=default_arch,
            handler=entry.handler,
            status=entry.status,
            directive=resolved_directive,
            fallback_used=True,
            fallback_reason=reason,
        )
