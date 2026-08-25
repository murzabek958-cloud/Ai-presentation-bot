import logging
from google import genai
from google.genai import types

from config.settings import settings
from ai.prompts import SYSTEM_PROMPT, build_user_prompt
from ai.schemas import PresentationPlan, TokenUsage

logger = logging.getLogger(__name__)


class PlannerError(Exception):
    """Raised when the planner fails to generate or validate a plan."""


class PresentationPlanner:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    async def generate(
        self,
        topic: str,
        slide_count: int = 8,
        language: str = "kk",
        style: str = "academic",
        require_conclusion: bool = False,
        require_statistics: bool = False,
        require_sources: bool = False,
        include_images: bool = True,
        max_text_per_slide: bool = False,
        extra_instructions: str = "",
    ) -> PresentationPlan:
        """
        Call Gemini API and return a validated PresentationPlan.
        Raises PlannerError on API or validation failure.
        """
        user_prompt = build_user_prompt(
            topic=topic,
            slide_count=slide_count,
            language=language,
            style=style,
            require_conclusion=require_conclusion,
            require_statistics=require_statistics,
            require_sources=require_sources,
            include_images=include_images,
            max_text_per_slide=max_text_per_slide,
            extra_instructions=extra_instructions,
        )

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.7,
        )

        try:
            response = self._client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=config,
            )
            response = await response
        except Exception as exc:
            raise PlannerError(f"Gemini API call failed: {exc}") from exc

        # --- Parse structured output ---
        plan: PresentationPlan | None = None

        if response.parsed is not None:
            # SDK validated and parsed directly into our Pydantic model
            plan = response.parsed
        else:
            # Fallback: parse from raw JSON text
            raw = response.text
            if not raw:
                raise PlannerError("Gemini returned an empty response.")
            try:
                plan = PresentationPlan.model_validate_json(raw)
            except Exception as exc:
                raise PlannerError(f"Failed to parse Gemini response: {exc}") from exc

        # --- Attach token usage from response metadata (best-effort) ---
        usage = response.usage_metadata
        if usage is not None:
            plan.metadata.token_usage = TokenUsage(
                prompt_tokens=usage.prompt_token_count or 0,
                completion_tokens=usage.candidates_token_count or 0,
                total_tokens=usage.total_token_count or 0,
            )

        if settings.debug:
            logger.debug(
                "Plan generated | topic=%s slides=%d tokens=%s",
                topic,
                slide_count,
                plan.metadata.token_usage,
            )

        return plan
