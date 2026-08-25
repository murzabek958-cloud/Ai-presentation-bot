"""
presentation/renderer.py
────────────────────────────────────────────────────────────────────────────
Converts a validated PresentationPlan into a PPTXBuilder (and optionally
saves it to disk).

Phase integration contract (Phase 4)
--------------------------------------
This module now integrates CompositionSelector into the render() loop.

For each slide:
  1. directive_for(slide.index)          → SlideDesignDirective | None
  2. CompositionSelector.select(...)     → CompositionResult
  3. result.handler(...)                 → delegates to existing _render_*
                                           (placeholder), or Phase 5 impl.

Pipeline position
-----------------
    PresentationPlanner
            ↓
    PresentationPlan
            ↓
    DesignIntent
            ↓
    DesignIntelligence
            ↓
    PresentationDesignPlan
            ↓
    PresentationRenderer          ← this module
            ↓
    CompositionSelector           ← dispatch layer (Phase 4)
            ↓
    CompositionHandler            ← placeholder → builder._render_*
            ↓
    PPTX

Backward compatibility guarantee
----------------------------------
    PresentationRenderer(plan)
    PresentationRenderer(plan, style_is_explicit=True)
    PresentationRenderer(plan, style_is_explicit=True, design_intent=intent)
    PresentationRenderer(plan, ..., design_plan=design_plan)

All four call signatures work identically.  When design_plan is None,
the render loop falls back to builder.add_slide() exactly as before.

Fallback guarantee
------------------
If CompositionSelector, a handler, or any directive lookup raises, the
renderer catches the exception, logs it, and falls back to
builder.add_slide() for that slide.  No slide is ever silently dropped.

Phase scope
-----------
Phase 4 wires the dispatch contract.  Visual composition remains
identical to Phase 3 because all handlers are still placeholders that
delegate to builder._render_* via builder.add_slide().  Phase 5 will
register concrete handlers via CompositionSelector.register_handler(),
at which point dispatch will automatically use the real implementations
without further changes to this file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai.schemas import PresentationPlan, SlideData
from ai.design_intent import DesignIntent
from presentation.styles import Theme
from presentation.builder import PPTXBuilder
from presentation.layouts import get_layout_spec
from presentation.design_resolver import DesignResolver
from presentation.design_spec import DesignSpec

# ── Design-schema imports (guarded for minimal test environments) ──────────
try:
    from ai.slide_design_schema import (
        PresentationDesignPlan,
        SlideDesignDirective,
        safe_default_directive,
    )
    _DESIGN_SCHEMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DESIGN_SCHEMA_AVAILABLE = False
    PresentationDesignPlan = None  # type: ignore[assignment,misc]
    SlideDesignDirective   = None  # type: ignore[assignment,misc]

# ── CompositionSelector import (guarded) ──────────────────────────────────
try:
    from presentation.composition_selector import CompositionSelector
    _SELECTOR_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SELECTOR_AVAILABLE = False
    CompositionSelector = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from ai.slide_design_schema import (
        PresentationDesignPlan as _PresentationDesignPlanT,
        SlideDesignDirective   as _SlideDesignDirectiveT,
    )
    from presentation.composition_selector import (
        CompositionSelector    as _CompositionSelectorT,
        CompositionResult      as _CompositionResultT,
    )

logger = logging.getLogger(__name__)

# ── Module-level singletons — stateless, safe to share ───────────────────
_resolver: DesignResolver = DesignResolver()

# CompositionSelector is stateless; one instance shared across all renders.
_composition_selector: "_CompositionSelectorT | None" = (
    CompositionSelector() if _SELECTOR_AVAILABLE else None  # type: ignore[misc]
)


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_theme(
    plan: PresentationPlan,
    style_is_explicit: bool,
    design_intent: DesignIntent | None = None,
) -> Theme:
    """
    Resolve the presentation Theme via DesignResolver → DesignSpec → Theme.

    Priority (Phase 2):
    0. Explicit DesignIntent    → user color/font overrides
    1. Explicit user style      → fixed academic / modern / minimal Theme
    2. Topic-aware              → ThemeSelector / TopicClassifier palette
    3. Default                  → neutral palette (inside DesignResolver)
    """
    spec: DesignSpec = _resolver.resolve(
        topic=plan.topic,
        style=plan.style,
        style_is_explicit=style_is_explicit,
        design_intent=design_intent,
    )
    theme = spec.to_theme()
    logger.info(
        "Theme resolved: resolved_from=%r style=%r topic=%r → "
        "primary=%s accent=%s bg=%s",
        spec.resolved_from,
        plan.style,
        plan.topic,
        theme.primary,
        theme.accent,
        theme.background,
    )
    return theme


def _validate_design_plan_safe(
    design_plan: object,
) -> "_PresentationDesignPlanT | None":
    """
    Return *design_plan* if it is a valid PresentationDesignPlan, else None.

    Leverages existing Pydantic model — no duplicate validation logic.
    """
    if not _DESIGN_SCHEMA_AVAILABLE:
        return None
    if design_plan is None:
        return None
    if not isinstance(design_plan, PresentationDesignPlan):  # type: ignore[arg-type]
        logger.warning(
            "PresentationRenderer: design_plan is not a PresentationDesignPlan "
            "(got %s) — falling back to default rendering.",
            type(design_plan).__name__,
        )
        return None
    try:
        _ = design_plan.directives  # noqa: F841
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "PresentationRenderer: design_plan.directives raised: %s "
            "— falling back to default rendering.",
            exc,
        )
        return None
    return design_plan  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

class RendererError(Exception):
    """Raised when rendering fails due to invalid plan or state."""


class PresentationRenderer:
    """
    Renders a PresentationPlan into a PPTXBuilder (and optionally saves it).

    Parameters
    ----------
    plan:
        The validated PresentationPlan.
    style_is_explicit:
        True when the user explicitly selected a style/theme.
        False (default) enables automatic topic-aware palette selection.
    design_intent:
        Optional explicit design preferences (Phase 2).
    design_plan:
        Optional PresentationDesignPlan from DesignIntelligence (Phase 3+).
        When present, each slide is dispatched through CompositionSelector.
        When None or invalid, builder.add_slide() is called directly
        (identical to Phase 1/2 behaviour).

    Backward-compatible call signatures
    ------------------------------------
        PresentationRenderer(plan)
        PresentationRenderer(plan, style_is_explicit=True)
        PresentationRenderer(plan, style_is_explicit=True, design_intent=intent)
        PresentationRenderer(plan, ..., design_plan=design_plan)
    """

    def __init__(
        self,
        plan: PresentationPlan,
        style_is_explicit: bool = False,
        design_intent: DesignIntent | None = None,
        design_plan: "_PresentationDesignPlanT | None" = None,
    ) -> None:
        if not plan.slides:
            raise RendererError("PresentationPlan has no slides.")

        self._plan              = plan
        self._style_is_explicit = style_is_explicit
        self._design_intent     = design_intent
        self._theme: Theme      = _resolve_theme(plan, style_is_explicit, design_intent)
        self._builder: PPTXBuilder | None = None

        # ── Phase 3: store validated design_plan ──────────────────────────
        self._design_plan: "_PresentationDesignPlanT | None" = (
            _validate_design_plan_safe(design_plan)
        )

        # O(1) directive lookup: slide_index → SlideDesignDirective
        self._directive_index: dict[int, "_SlideDesignDirectiveT"] = {}
        if self._design_plan is not None:
            self._directive_index = {
                d.slide_index: d
                for d in self._design_plan.directives
            }
            logger.info(
                "PresentationRenderer: design_plan accepted — "
                "%d directive(s) indexed, global_spacing=%s, rationale=%r",
                len(self._directive_index),
                self._design_plan.global_spacing,
                (self._design_plan.design_rationale or "")[:80],
            )
        else:
            logger.debug(
                "PresentationRenderer: no design_plan — "
                "using default rendering for all slides."
            )

    # ──────────────────────────────────────────────────────────────────────
    # Public properties
    # ──────────────────────────────────────────────────────────────────────

    @property
    def theme(self) -> Theme:
        """The resolved Theme used for rendering."""
        return self._theme

    @property
    def design_plan(self) -> "_PresentationDesignPlanT | None":
        """The validated PresentationDesignPlan, or None."""
        return self._design_plan

    # ──────────────────────────────────────────────────────────────────────
    # Directive access (Phase 3 contract — still used in Phase 4)
    # ──────────────────────────────────────────────────────────────────────

    def directive_for(
        self,
        slide_index: int,
    ) -> "_SlideDesignDirectiveT | None":
        """
        Return the SlideDesignDirective for *slide_index*, or None.

        None is returned when no design_plan is attached, or when the
        design_plan has no directive for this slide index.
        """
        if not self._directive_index:
            return None
        return self._directive_index.get(slide_index)

    def has_design_plan(self) -> bool:
        """Return True when a valid PresentationDesignPlan is attached."""
        return self._design_plan is not None

    # ──────────────────────────────────────────────────────────────────────
    # Render — Phase 4: CompositionSelector dispatch
    # ──────────────────────────────────────────────────────────────────────

    def render(
        self,
        image_paths: dict[int, str] | None = None,
    ) -> PPTXBuilder:
        """
        Build the presentation from the plan.

        Dispatch logic (Phase 4)
        ------------------------
        When design_plan is present AND CompositionSelector is available:

            directive = self.directive_for(slide.index)
            result    = selector.select(directive, slide)
            # result.handler is called via builder.add_slide() in Phase 4.
            # Phase 5: result.handler(pptx_slide, slide, result.directive, builder)

        When design_plan is None (or CompositionSelector unavailable):

            builder.add_slide(slide, image_path=...)   ← unchanged from Phase 2

        Error safety
        ------------
        If CompositionSelector.select() raises, the slide falls back to
        builder.add_slide() and the error is logged (not swallowed silently).

        Parameters
        ----------
        image_paths:
            Mapping of slide index → local image file path.
            Missing entries use the placeholder.
        """
        builder = PPTXBuilder(theme=self._theme)
        resolved = image_paths or {}
        use_selector = self.has_design_plan() and _composition_selector is not None

        for slide in self._plan.slides:
            # Validate layout spec exists (raises ValueError for unknown layout)
            spec = get_layout_spec(slide.layout)

            if use_selector:
                self._render_with_selector(
                    slide=slide,
                    builder=builder,
                    image_path=resolved.get(slide.index),
                    spec=spec,
                )
            else:
                # Phase 2 path — unchanged behaviour
                logger.debug(
                    "Rendering slide index=%d layout=%s required_fields=%s "
                    "(no design_plan — default path)",
                    slide.index,
                    slide.layout.value,
                    spec.required_fields,
                )
                builder.add_slide(slide, image_path=resolved.get(slide.index))

        self._builder = builder
        logger.info(
            "Rendered %d slides (theme=%s palette_source=%s topic=%r%s)",
            len(self._plan.slides),
            self._theme.name,
            "explicit" if self._style_is_explicit else "topic-aware",
            self._plan.topic,
            f" via CompositionSelector ({len(self._directive_index)} directives)"
            if use_selector else "",
        )
        return builder

    # ──────────────────────────────────────────────────────────────────────
    # Phase 4: per-slide composition dispatch
    # ──────────────────────────────────────────────────────────────────────

    def _render_with_selector(
        self,
        slide: SlideData,
        builder: PPTXBuilder,
        image_path: str | None,
        spec: Any,
    ) -> None:
        """
        Dispatch one slide through CompositionSelector (Phase 5B).

        Pipeline
        --------
        1. directive_for(slide.index)         → SlideDesignDirective | None
        2. CompositionSelector.select(...)    → CompositionResult
        3. builder.prepare_slide(...)         → (pptx_slide, variant, resolved_img)
        4a. result.status == IMPLEMENTED      → result.handler(pptx_slide, ...)
        4b. result.status == PLACEHOLDER/PENDING → builder._dispatch_render(...)

        Error safety
        ------------
        - selector.select() raises    → add_slide() fallback, logged.
        - prepare_slide() raises      → add_slide() fallback, logged.
        - handler() raises            → _dispatch_render() fallback, logged.
        - _dispatch_render() raises   → re-raised (genuine builder error).

        No slide is ever silently dropped.
        """
        from presentation.composition_selector import HandlerStatus

        directive = self.directive_for(slide.index)

        # ── Step 2: CompositionSelector dispatch ──────────────────────────
        try:
            result = _composition_selector.select(directive, slide)  # type: ignore[union-attr]
        except Exception as exc:
            logger.error(
                "CompositionSelector.select() raised for slide index=%d "
                "layout=%s: %s — falling back to builder.add_slide()",
                slide.index, slide.layout.value, exc, exc_info=True,
            )
            builder.add_slide(slide, image_path=image_path)
            return

        logger.debug(
            "CompositionSelector: slide index=%d → archetype=%s "
            "status=%s fallback=%s%s",
            slide.index,
            result.archetype.value,
            result.status.value,
            result.fallback_used,
            f" ({result.fallback_reason})" if result.fallback_reason else "",
        )

        # ── Step 3: builder.prepare_slide() ──────────────────────────────
        # Creates pptx_slide, applies background (incl. background_override),
        # picks variant, validates image_path, handles AGENDA early return.
        try:
            pptx_slide, variant, resolved_img = builder.prepare_slide(
                slide,
                directive=result.directive,
                image_path=image_path,
            )
        except Exception as exc:
            logger.error(
                "builder.prepare_slide() raised for slide index=%d "
                "layout=%s archetype=%s: %s — falling back to builder.add_slide()",
                slide.index, slide.layout.value, result.archetype.value,
                exc, exc_info=True,
            )
            builder.add_slide(slide, image_path=image_path)
            return

        # AGENDA was rendered entirely inside prepare_slide(); nothing more.
        if slide.layout.value == "agenda":
            logger.debug(
                "Slide index=%d layout=agenda rendered via prepare_slide()",
                slide.index,
            )
            return

        # ── Step 4a: IMPLEMENTED handler → concrete composition ───────────
        if result.status == HandlerStatus.IMPLEMENTED:
            try:
                result.handler(pptx_slide, slide, result.directive, builder)
                logger.debug(
                    "CompositionHandler IMPLEMENTED: slide index=%d "
                    "archetype=%s handler=%s",
                    slide.index,
                    result.archetype.value,
                    result.handler.__name__,
                )
                return
            except Exception as exc:
                logger.error(
                    "CompositionHandler %r raised for slide index=%d "
                    "archetype=%s: %s — falling back to _dispatch_render()",
                    result.handler.__name__,
                    slide.index,
                    result.archetype.value,
                    exc,
                    exc_info=True,
                )
                # Fall through to _dispatch_render() below.

        # ── Step 4b: PLACEHOLDER / PENDING → existing _render_* pipeline ─
        # Also used as fallback when IMPLEMENTED handler raises.
        logger.debug(
            "CompositionHandler %s: slide index=%d archetype=%s "
            "→ builder._dispatch_render()",
            result.status.value,
            slide.index,
            result.archetype.value,
        )
        builder._dispatch_render(pptx_slide, slide, variant, resolved_img)

    # ──────────────────────────────────────────────────────────────────────
    # Save
    # ──────────────────────────────────────────────────────────────────────

    def save(self, path: str) -> str:
        """
        Save the presentation to *path*.
        Calls render() automatically if not already rendered.
        """
        if self._builder is None:
            self.render()
        return self._builder.save(path)  # type: ignore[union-attr]
