from dataclasses import dataclass

from ai.schemas import SlideLayout


@dataclass(frozen=True)
class LayoutSpec:
    name: SlideLayout
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]


# ---------------------------------------------------------------------------
# Layout registry
# ---------------------------------------------------------------------------

_LAYOUTS: dict[SlideLayout, LayoutSpec] = {
    SlideLayout.TITLE: LayoutSpec(
        name=SlideLayout.TITLE,
        required_fields=("subtitle",),
        optional_fields=("author",),
    ),
    SlideLayout.TITLE_TEXT: LayoutSpec(
        name=SlideLayout.TITLE_TEXT,
        required_fields=("body",),
        optional_fields=(),
    ),
    SlideLayout.IMAGE_TEXT: LayoutSpec(
        name=SlideLayout.IMAGE_TEXT,
        required_fields=("body",),
        optional_fields=("image_query",),
    ),
    SlideLayout.TWO_COLUMNS: LayoutSpec(
        name=SlideLayout.TWO_COLUMNS,
        required_fields=("left_title", "left_body", "right_title", "right_body"),
        optional_fields=(),
    ),
    SlideLayout.COMPARISON: LayoutSpec(
        name=SlideLayout.COMPARISON,
        required_fields=("left_label", "left_points", "right_label", "right_points"),
        optional_fields=(),
    ),
    SlideLayout.TIMELINE: LayoutSpec(
        name=SlideLayout.TIMELINE,
        required_fields=("events",),
        optional_fields=(),
    ),
    SlideLayout.STATISTICS: LayoutSpec(
        name=SlideLayout.STATISTICS,
        required_fields=("stats",),
        optional_fields=(),
    ),
    SlideLayout.CHART: LayoutSpec(
        name=SlideLayout.CHART,
        required_fields=("chart_type", "description"),
        optional_fields=("data_hint",),
    ),
    SlideLayout.QUOTE: LayoutSpec(
        name=SlideLayout.QUOTE,
        required_fields=("quote", "author"),
        optional_fields=("source",),
    ),
    SlideLayout.CONCLUSION: LayoutSpec(
        name=SlideLayout.CONCLUSION,
        required_fields=("summary",),
        optional_fields=("call_to_action",),
    ),
    SlideLayout.AGENDA: LayoutSpec(
        name=SlideLayout.AGENDA,
        # items: list of {"number": str, "title": str, "subtitle": str}
        required_fields=("items",),
        optional_fields=(),
    ),
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_layout_spec(layout: SlideLayout) -> LayoutSpec:
    """Return the LayoutSpec for *layout*. Raises ValueError for unknown layouts."""
    try:
        return _LAYOUTS[layout]
    except KeyError:
        available = ", ".join(l.value for l in _LAYOUTS)
        raise ValueError(
            f"Unknown layout '{layout}'. Available layouts: {available}"
        )


def list_layouts() -> list[SlideLayout]:
    """Return all registered layouts."""
    return list(_LAYOUTS)


def is_layout_compatible(layout: SlideLayout, content: dict) -> bool:
    """
    Return True if *content* contains all required fields for *layout*.
    Does not validate field values — only checks key presence.
    """
    spec = get_layout_spec(layout)
    return all(field in content for field in spec.required_fields)
