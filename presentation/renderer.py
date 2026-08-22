import logging

from ai.schemas import PresentationPlan
from ai.design_intent import DesignIntent
from presentation.styles import Theme
from presentation.builder import PPTXBuilder
from presentation.layouts import get_layout_spec
from presentation.design_resolver import DesignResolver
from presentation.design_spec import DesignSpec

logger = logging.getLogger(__name__)

# Singleton resolver — stateless, safe to share across calls
_resolver = DesignResolver()


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

    If design_intent is None, behavior is identical to Phase 1.
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
    design_intent:
        Optional explicit design preferences (Phase 2).
        If provided and non-empty, overrides color/font values from style/topic.
        If None (default), behavior is identical to Phase 1.
    """

    def __init__(
        self,
        plan: PresentationPlan,
        style_is_explicit: bool = False,
        design_intent: DesignIntent | None = None,
    ) -> None:
        if not plan.slides:
            raise RendererError("PresentationPlan has no slides.")

        self._plan = plan
        self._style_is_explicit = style_is_explicit
        self._design_intent = design_intent
        self._theme: Theme = _resolve_theme(plan, style_is_explicit, design_intent)
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
