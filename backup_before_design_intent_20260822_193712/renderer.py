import logging

from ai.schemas import PresentationPlan
from presentation.styles import Theme, get_theme
from presentation.builder import PPTXBuilder
from presentation.layouts import get_layout_spec
from presentation.theme_selector import ThemeSelector

logger = logging.getLogger(__name__)

# Singleton — stateless, safe to share across calls
_theme_selector = ThemeSelector()

# Styles that are considered explicitly user-chosen (not pipeline defaults)
_EXPLICIT_STYLES = frozenset({"academic", "modern", "minimal"})


def _resolve_theme(plan: PresentationPlan, style_is_explicit: bool) -> Theme:
    """
    Theme priority rule:

    1. User explicitly chose a style → use that style's fixed Theme.
    2. No explicit style → use ThemeSelector based on plan.topic.
    3. ThemeSelector returns neutral (unknown topic) → fall back to 'academic'.

    The rule is implemented by checking *style_is_explicit*, not by inspecting
    the style string, so the logic is clear and easy to test.
    """
    if style_is_explicit:
        theme = get_theme(plan.style)
        logger.info(
            "Theme resolved: explicit style=%r → theme=%r (topic=%r)",
            plan.style, theme.name, plan.topic,
        )
        return theme

    # Automatic topic-aware selection
    theme, profile = _theme_selector.select_with_profile(plan.topic)
    logger.info(
        "Theme resolved: topic-aware | topic=%r → category=%r palette=%r "
        "confidence=%.2f primary=%s accent=%s",
        plan.topic,
        profile.primary_category,
        profile.palette_name,
        profile.confidence,
        theme.primary,
        theme.accent,
    )
    return theme


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
        Pass ``True`` when the user explicitly selected a style/theme.
        Pass ``False`` (default) to enable automatic topic-aware palette selection.
        Existing call sites that omit this argument continue to work unchanged,
        but will now receive a topic-aware palette instead of always 'academic'.

        In the Telegram bot, ``style_is_explicit=True`` is set when
        ``PresentationRequirements.style is not None``.
    """

    def __init__(
        self,
        plan: PresentationPlan,
        style_is_explicit: bool = False,
    ) -> None:
        if not plan.slides:
            raise RendererError("PresentationPlan has no slides.")

        self._plan = plan
        self._style_is_explicit = style_is_explicit
        self._theme: Theme = _resolve_theme(plan, style_is_explicit)
        self._builder: PPTXBuilder | None = None

    # ------------------------------------------------------------------
    # Public properties (useful for tests / inspection)
    # ------------------------------------------------------------------

    @property
    def theme(self) -> Theme:
        """The resolved Theme that will be (or was) used for rendering."""
        return self._theme

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(
        self,
        image_paths: dict[int, str] | None = None,
    ) -> PPTXBuilder:
        """
        Build the presentation from the plan.
        Calling render() a second time resets and rebuilds from scratch.

        Parameters
        ----------
        image_paths:
            Optional mapping of slide index -> local image file path.
            Slides not present in the mapping use the ``[ Image ]`` placeholder.
        """
        builder = PPTXBuilder(theme=self._theme)
        resolved = image_paths or {}

        for slide in self._plan.slides:
            # Validate layout spec exists (raises ValueError for unknown layout)
            spec = get_layout_spec(slide.layout)

            logger.debug(
                "Rendering slide index=%d layout=%s required_fields=%s",
                slide.index,
                slide.layout.value,
                spec.required_fields,
            )

            builder.add_slide(slide, image_path=resolved.get(slide.index))

        self._builder = builder
        logger.info(
            "Rendered %d slides (theme=%s palette_source=%s topic=%r)",
            len(self._plan.slides),
            self._theme.name,
            "explicit" if self._style_is_explicit else "topic-aware",
            self._plan.topic,
        )
        return builder

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, path: str) -> str:
        """
        Save the presentation to *path*.
        Calls render() automatically if not already rendered.
        """
        if self._builder is None:
            self.render()

        return self._builder.save(path)  # type: ignore[union-attr]
