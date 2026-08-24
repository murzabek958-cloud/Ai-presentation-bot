import html
import logging
from pathlib import Path
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from ai.planner import PresentationPlanner, PlannerError
from ai.requirements_extractor import RequirementsExtractor, ExtractionError
from ai.schemas import PresentationPlan, PresentationRequirements, SlideLayout
from ai.validator import RequirementsValidator
from ai.design_intent import parse_design_intent, DesignIntent
from ai.design_intelligence import DesignIntelligence
from ai.slide_design_schema import PresentationDesignPlan
from ai.visual_design_planner import VisualDesignPlanner, VisualDesignSpec
from ai.visual_spec_bridge import visual_spec_to_design_plan
from config.settings import settings
from presentation.renderer import PresentationRenderer, RendererError
from images.pipeline import ImagePipeline
from images.intent import ImageIntent
from images.asset_pipeline import ImageAssetPipeline, AssetResolutionResult

logger = logging.getLogger(__name__)
router = Router()

_planner = PresentationPlanner()
_extractor = RequirementsExtractor()
_validator = RequirementsValidator()
_design_intelligence = DesignIntelligence()
_visual_design_planner = VisualDesignPlanner()

MIN_TOPIC_LEN = 3


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Сәлем! Мен презентация жасаушы бот.\n\n"
        "Маған тақырыпты жіберсеңіз, AI арқылы слайдтар жоспарын дайындаймын.\n\n"
        "📌 Мысал:\n"
        "<code>Жасанды интеллект және болашақ</code>\n\n"
        "Қолданылуы: /help ",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📖 <b>Қалай қолдану керек:</b>\n\n"
        "1. Презентация тақырыбын қазақ, орыс немесе ағылшын тілінде жіберіңіз.\n"
        "2. Бот AI арқылы слайдтар жоспарын жасайды.\n"
        "3. Жоспар дайын болған соң сізге жіберіледі.\n\n"
        "⚠️ Тақырып кемінде 3 таңба болуы керек.\n\n"
        "📌 Мысалдар:\n"
        "<code>Климаттың өзгеруі</code>\n"
        "<code>Python программалау тілі</code>\n"
        "<code>Маркетинг стратегиялары</code> ",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Topic message handler
# ---------------------------------------------------------------------------
@router.message(F.text)
async def handle_topic(message: Message) -> None:
    topic = (message.text or "").strip()

    # --- Validation ---
    if not topic:
        await message.answer("⚠️ Тақырыпты жазып жіберіңіз.")
        return
    if len(topic) < MIN_TOPIC_LEN:
        await message.answer(
            f"⚠️ Тақырып тым қысқа. Кемінде {MIN_TOPIC_LEN} таңба болуы керек."
        )
        return

    # --- Step 1: Extract requirements ---
    await message.answer(
        f"⏳ <b>«{html.escape(topic)}»</b> — талаптар анықталуда…",
        parse_mode="HTML",
    )
    try:
        reqs: PresentationRequirements = await _extractor.extract(topic)
    except ExtractionError as exc:
        logger.warning("ExtractionError for topic=%r: %s — using defaults", topic, exc)
        reqs = PresentationRequirements()   # fall back to all-defaults, don't fail user

    # --- Step 1b: Extract DesignIntent from raw user message ---
    # parse_design_intent() is deterministic (no LLM call) — always safe.
    # The result travels through the pipeline so explicit user color/font
    # preferences are never lost or overridden by topic-aware logic.
    design_intent: DesignIntent = parse_design_intent(topic)
    if not design_intent.is_empty():
        logger.info(
            "DesignIntent extracted for topic=%r: %s",
            topic,
            design_intent,
        )
    # Store on reqs so it survives to renderer (Phase 2 contract)
    reqs.design_intent = design_intent if not design_intent.is_empty() else None

    # --- Step 2: Build generation kwargs from all extracted requirements ---
    gen_kwargs: dict = {}
    if reqs.slide_count is not None:
        gen_kwargs["slide_count"] = reqs.slide_count
    if reqs.language is not None:
        gen_kwargs["language"] = reqs.language
    if reqs.style is not None:
        gen_kwargs["style"] = reqs.style

    # Boolean/string requirements — always pass so planner prompt reflects them
    gen_kwargs["require_conclusion"] = reqs.require_conclusion
    gen_kwargs["require_statistics"] = reqs.require_statistics
    gen_kwargs["require_sources"] = reqs.require_sources
    gen_kwargs["include_images"] = reqs.include_images
    gen_kwargs["max_text_per_slide"] = reqs.max_text_per_slide
    gen_kwargs["extra_instructions"] = reqs.extra_instructions

    await message.answer(
        "⚙️ Презентация жоспары жасалуда…\n"
        "Бірнеше секунд күтіңіз.",
        parse_mode="HTML",
    )
    try:
        plan: PresentationPlan = await _planner.generate(topic=topic, **gen_kwargs)
    except PlannerError as exc:
        logger.error("PlannerError for topic=%r: %s", topic, exc)
        await message.answer(
            "❌ AI жауап бере алмады. Сәл кейінірек қайталап көріңіз."
        )
        return
    except Exception as exc:
        logger.exception("Unexpected error during plan generation for topic=%r", topic)
        await message.answer(
            "❌ Күтпеген қате болды. Сәл кейінірек қайталап көріңіз."
        )
        return

    # --- Step 3: Validate plan against requirements ---
    validation = _validator.validate(plan, reqs)
    if not validation.passed:
        logger.warning(
            "Plan failed requirement validation for topic=%r:\n%s",
            topic,
            validation.summary(),
        )
        error_text = html.escape(validation.summary())
        await message.answer(
            f"⚠️ <b>Жоспар талаптарға сәйкес келмеді:</b>\n\n{error_text}\n\n"
            "Қайтадан жіберіп көріңіз немесе талаптарды нақтылаңыз.",
            parse_mode="HTML",
        )
        return

    # --- Step 4: Format and send summary ---
    summary = _format_plan_summary(plan, reqs)
    try:
        await message.answer(summary, parse_mode="HTML")
    except Exception as exc:
        logger.error("Failed to send plan summary: %s", exc)
        await message.answer("❌ Жоспар жіберілмеді. Қайталап көріңіз.")

    # --- Step 5: Render PPTX and send as file ---
    await message.answer("📊 Презентация файлы жасалуда…")
    output_path = _build_output_path(
        user_id=message.from_user.id if message.from_user else 0,
        message_id=message.message_id,
    )

    # --- Fetch images if required ---
    image_paths = {}
    if reqs.include_images:
        try:
            pipeline = ImagePipeline()
            image_paths = await _fetch_image_paths_for_slides(plan.slides, plan.topic, pipeline)
        except Exception as e:
            logger.warning(f"Image fetching pipeline failed: {e}")

    # --- Step 5b: Gemini Visual Design Planner (Creative Director) ---
    # VisualDesignPlanner asks Gemini to design every slide's visual layout:
    # coordinates, sizes, colors, fonts, backgrounds, and asset prompts.
    # plan_sync() NEVER raises — returns safe defaults on any failure.
    visual_spec: VisualDesignSpec = await _visual_design_planner.plan(
        plan=plan,
        design_intent=reqs.design_intent,
    )
    logger.info(
        "VisualDesignPlanner completed: topic=%r slides=%d "
        "gemini=%s fallback=%s direction=%r",
        topic,
        len(visual_spec.slides),
        visual_spec.generated_by_gemini,
        visual_spec.fallback_used,
        visual_spec.presentation.visual_direction[:80]
        if visual_spec.presentation.visual_direction else "",
    )

    # --- Step 5c: Visual asset generation ---
    # ImageAssetPipeline resolves all assets defined in visual_spec.
    # Per-asset fallback: generated → cache → solid color placeholder.
    # ONE asset failure never stops the pipeline.
    asset_result: AssetResolutionResult = await _resolve_visual_assets(visual_spec)

    # Merge resolved visual assets into image_paths (IMAGE_TEXT slides only).
    # SpecRenderer.inject_assets() is non-destructive: never overwrites existing paths.
    try:
        from presentation.spec_renderer import SpecRenderer
        image_paths = SpecRenderer(
            visual_spec=visual_spec,
            resolved_assets=asset_result.resolved,
        ).inject_assets(plan.slides, image_paths)
    except Exception as _sr_exc:
        logger.error("SpecRenderer.inject_assets failed (non-fatal): %s", _sr_exc)

    # --- Step 5d: Gemini Design Intelligence (archetype dispatch layer) ---
    # DesignIntelligence receives image_index so it knows which slides have
    # real images. analyse() NEVER raises — returns safe defaults on failure.
    image_index: set[int] = set(image_paths.keys())
    design_plan: PresentationDesignPlan = await _design_intelligence.analyse(
        plan=plan,
        design_intent=reqs.design_intent,
        image_index=image_index,
    )
    logger.info(
        "DesignIntelligence completed: topic=%r directives=%d rationale=%r",
        topic,
        len(design_plan.directives),
        design_plan.design_rationale[:80] if design_plan.design_rationale else "",
    )

    # --- Step 5e: Merge VisualDesignSpec → PresentationDesignPlan ---
    # visual_spec (Gemini Creative Director) мазмұнын design_plan-ға merge жасайды:
    #   composition_type  → archetype        (CompositionSelector → layout handler)
    #   background.color  → background_override   (builder.prepare_slide → bg)
    #   elements.alignment→ text_alignment
    #   elements.width    → title_width_ratio
    #   margin_top        → spacing
    #   heading_font/body → global_font_heading/body
    # Priority: USER CONSTRAINT > visual_spec > design_plan > renderer defaults
    try:
        design_plan = visual_spec_to_design_plan(
            visual_spec=visual_spec,
            plan=plan,
            existing_design_plan=design_plan,
        )
        logger.info(
            "visual_spec_bridge: merged → design_plan directives=%d "
            "font_heading=%r font_body=%r",
            len(design_plan.directives),
            design_plan.global_font_heading,
            design_plan.global_font_body,
        )
    except Exception as _bridge_exc:
        logger.error(
            "visual_spec_bridge failed (non-fatal): %s — "
            "continuing with DesignIntelligence plan only",
            _bridge_exc,
        )
    logger.info(
        "Composition rendering started: topic=%r slides=%d",
        topic,
        len(plan.slides),
    )
    try:
        renderer = PresentationRenderer(
            plan,
            style_is_explicit=reqs.style is not None,
            design_intent=reqs.design_intent,
            design_plan=design_plan,
        )
        renderer.render(image_paths=image_paths)
        renderer.save(str(output_path))
        logger.info("Presentation rendering completed: topic=%r path=%s", topic, output_path)
    except RendererError as exc:
        logger.error(
            "RendererError for topic=%r user_id=%s: %s",
            topic,
            message.from_user.id if message.from_user else "unknown",
            exc,
        )
        await message.answer(
            "❌ Презентация файлын жасау кезінде қате болды. "
            "Жоспар жоғарыда жіберілді — кейінірек қайталаңыз."
        )
        return
    except Exception as exc:
        logger.exception(
            "Unexpected error during PPTX rendering for topic=%r user_id=%s",
            topic,
            message.from_user.id if message.from_user else "unknown",
        )
        await message.answer(
            "❌ Күтпеген қате болды. Жоспар жоғарыда жіберілді."
        )
        return

    try:
        pptx_file = FSInputFile(str(output_path), filename=output_path.name)
        await message.answer_document(
            pptx_file,
            caption="✅ Презентация дайын!",
        )
    except Exception as exc:
        logger.error(
            "Failed to upload PPTX to Telegram for topic=%r user_id=%s: %s",
            topic,
            message.from_user.id if message.from_user else "unknown",
            exc,
        )
        await message.answer(
            "❌ Файлды Telegram-ға жіберу кезінде қате болды. "
            "Жоспар жоғарыда жіберілді — кейінірек қайталаңыз."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _build_output_path(user_id: int, message_id: int) -> Path:
    """
    Return a unique Path for the output PPTX file.
    Pattern: <output_dir>/presentation<user_id>_<message_id>.pptx
    The parent directory is created if it does not exist.
    """
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"presentation_{user_id}_{message_id}.pptx"
    return output_dir / filename


def _format_plan_summary(
    plan: PresentationPlan,
    reqs: PresentationRequirements | None = None,
) -> str:
    """Return a short HTML summary of PresentationPlan for the user."""
    usage = plan.metadata.token_usage
    tokens_line = (
        f"🔢 Токендер: {usage.total_tokens}"
        if usage and usage.total_tokens
        else ""
    )

    slides_text = "\n".join(
        f"  {slide.index + 1}. [{html.escape(slide.layout.value)}] {html.escape(slide.title)}"
        for slide in plan.slides
    )

    parts = [
        "✅ <b>Жоспар дайын!</b>",
        "",
        f"📋 <b>Тақырып:</b> {html.escape(plan.topic)}",
        f"🎨 <b>Стиль:</b> {html.escape(plan.style)}",
        f"📊 <b>Слайдтар саны:</b> {plan.slide_count}",
        f"🌐 <b>Тіл:</b> {html.escape(plan.metadata.language)}",
    ]

    # Show which requirements were detected
    if reqs is not None:
        req_flags: list[str] = []
        if reqs.require_conclusion:
            req_flags.append("қорытынды")
        if reqs.require_statistics:
            req_flags.append("статистика")
        if reqs.require_sources:
            req_flags.append("дереккөздер")
        if not reqs.include_images:
            req_flags.append("сурет жоқ")
        if reqs.max_text_per_slide:
            req_flags.append("мәтін аз")
        if req_flags:
            parts.append(f"✔️ <b>Талаптар:</b> {html.escape(', '.join(req_flags))}")

    if tokens_line:
        parts.append(tokens_line)

    parts += [
        "",
        "<b>Слайдтар:</b>",
        f"<code>{slides_text}</code>",
    ]

    return "\n".join(parts)


async def _fetch_image_paths_for_slides(slides, topic: str, pipeline) -> dict[int, str]:
    """
    Resolve local image paths only for IMAGE_TEXT slides that have an image_query.

    The PPTXBuilder embeds pictures exclusively for SlideLayout.IMAGE_TEXT.
    Fetching for any other layout would waste network/IO and the path would
    be silently discarded.  Therefore we:
      1. Ignore (and clear) image_query on non-IMAGE_TEXT slides.
      2. Call the pipeline only for genuine IMAGE_TEXT slides.

    Returns: {slide.index: str(image_path)}
    """
    image_paths: dict[int, str] = {}
    for slide in slides:
        if not slide.image_query:
            continue

        # Defensive: AI may still attach image_query to wrong layouts despite prompt.
        if slide.layout != SlideLayout.IMAGE_TEXT:
            logger.warning(
                "Ignoring image_query on non-IMAGE_TEXT slide index=%d layout=%s query=%r",
                slide.index,
                slide.layout.value,
                slide.image_query[:60] if slide.image_query else "",
            )
            slide.image_query = None
            continue

        try:
            intent = ImageIntent.from_query(slide.image_query)
            image_path = await pipeline.resolve(intent=intent, topic=topic)
            if image_path:
                image_paths[slide.index] = str(image_path)
                logger.info(
                    "Resolved image for IMAGE_TEXT slide index=%d → %s",
                    slide.index,
                    image_path,
                )
        except Exception as e:
            logger.warning(
                "Failed to fetch image for IMAGE_TEXT slide %d: %s",
                slide.index,
                e,
            )
            continue
    return image_paths


async def _resolve_visual_assets(visual_spec: "VisualDesignSpec") -> "AssetResolutionResult":
    """
    Run ImageAssetPipeline on visual_spec assets.

    Per-asset fallback chain (inside ImageAssetPipeline):
      generated image → cache → solid-color placeholder

    ONE asset failure never stops the pipeline — always returns a result.
    """
    try:
        asset_pipeline = ImageAssetPipeline()
        return await asset_pipeline.resolve_all(visual_spec)
    except Exception as exc:
        logger.error(
            "_resolve_visual_assets: unexpected error — returning empty result: %s", exc
        )
        from images.asset_pipeline import AssetResolutionResult
        return AssetResolutionResult()


def _merge_asset_paths(
    slides,
    visual_spec: "VisualDesignSpec",
    asset_result: "AssetResolutionResult",
    existing_image_paths: dict[int, str],
) -> dict[int, str]:
    """
    Merge resolved visual assets into existing image_paths for IMAGE_TEXT slides.

    For each IMAGE_TEXT slide that has no image_path yet, check if
    visual_spec has a hero_visual or illustration asset for that slide
    that was successfully resolved by ImageAssetPipeline.

    Non-IMAGE_TEXT slide assets (backgrounds, decorations) are intentionally
    NOT merged here — they remain in visual_spec for the composition engine.

    Returns updated image_paths dict.
    """
    merged = dict(existing_image_paths)

    # Build a lookup: slide_index → list of resolved asset paths for that slide
    spec_slides = getattr(visual_spec, "slides", [])
    for slide_spec in spec_slides:
        slide_index = getattr(slide_spec, "slide_index", None)
        if slide_index is None:
            continue

        # Only inject into IMAGE_TEXT slides that have no image yet
        matching_slide = next(
            (s for s in slides if s.index == slide_index
             and s.layout == SlideLayout.IMAGE_TEXT),
            None,
        )
        if matching_slide is None:
            continue
        if slide_index in merged:
            continue  # already has an image from _fetch_image_paths_for_slides

        # Look for a content/hero asset for this slide
        for asset in getattr(slide_spec, "assets", []):
            asset_id = getattr(asset, "id", None)
            purpose = getattr(asset, "purpose", "")
            if purpose in ("hero_visual", "illustration", "content") and asset_id:
                resolved_path = asset_result.resolved.get(asset_id)
                if resolved_path is not None:
                    merged[slide_index] = str(resolved_path)
                    logger.info(
                        "_merge_asset_paths: injected asset %r → IMAGE_TEXT slide %d",
                        asset_id,
                        slide_index,
                    )
                    break  # one image per slide

    return merged
