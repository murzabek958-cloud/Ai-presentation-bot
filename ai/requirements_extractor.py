"""
Extract structured PresentationRequirements from a free-form user message.

The extractor calls Gemini once with a focused prompt and returns a
PresentationRequirements object.  No PPTX logic here.
"""
import logging

from google import genai
from google.genai import types

from config.settings import settings
from ai.schemas import PresentationRequirements

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are a requirement parser for a presentation generator bot.

The user may write in Kazakh, Russian, or English.
Your job is to extract ONLY explicit requirements from the message.
Do NOT infer or assume requirements that are not stated.

Return a single JSON object with these fields (all optional — use null if not stated):
{
  "slide_count":        integer or null,
  "language":           "kk" | "ru" | "en" | null,
  "style":              "academic" | "modern" | "minimal" | null,
  "require_conclusion": true | false,
  "require_statistics": true | false,
  "require_sources":    true | false,
  "include_images":     true | false,
  "max_text_per_slide": true | false,
  "extra_instructions": string (any other explicit user instruction, or "")
}

Language detection rules:
- "қазақша", "қазақ тілінде", "на казахском"     → "kk"
- "орысша", "орыс тілінде", "на русском"          → "ru"
- "english", "in english", "английский"            → "en"

Style detection rules:
- "академиялық", "академический", "academic"       → "academic"
- "заманауи", "современный", "modern"              → "modern"
- "минималды", "минималистичный", "minimal"        → "minimal"

Slide count detection:
- "8 слайд", "10 слайдтан тұрсын", "5 slide", "сделай 12 слайдов" → integer

Other rules:
- "қорытынды болсын", "заключение", "conclusion"   → require_conclusion = true
- "статистика", "деректер", "данные", "statistics" → require_statistics = true
- "дереккөздер", "источники", "sources"            → require_sources = true
- "сурет қоспа", "без картинок", "no images"       → include_images = false
- "мәтін аз", "текста мало", "less text"           → max_text_per_slide = true

Return ONLY the JSON object, no markdown, no extra text.
"""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class ExtractionError(Exception):
    """Raised when requirement extraction fails."""


class RequirementsExtractor:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    async def extract(self, user_message: str) -> PresentationRequirements:
        """
        Parse user_message and return PresentationRequirements.
        Unknown/unmentioned fields are left at their defaults.
        """
        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
            response_schema=PresentationRequirements,
            temperature=0.0,   # deterministic — this is parsing, not creativity
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_message,
                config=config,
            )
        except Exception as exc:
            raise ExtractionError(f"Gemini extraction call failed: {exc}") from exc

        if response.parsed is not None:
            reqs: PresentationRequirements = response.parsed
        else:
            raw = response.text or ""
            if not raw:
                raise ExtractionError("Empty response from Gemini during extraction.")
            try:
                reqs = PresentationRequirements.model_validate_json(raw)
            except Exception as exc:
                raise ExtractionError(f"Failed to parse extraction response: {exc}") from exc

        if settings.debug:
            logger.debug("Extracted requirements: %s", reqs.model_dump(exclude_none=True))

        return reqs
