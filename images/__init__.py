"""
Auto Image Pipeline for AI Presentation Bot.

Pipeline: Slide Planner → Image needed? → Cache → Gemini generation → Fallback

Core rule: "Image is an enhancement, never a hard dependency."

Wikipedia / Wikimedia search has been removed.
Gemini image generation is the sole image source.
"""
