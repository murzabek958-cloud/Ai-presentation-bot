"""
Design Variety Engine for AI Presentation Bot.

Provides:
- SlideVariant  — typed variant names per layout
- LAYOUT_VARIANTS  — mapping of SlideLayout → available variants
- VariantSelector — stateful selector that avoids repeating variants consecutively

Usage:
    selector = VariantSelector()
    variant = selector.pick(SlideLayout.TITLE)   # e.g. "hero_center"
    variant = selector.pick(SlideLayout.TITLE)   # guaranteed ≠ "hero_center"
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List

from ai.schemas import SlideLayout

# ---------------------------------------------------------------------------
# Variant name constants (plain strings — no extra enum overhead)
# ---------------------------------------------------------------------------

# TITLE
TITLE_HERO_CENTER  = "hero_center"
TITLE_HERO_LEFT    = "hero_left"
TITLE_HERO_BAND    = "hero_band"

# TITLE_TEXT
TITLE_TEXT_EDITORIAL      = "editorial"
TITLE_TEXT_CLEAN          = "clean"
TITLE_TEXT_LARGE_STATEMENT = "large_statement"

# STATISTICS
STATS_THREE_CARDS       = "three_cards"
STATS_BIG_NUMBER        = "big_number"
STATS_HORIZONTAL_METRICS = "horizontal_metrics"

# TWO_COLUMNS
TWO_COL_EQUAL      = "equal_columns"
TWO_COL_ASYMMETRIC = "asymmetric_columns"
TWO_COL_TEXT_EMPH  = "text_emphasis"

# COMPARISON
CMP_SPLIT_SCREEN    = "split_screen"
CMP_CARD_COMPARISON = "card_comparison"
CMP_VERTICAL        = "vertical_comparison"

# TIMELINE
TIMELINE_HORIZONTAL    = "horizontal"
TIMELINE_VERTICAL      = "vertical"
TIMELINE_MILESTONE     = "milestone_cards"

# CHART
CHART_FOCUS       = "chart_focus"
CHART_WITH_INSIGHT = "chart_with_insight"
CHART_ANNOTATED   = "chart_with_annotation"

# QUOTE
QUOTE_CENTERED = "centered_quote"
QUOTE_SIDE     = "side_quote"
QUOTE_LARGE    = "large_typography"

# IMAGE_TEXT  (image pipeline not yet implemented — layout preserved as-is)
IMAGE_TEXT_SPLIT     = "image_split"
IMAGE_TEXT_OVERLAY   = "image_overlay"
IMAGE_TEXT_SIDEBAR   = "image_sidebar"

# CONCLUSION
CONCLUSION_STATEMENT    = "statement"
CONCLUSION_SUMMARY_CARDS = "summary_cards"
CONCLUSION_MINIMAL      = "minimal_final"

# ---------------------------------------------------------------------------
# Master mapping: SlideLayout → ordered list of variant names
# ---------------------------------------------------------------------------

LAYOUT_VARIANTS: Dict[SlideLayout, List[str]] = {
    SlideLayout.TITLE: [
        TITLE_HERO_CENTER,
        TITLE_HERO_LEFT,
        TITLE_HERO_BAND,
    ],
    SlideLayout.TITLE_TEXT: [
        TITLE_TEXT_EDITORIAL,
        TITLE_TEXT_CLEAN,
        TITLE_TEXT_LARGE_STATEMENT,
    ],
    SlideLayout.STATISTICS: [
        STATS_THREE_CARDS,
        STATS_BIG_NUMBER,
        STATS_HORIZONTAL_METRICS,
    ],
    SlideLayout.TWO_COLUMNS: [
        TWO_COL_EQUAL,
        TWO_COL_ASYMMETRIC,
        TWO_COL_TEXT_EMPH,
    ],
    SlideLayout.COMPARISON: [
        CMP_SPLIT_SCREEN,
        CMP_CARD_COMPARISON,
        CMP_VERTICAL,
    ],
    SlideLayout.TIMELINE: [
        TIMELINE_HORIZONTAL,
        TIMELINE_VERTICAL,
        TIMELINE_MILESTONE,
    ],
    SlideLayout.CHART: [
        CHART_FOCUS,
        CHART_WITH_INSIGHT,
        CHART_ANNOTATED,
    ],
    SlideLayout.QUOTE: [
        QUOTE_CENTERED,
        QUOTE_SIDE,
        QUOTE_LARGE,
    ],
    SlideLayout.IMAGE_TEXT: [
        IMAGE_TEXT_SPLIT,
        IMAGE_TEXT_OVERLAY,
        IMAGE_TEXT_SIDEBAR,
    ],
    SlideLayout.CONCLUSION: [
        CONCLUSION_STATEMENT,
        CONCLUSION_SUMMARY_CARDS,
        CONCLUSION_MINIMAL,
    ],
}


def get_variants(layout: SlideLayout) -> List[str]:
    """Return the list of variants for *layout*. Never raises — returns ['default'] as fallback."""
    return LAYOUT_VARIANTS.get(layout, ["default"])


# ---------------------------------------------------------------------------
# VariantSelector — controlled, stateful variety
# ---------------------------------------------------------------------------

@dataclass
class VariantSelector:
    """
    Picks variants for slides in a single presentation.

    Rules enforced:
    - The same variant is never repeated consecutively for the same layout.
    - We prefer not to reuse a variant that has already appeared for this layout
      (exhausts the pool before repeating).
    - Randomness is only used to choose among valid candidates.
    """

    # Maps layout → variant used on the most recent slide of that layout
    _last_variant: Dict[SlideLayout, str] = field(default_factory=dict)

    # Maps layout → set of variants already used in this presentation
    _used_variants: Dict[SlideLayout, List[str]] = field(default_factory=dict)

    def pick(self, layout: SlideLayout) -> str:
        """Return the next variant for *layout*, respecting anti-repetition rules."""
        variants = get_variants(layout)

        if len(variants) == 1:
            # No choice available — return the only option
            self._last_variant[layout] = variants[0]
            return variants[0]

        last = self._last_variant.get(layout)
        used = self._used_variants.get(layout, [])

        # Priority 1: unused variants (excluding last used)
        fresh = [v for v in variants if v not in used and v != last]

        # Priority 2: all variants except the last (pool exhausted)
        if not fresh:
            fresh = [v for v in variants if v != last]

        # Priority 3: safety fallback (should never reach, only 1 variant)
        if not fresh:
            fresh = variants

        chosen = random.choice(fresh)

        # Update state
        self._last_variant[layout] = chosen
        pool = self._used_variants.setdefault(layout, [])
        pool.append(chosen)

        # Reset pool when all variants have been used (allow recycling)
        if set(pool) >= set(variants):
            self._used_variants[layout] = [chosen]

        return chosen

    def reset(self) -> None:
        """Clear all state (start fresh for a new presentation)."""
        self._last_variant.clear()
        self._used_variants.clear()
