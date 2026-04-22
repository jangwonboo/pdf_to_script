"""Configuration objects for script generation."""

from dataclasses import dataclass

from prompts import DEFAULT_SYSTEM_PROMPT


@dataclass(frozen=True)
class GeneratorConfig:
    model_name: str = "gemini-2.5-flash"
    claude_model_name: str = "claude-3-5-sonnet-20241022"
    temperature: float = 0.2
    max_retries: int = 3
    retry_delay_sec: int = 3
    request_interval_sec: int = 2
    zoom: float = 2.0
    jpeg_quality: int = 90
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
