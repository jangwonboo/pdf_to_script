"""Prompt package public exports."""

from prompts.slide_prompt import build_slide_prompt, split_script_header
from prompts.system_prompt import DEFAULT_SYSTEM_PROMPT

__all__ = ["DEFAULT_SYSTEM_PROMPT", "build_slide_prompt", "split_script_header"]
