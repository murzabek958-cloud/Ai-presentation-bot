from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ai.design_intent import DesignIntent


class SlideLayout(str, Enum):
    TITLE = "title"
    TITLE_TEXT = "title_text"
    IMAGE_TEXT = "image_text"
    TWO_COLUMNS = "two_columns"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    STATISTICS = "statistics"
    CHART = "chart"
    QUOTE = "quote"
    CONCLUSION = "conclusion"
    AGENDA = "agenda"


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class PlanMetadata(BaseModel):
    language: str = Field(..., pattern="^(kk|ru|en)$")
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    # Filled by backend after API call — not required from AI output
    token_usage: TokenUsage | None = None


class SlideData(BaseModel):
    index: int = Field(..., ge=0)
    layout: SlideLayout
    title: str = Field(..., min_length=1)
    content: dict[str, Any] = Field(default_factory=dict)
    image_query: str | None = None
    speaker_notes: str | None = None


class PresentationRequirements(BaseModel):
    """
    Extracted from the user's natural-language request.
    All fields are optional — only explicitly requested constraints are set.
    """
    slide_count: int | None = Field(None, ge=1, le=50)
    language: str | None = Field(None, pattern="^(kk|ru|en)$")
    style: str | None = Field(None, pattern="^(academic|modern|minimal)$")

    require_conclusion: bool = False
    require_statistics: bool = False
    require_sources: bool = False

    include_images: bool = True
    max_text_per_slide: bool = False

    extra_instructions: str = ""

    # Phase 2: explicit user design preferences.
    # None means no design preferences were stated — behavior unchanged.
    design_intent: DesignIntent | None = None

    class Config:
        arbitrary_types_allowed = True  # DesignIntent is a plain dataclass


class PresentationPlan(BaseModel):
    topic: str = Field(..., min_length=1)
    style: str = Field(..., pattern="^(academic|modern|minimal)$")
    slide_count: int = Field(..., ge=1)
    slides: list[SlideData] = Field(..., min_length=1)
    metadata: PlanMetadata

    @model_validator(mode="after")
    def validate_slides(self) -> PresentationPlan:
        if len(self.slides) != self.slide_count:
            raise ValueError(
                f"slide_count={self.slide_count} but got {len(self.slides)} slides"
            )

        indices = [s.index for s in self.slides]
        expected = list(range(len(self.slides)))
        if indices != expected:
            raise ValueError(
                f"Slide indices must be consecutive starting from 0, got {indices}"
            )

        return self
