"""
ai/slide_design_schema.py
────────────────────────────────────────────────────────────────────────────
Structured type contracts for the Gemini Design Intelligence layer.

Role in the pipeline
--------------------
    Planner  →  PresentationPlan (content)
                        ↓
          Gemini Design Intelligence
                        ↓
          PresentationDesignPlan  ← defined here
                        ↓
          CompositionSelector
                        ↓
          PPTXBuilder / Renderer

This module defines:

  1.  Enums — controlled vocabulary for archetype names, image treatments,
      text alignments, spacing density, and accent shapes.

  2.  SlideDesignDirective — Gemini's per-slide output: which archetype to
      use, where to place image/text, what accent to draw, what spacing to
      apply.  Every field is Optional so Gemini can be partial and
      CompositionSelector fills in safe defaults.

  3.  PresentationDesignPlan — wrapper holding one SlideDesignDirective per
      slide plus presentation-level choices (global palette override, font
      pair, density).

  4.  validate_design_plan() — validates a PresentationDesignPlan against
      the PresentationPlan it decorates, returning a ValidationResult.
      Invalid directives are replaced with safe defaults (never crash).

  5.  safe_default_directive() — returns a SlideDesignDirective that is
      always valid for a given SlideLayout, used as a fallback.

Design decisions
----------------
- All Pydantic models: Gemini SDK can validate/parse them directly.
- All enums are str-based: JSON-serialisable without extra config.
- No python-pptx imports: this module is pure schema / validation.
- Enums include only values that PPTXBuilder can actually render.
  Unrecognised values from Gemini are caught at validation time.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ai.schemas import SlideLayout

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ENUMS — controlled vocabulary
# ═══════════════════════════════════════════════════════════════════════════

class LayoutArchetype(str, Enum):
    """
    Visual archetype library.

    Each value names a concrete composition that PPTXBuilder knows how to
    render.  New archetypes must be added here AND implemented in
    CompositionSelector / the relevant compositions/ module before use.

    Naming convention: <primary_element>_<secondary_element> or intent.
    """

    # ── Title / cover slides ─────────────────────────────────────────────
    HERO                    = "hero"               # centred title on colour bg
    HERO_SPLIT              = "hero_split"         # title left | image right
    HERO_IMAGE_OVERLAY      = "hero_image_overlay" # full-bleed photo + dark overlay

    # ── Section dividers / transitions ───────────────────────────────────
    SECTION_DIVIDER         = "section_divider"    # large number + topic label

    # ── Content: single column ───────────────────────────────────────────
    TITLE_TEXT              = "title_text"         # heading + body paragraph
    TITLE_BULLETS           = "title_bullets"      # heading + bullet list
    LARGE_STATEMENT         = "large_statement"    # single oversized sentence
    EDITORIAL               = "editorial"          # heading left + body right

    # ── Content: two columns ─────────────────────────────────────────────
    TWO_COLUMNS_EQUAL       = "two_columns_equal"  # symmetric halves
    TWO_COLUMNS_ASYMMETRIC  = "two_columns_asymmetric"  # 40/60 split
    CARD_DUO                = "card_duo"           # two dark cards with icon+text
    ICON_COLUMNS            = "icon_columns"       # icon top, text below each col

    # ── Image + text ─────────────────────────────────────────────────────
    IMAGE_LEFT_TEXT_RIGHT   = "image_left_text_right"
    IMAGE_RIGHT_TEXT_LEFT   = "image_right_text_left"
    FULL_BLEED              = "full_bleed"         # photo edge-to-edge, caption
    IMAGE_SIDEBAR           = "image_sidebar"      # narrow image strip + text

    # ── Data / metrics ───────────────────────────────────────────────────
    THREE_CARDS             = "three_cards"        # 3 stat cards
    FOUR_CARDS              = "four_cards"         # 4 kpi cards 2×2
    BIG_NUMBER              = "big_number"         # one oversized metric
    HORIZONTAL_METRICS      = "horizontal_metrics" # metrics in a row
    CHART_FOCUS             = "chart_focus"        # chart centred, label below

    # ── Structured layouts ────────────────────────────────────────────────
    TIMELINE_HORIZONTAL     = "timeline_horizontal"
    TIMELINE_VERTICAL       = "timeline_vertical"
    PROCESS_STEPS           = "process_steps"      # 1→2→3→4 flow
    COMPARISON_SPLIT        = "comparison_split"   # left/right with labels
    COMPARISON_TABLE        = "comparison_table"   # feature × option matrix
    AGENDA                  = "agenda"             # numbered TOC

    # ── Quote ────────────────────────────────────────────────────────────
    QUOTE_CENTERED          = "quote_centered"
    QUOTE_SIDE              = "quote_side"
    LARGE_TYPOGRAPHY        = "large_typography"

    # ── Closing ──────────────────────────────────────────────────────────
    CLOSING                 = "closing"            # summary + CTA
    MINIMAL_FINAL           = "minimal_final"      # just the topic line


class ImageTreatment(str, Enum):
    """How an image is cropped, filtered, or composited."""
    NONE            = "none"           # no image
    NATURAL         = "natural"        # original colours, no filter
    DARK_OVERLAY    = "dark_overlay"   # dark transparent layer for text legibility
    LIGHT_OVERLAY   = "light_overlay"  # white transparent layer
    GREYSCALE       = "greyscale"      # desaturated
    BLURRED         = "blurred"        # soft focus, used as texture
    FULL_HEIGHT     = "full_height"    # image crops to full slide height


class ImagePosition(str, Enum):
    NONE    = "none"
    LEFT    = "left"
    RIGHT   = "right"
    TOP     = "top"
    BOTTOM  = "bottom"
    FULL    = "full"   # edge-to-edge / full bleed
    INSET   = "inset"  # centred with margin


class TextAlignment(str, Enum):
    LEFT    = "left"
    CENTER  = "center"
    RIGHT   = "right"


class SpacingDensity(str, Enum):
    SPACIOUS = "spacious"  # large whitespace, fewer elements
    NORMAL   = "normal"
    DENSE    = "dense"     # small gaps, more content


class AccentShape(str, Enum):
    """Decorative accent element drawn by the renderer."""
    NONE            = "none"
    LINE_BOTTOM     = "line_bottom"     # horizontal rule below title
    LINE_LEFT       = "line_left"       # vertical bar on left edge
    LINE_RIGHT      = "line_right"      # vertical bar on right edge
    DOT_GRID        = "dot_grid"        # subtle dot matrix background pattern
    CORNER_BRACKET  = "corner_bracket"  # bracket in one corner
    FULL_SIDE_BAR   = "full_side_bar"   # full-height accent bar


class AccentPosition(str, Enum):
    """Where the accent element is drawn relative to the slide."""
    NONE            = "none"
    TITLE_BOTTOM    = "title_bottom"
    SLIDE_LEFT      = "slide_left"
    SLIDE_RIGHT     = "slide_right"
    SLIDE_TOP       = "slide_top"
    SLIDE_BOTTOM    = "slide_bottom"


# ── Layout → compatible archetypes mapping ────────────────────────────────
# Used by validate_design_plan() to reject archetypes Gemini picks that
# cannot physically render for a given SlideLayout.

_COMPATIBLE_ARCHETYPES: dict[SlideLayout, frozenset[LayoutArchetype]] = {
    SlideLayout.TITLE: frozenset({
        LayoutArchetype.HERO,
        LayoutArchetype.HERO_SPLIT,
        LayoutArchetype.HERO_IMAGE_OVERLAY,
    }),
    SlideLayout.TITLE_TEXT: frozenset({
        LayoutArchetype.TITLE_TEXT,
        LayoutArchetype.TITLE_BULLETS,
        LayoutArchetype.LARGE_STATEMENT,
        LayoutArchetype.EDITORIAL,
    }),
    SlideLayout.IMAGE_TEXT: frozenset({
        LayoutArchetype.IMAGE_LEFT_TEXT_RIGHT,
        LayoutArchetype.IMAGE_RIGHT_TEXT_LEFT,
        LayoutArchetype.FULL_BLEED,
        LayoutArchetype.IMAGE_SIDEBAR,
    }),
    SlideLayout.TWO_COLUMNS: frozenset({
        LayoutArchetype.TWO_COLUMNS_EQUAL,
        LayoutArchetype.TWO_COLUMNS_ASYMMETRIC,
        LayoutArchetype.CARD_DUO,
        LayoutArchetype.ICON_COLUMNS,
    }),
    SlideLayout.COMPARISON: frozenset({
        LayoutArchetype.COMPARISON_SPLIT,
        LayoutArchetype.COMPARISON_TABLE,
        LayoutArchetype.CARD_DUO,
    }),
    SlideLayout.TIMELINE: frozenset({
        LayoutArchetype.TIMELINE_HORIZONTAL,
        LayoutArchetype.TIMELINE_VERTICAL,
        LayoutArchetype.PROCESS_STEPS,
    }),
    SlideLayout.STATISTICS: frozenset({
        LayoutArchetype.THREE_CARDS,
        LayoutArchetype.FOUR_CARDS,
        LayoutArchetype.BIG_NUMBER,
        LayoutArchetype.HORIZONTAL_METRICS,
    }),
    SlideLayout.CHART: frozenset({
        LayoutArchetype.CHART_FOCUS,
    }),
    SlideLayout.QUOTE: frozenset({
        LayoutArchetype.QUOTE_CENTERED,
        LayoutArchetype.QUOTE_SIDE,
        LayoutArchetype.LARGE_TYPOGRAPHY,
    }),
    SlideLayout.CONCLUSION: frozenset({
        LayoutArchetype.CLOSING,
        LayoutArchetype.MINIMAL_FINAL,
        LayoutArchetype.LARGE_STATEMENT,
    }),
    SlideLayout.AGENDA: frozenset({
        LayoutArchetype.AGENDA,
    }),
}

# ── Default archetype per SlideLayout ────────────────────────────────────
# Used when Gemini returns an incompatible or missing archetype.

_DEFAULT_ARCHETYPE: dict[SlideLayout, LayoutArchetype] = {
    SlideLayout.TITLE:       LayoutArchetype.HERO,
    SlideLayout.TITLE_TEXT:  LayoutArchetype.TITLE_TEXT,
    SlideLayout.IMAGE_TEXT:  LayoutArchetype.IMAGE_RIGHT_TEXT_LEFT,
    SlideLayout.TWO_COLUMNS: LayoutArchetype.TWO_COLUMNS_EQUAL,
    SlideLayout.COMPARISON:  LayoutArchetype.COMPARISON_SPLIT,
    SlideLayout.TIMELINE:    LayoutArchetype.TIMELINE_HORIZONTAL,
    SlideLayout.STATISTICS:  LayoutArchetype.THREE_CARDS,
    SlideLayout.CHART:       LayoutArchetype.CHART_FOCUS,
    SlideLayout.QUOTE:       LayoutArchetype.QUOTE_CENTERED,
    SlideLayout.CONCLUSION:  LayoutArchetype.CLOSING,
    SlideLayout.AGENDA:      LayoutArchetype.AGENDA,
}


# ═══════════════════════════════════════════════════════════════════════════
# 2. SlideDesignDirective — per-slide Gemini output
# ═══════════════════════════════════════════════════════════════════════════

class SlideDesignDirective(BaseModel):
    """
    Gemini's visual design instruction for a single slide.

    All fields are Optional: Gemini may omit fields it has no strong
    opinion about.  Missing fields are filled by safe_default_directive()
    during validation so the renderer always receives complete data.

    Field notes
    -----------
    slide_index      : Must match SlideData.index.
    archetype        : The named visual composition to use.  CompositionSelector
                       maps this to a concrete render function.
    image_treatment  : How to process/filter the slide's image (if any).
    image_position   : Where the image is placed relative to the text area.
    text_alignment   : Primary text block horizontal alignment.
    title_width_ratio: Fraction of slide width for the title text box (0–1).
                       e.g. 0.55 means title occupies 55% of slide width.
    accent_shape     : Decorative element type.
    accent_position  : Where the decorative element is placed.
    spacing          : Overall whitespace density for this slide.
    background_override: Optional '#RRGGBB' to override the global palette
                         background for this slide only.
    notes            : Free-text rationale from Gemini (ignored by renderer,
                       useful for logging/debugging).
    """

    slide_index:          int
    archetype:            LayoutArchetype | None          = None
    image_treatment:      ImageTreatment                  = ImageTreatment.NATURAL
    image_position:       ImagePosition                   = ImagePosition.NONE
    text_alignment:       TextAlignment                   = TextAlignment.LEFT
    title_width_ratio:    float | None                    = Field(None, ge=0.2, le=1.0)
    accent_shape:         AccentShape                     = AccentShape.LINE_BOTTOM
    accent_position:      AccentPosition                  = AccentPosition.TITLE_BOTTOM
    spacing:              SpacingDensity                  = SpacingDensity.NORMAL
    background_override:  str | None                      = None  # '#RRGGBB'
    notes:                str                             = ""

    @model_validator(mode="after")
    def _normalise_image_fields(self) -> SlideDesignDirective:
        """If no image treatment specified, default image_position to NONE."""
        if self.image_treatment == ImageTreatment.NONE:
            object.__setattr__(self, "image_position", ImagePosition.NONE)
        return self

    class Config:
        use_enum_values = False   # keep enum objects, not raw strings


# ═══════════════════════════════════════════════════════════════════════════
# 3. PresentationDesignPlan — full Gemini design output
# ═══════════════════════════════════════════════════════════════════════════

class PresentationDesignPlan(BaseModel):
    """
    Gemini Design Intelligence output for the entire presentation.

    Fields
    ------
    directives        : One SlideDesignDirective per slide, in slide_index order.
                        May be a partial list — missing slides get defaults.
    global_font_heading: Optional font override for the whole presentation.
    global_font_body  : Optional font override for the whole presentation.
    global_spacing    : Default spacing density; individual slides may override.
    design_rationale  : Free-text from Gemini explaining the overall design
                        direction (logging/debugging only).
    """

    directives:           list[SlideDesignDirective]  = Field(default_factory=list)
    global_font_heading:  str | None                  = None
    global_font_body:     str | None                  = None
    global_spacing:       SpacingDensity               = SpacingDensity.NORMAL
    design_rationale:     str                          = ""


# ═══════════════════════════════════════════════════════════════════════════
# 4. Validation
# ═══════════════════════════════════════════════════════════════════════════

class DirectiveValidationResult(BaseModel):
    """Per-slide validation outcome."""
    slide_index:      int
    original:         SlideDesignDirective
    final:            SlideDesignDirective   # may equal original if valid
    warnings:         list[str]              = Field(default_factory=list)
    archetype_fixed:  bool                   = False


class DesignPlanValidationResult(BaseModel):
    """Overall validation outcome for a PresentationDesignPlan."""
    passed:             bool
    slide_results:      list[DirectiveValidationResult]  = Field(default_factory=list)
    missing_slides:     list[int]                        = Field(default_factory=list)
    warnings:           list[str]                        = Field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Passed: {self.passed}"]
        if self.missing_slides:
            lines.append(f"Missing directives for slides: {self.missing_slides}")
        for r in self.slide_results:
            if r.warnings:
                lines.append(f"  slide {r.slide_index}: {'; '.join(r.warnings)}")
        if self.warnings:
            lines.extend(self.warnings)
        return "\n".join(lines)


def safe_default_directive(
    slide_index: int,
    layout: SlideLayout,
    spacing: SpacingDensity = SpacingDensity.NORMAL,
) -> SlideDesignDirective:
    """
    Return a SlideDesignDirective that is always valid for *layout*.

    Used when:
    - Gemini returned no directive for a slide.
    - Gemini's archetype is incompatible with the slide's SlideLayout.
    - JSON schema validation failed entirely.
    """
    archetype = _DEFAULT_ARCHETYPE.get(layout, LayoutArchetype.TITLE_TEXT)

    # Image-bearing layouts default to right-positioned natural image
    image_pos = ImagePosition.NONE
    image_treatment = ImageTreatment.NONE
    if layout == SlideLayout.IMAGE_TEXT:
        image_pos = ImagePosition.RIGHT
        image_treatment = ImageTreatment.NATURAL
    elif layout == SlideLayout.TITLE:
        image_treatment = ImageTreatment.NONE

    return SlideDesignDirective(
        slide_index=slide_index,
        archetype=archetype,
        image_treatment=image_treatment,
        image_position=image_pos,
        text_alignment=TextAlignment.LEFT,
        title_width_ratio=None,
        accent_shape=AccentShape.LINE_BOTTOM,
        accent_position=AccentPosition.TITLE_BOTTOM,
        spacing=spacing,
        background_override=None,
        notes="[safe default]",
    )


def validate_design_plan(
    design_plan: PresentationDesignPlan,
    slide_layout_map: dict[int, SlideLayout],
) -> tuple[PresentationDesignPlan, DesignPlanValidationResult]:
    """
    Validate *design_plan* against a map of {slide_index: SlideLayout}.

    For each slide:
    1. If no directive exists → create a safe default.
    2. If archetype is None → assign the layout's default archetype.
    3. If archetype is incompatible with the slide's SlideLayout → replace
       with the layout's default archetype and record a warning.
    4. For IMAGE_TEXT slides: if image_position is NONE, set RIGHT.

    Returns
    -------
    (validated_plan, result)
        validated_plan : PresentationDesignPlan with all issues fixed.
        result         : DesignPlanValidationResult for logging.

    Guarantees
    ----------
    - Never raises.
    - validated_plan always has exactly one directive per slide in
      slide_layout_map, in slide_index order.
    - All archetypes in validated_plan are compatible with their layouts.
    """
    global_spacing = design_plan.global_spacing

    # Index existing directives by slide_index
    directive_by_index: dict[int, SlideDesignDirective] = {
        d.slide_index: d for d in design_plan.directives
    }

    slide_results: list[DirectiveValidationResult] = []
    missing: list[int] = []
    plan_warnings: list[str] = []
    final_directives: list[SlideDesignDirective] = []

    for idx in sorted(slide_layout_map.keys()):
        layout = slide_layout_map[idx]
        compatible = _COMPATIBLE_ARCHETYPES.get(layout, frozenset())
        default_arch = _DEFAULT_ARCHETYPE.get(layout, LayoutArchetype.TITLE_TEXT)

        if idx not in directive_by_index:
            # Gemini gave no directive for this slide
            missing.append(idx)
            directive = safe_default_directive(idx, layout, global_spacing)
            slide_results.append(DirectiveValidationResult(
                slide_index=idx,
                original=directive,
                final=directive,
                warnings=[f"No directive from Gemini — using safe default ({default_arch.value})"],
                archetype_fixed=False,
            ))
            final_directives.append(directive)
            continue

        original = directive_by_index[idx]
        warnings: list[str] = []
        archetype_fixed = False
        resolved_arch = original.archetype

        # Fix missing archetype
        if resolved_arch is None:
            resolved_arch = default_arch
            warnings.append(f"archetype was None → set to {default_arch.value}")
            archetype_fixed = True

        # Fix incompatible archetype
        elif resolved_arch not in compatible:
            warnings.append(
                f"archetype {resolved_arch.value!r} incompatible with layout "
                f"{layout.value!r} → replaced with {default_arch.value!r}"
            )
            resolved_arch = default_arch
            archetype_fixed = True

        # Fix IMAGE_TEXT image_position
        image_position = original.image_position
        if (
            layout == SlideLayout.IMAGE_TEXT
            and image_position == ImagePosition.NONE
        ):
            image_position = ImagePosition.RIGHT
            warnings.append("image_position was NONE for IMAGE_TEXT → set to RIGHT")

        if warnings:
            logger.warning(
                "SlideDesignDirective slide_index=%d: %s",
                idx,
                "; ".join(warnings),
            )

        # Build final directive (only rebuild if something changed)
        if archetype_fixed or image_position != original.image_position:
            final = original.model_copy(update={
                "archetype":      resolved_arch,
                "image_position": image_position,
            })
        else:
            final = original

        slide_results.append(DirectiveValidationResult(
            slide_index=idx,
            original=original,
            final=final,
            warnings=warnings,
            archetype_fixed=archetype_fixed,
        ))
        final_directives.append(final)

    passed = not missing and all(not r.warnings for r in slide_results)

    validated_plan = design_plan.model_copy(update={"directives": final_directives})
    result = DesignPlanValidationResult(
        passed=passed,
        slide_results=slide_results,
        missing_slides=missing,
        warnings=plan_warnings,
    )

    if not passed:
        logger.info(
            "DesignPlan validation completed with issues:\n%s", result.summary()
        )
    else:
        logger.debug("DesignPlan validation passed for %d slides.", len(slide_layout_map))

    return validated_plan, result
