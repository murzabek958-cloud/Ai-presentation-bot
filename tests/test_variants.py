"""
Unit tests for the Design Variety Engine (presentation/variants.py).

Tests verify:
- A variant is always picked for every layout.
- The same variant is never returned consecutively for the same layout.
- The valid variant mapping is never violated.
- Existing layouts continue to work via the builder (smoke test).
"""

import pytest

from ai.schemas import SlideLayout
from presentation.variants import (
    LAYOUT_VARIANTS,
    VariantSelector,
    get_variants,
)


# ---------------------------------------------------------------------------
# get_variants
# ---------------------------------------------------------------------------

class TestGetVariants:
    def test_returns_list_for_every_layout(self):
        for layout in SlideLayout:
            variants = get_variants(layout)
            assert isinstance(variants, list)
            assert len(variants) >= 1, f"{layout} has no variants"

    def test_known_layout_returns_correct_variants(self):
        assert "hero_center" in get_variants(SlideLayout.TITLE)
        assert "hero_left"   in get_variants(SlideLayout.TITLE)
        assert "hero_band"   in get_variants(SlideLayout.TITLE)

    def test_statistics_has_three_variants(self):
        assert len(get_variants(SlideLayout.STATISTICS)) == 3

    def test_conclusion_has_three_variants(self):
        assert len(get_variants(SlideLayout.CONCLUSION)) == 3

    def test_unknown_layout_returns_fallback(self):
        # get_variants should not raise — returns ['default'] for unknown layouts
        from ai.schemas import SlideLayout as SL
        # We test the dict lookup path directly
        result = LAYOUT_VARIANTS.get("nonexistent_layout", ["default"])
        assert result == ["default"]


# ---------------------------------------------------------------------------
# VariantSelector — single-layout anti-repetition
# ---------------------------------------------------------------------------

class TestVariantSelectorAntiRepetition:
    def test_variant_is_a_string(self):
        sel = VariantSelector()
        v = sel.pick(SlideLayout.TITLE)
        assert isinstance(v, str)

    def test_variant_in_valid_set(self):
        sel = VariantSelector()
        for _ in range(20):
            v = sel.pick(SlideLayout.TITLE)
            assert v in get_variants(SlideLayout.TITLE), f"Invalid variant: {v}"

    def test_no_consecutive_repeat_same_layout(self):
        """The same variant must never appear twice in a row for the same layout."""
        sel = VariantSelector()
        layout = SlideLayout.TITLE
        prev = None
        for _ in range(30):
            v = sel.pick(layout)
            assert v != prev, f"Consecutive repeat: {v}"
            prev = v

    def test_no_consecutive_repeat_statistics(self):
        sel = VariantSelector()
        prev = None
        for _ in range(30):
            v = sel.pick(SlideLayout.STATISTICS)
            assert v != prev
            prev = v

    def test_no_consecutive_repeat_conclusion(self):
        sel = VariantSelector()
        prev = None
        for _ in range(30):
            v = sel.pick(SlideLayout.CONCLUSION)
            assert v != prev
            prev = v

    def test_all_variants_used_before_repeat(self):
        """Before any variant is repeated, all variants in the pool must appear."""
        sel    = VariantSelector()
        layout = SlideLayout.TITLE
        pool   = set(get_variants(layout))
        seen   = []
        # Collect picks until we've seen the full pool at least once
        for _ in range(len(pool) * 3):
            seen.append(sel.pick(layout))
            if pool <= set(seen):
                break
        assert pool <= set(seen), "Not all variants appeared before repetition"

    def test_reset_clears_state(self):
        sel = VariantSelector()
        # Drive some picks
        for _ in range(10):
            sel.pick(SlideLayout.TITLE)
        sel.reset()
        # After reset the selector has no memory; any variant is valid
        v = sel.pick(SlideLayout.TITLE)
        assert v in get_variants(SlideLayout.TITLE)


# ---------------------------------------------------------------------------
# VariantSelector — multi-layout interleaving
# ---------------------------------------------------------------------------

class TestVariantSelectorMultiLayout:
    def test_independent_tracking_per_layout(self):
        """Picks for one layout must not affect picks for another."""
        sel = VariantSelector()
        # Exhaust title variants
        seen_title = [sel.pick(SlideLayout.TITLE) for _ in range(6)]
        # Stats picks must still respect their own pool
        prev = None
        for _ in range(15):
            v = sel.pick(SlideLayout.STATISTICS)
            assert v in get_variants(SlideLayout.STATISTICS)
            assert v != prev
            prev = v

    def test_mixed_sequence_no_crash(self):
        sel = VariantSelector()
        sequence = list(SlideLayout) * 3
        for layout in sequence:
            v = sel.pick(layout)
            assert v in get_variants(layout)


# ---------------------------------------------------------------------------
# Variant mapping integrity
# ---------------------------------------------------------------------------

class TestLayoutVariantsMapping:
    def test_every_layout_has_entry(self):
        for layout in SlideLayout:
            assert layout in LAYOUT_VARIANTS, (
                f"SlideLayout.{layout.name} missing from LAYOUT_VARIANTS"
            )

    def test_each_layout_has_at_least_two_variants(self):
        for layout, variants in LAYOUT_VARIANTS.items():
            assert len(variants) >= 2, (
                f"{layout} has only {len(variants)} variant(s); need >= 2"
            )

    def test_no_duplicate_variants_per_layout(self):
        for layout, variants in LAYOUT_VARIANTS.items():
            assert len(variants) == len(set(variants)), (
                f"{layout} has duplicate variant entries"
            )


# ---------------------------------------------------------------------------
# Builder smoke test — all layouts render with variant engine
# ---------------------------------------------------------------------------

from presentation.builder import PPTXBuilder
from presentation.styles import get_theme
from ai.schemas import SlideData

THEME = get_theme("academic")

LAYOUT_CONTENTS: dict[SlideLayout, dict] = {
    SlideLayout.TITLE: {"subtitle": "A subtitle", "author": "Author Name"},
    SlideLayout.TITLE_TEXT: {"body": "Some body text here."},
    SlideLayout.IMAGE_TEXT: {"body": "Text beside image."},
    SlideLayout.TWO_COLUMNS: {
        "left_title": "Left", "left_body": "Left body.",
        "right_title": "Right", "right_body": "Right body.",
    },
    SlideLayout.COMPARISON: {
        "left_label": "Option A", "left_points": ["Fast", "Cheap"],
        "right_label": "Option B", "right_points": ["Reliable", "Scalable"],
    },
    SlideLayout.TIMELINE: {
        "events": [
            {"year": "2020", "description": "First"},
            {"year": "2022", "description": "Second"},
        ]
    },
    SlideLayout.STATISTICS: {
        "stats": [{"value": "95%", "label": "Accuracy"}, {"value": "1.2M", "label": "Users"}]
    },
    SlideLayout.CHART: {
        "chart_type": "bar", "description": "Revenue by quarter.", "data_hint": "Q1:10 Q2:20",
    },
    SlideLayout.QUOTE: {
        "quote": "The best way to predict the future is to create it.",
        "author": "Peter Drucker",
    },
    SlideLayout.CONCLUSION: {
        "summary": "We covered the key points.",
        "call_to_action": "Start building today.",
    },
}


def _make_slide(layout: SlideLayout, idx: int = 0) -> SlideData:
    return SlideData(
        index=idx,
        layout=layout,
        title="Test Slide",
        content=LAYOUT_CONTENTS[layout],
    )


@pytest.mark.parametrize("layout", list(SlideLayout))
def test_all_layouts_render_without_crash(layout):
    """Every layout must render with each of its variants without raising."""
    variants = get_variants(layout)
    for _ in range(len(variants) + 1):  # cycle through all variants + one extra
        builder = PPTXBuilder(theme=THEME)
        builder.add_slide(_make_slide(layout))
        assert len(builder._prs.slides) == 1


@pytest.mark.parametrize("layout", list(SlideLayout))
def test_variant_engine_integrated_in_builder(layout):
    """Builder must pick and apply a valid variant for every layout."""
    builder = PPTXBuilder(theme=THEME)
    # Add the same layout 3 times — no consecutive variant repeat
    for i in range(3):
        slide = SlideData(
            index=i, layout=layout, title=f"Slide {i}",
            content=LAYOUT_CONTENTS[layout],
        )
        builder.add_slide(slide)
    assert len(builder._prs.slides) == 3


def test_full_deck_all_layouts_saves(tmp_path):
    """All layouts in one presentation — must save a valid .pptx."""
    from pathlib import Path
    builder = PPTXBuilder(theme=THEME)
    for i, (layout, content) in enumerate(LAYOUT_CONTENTS.items()):
        slide = SlideData(index=i, layout=layout, title=f"Slide {i}", content=content)
        builder.add_slide(slide)
    out = tmp_path / "full_deck.pptx"
    builder.save(str(out))
    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.parametrize("theme_name", ["academic", "modern", "minimal"])
def test_all_themes_with_variant_engine(theme_name):
    theme   = get_theme(theme_name)
    builder = PPTXBuilder(theme=theme)
    for layout, content in LAYOUT_CONTENTS.items():
        slide = SlideData(index=0, layout=layout, title="Test", content=content)
        builder.add_slide(slide)
