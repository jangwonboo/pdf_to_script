"""Logging configuration utilities."""

from __future__ import annotations

import logging
from pathlib import Path

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def resolve_log_level(log_level: str, verbose: bool, quiet: bool) -> int:
    """CLI 옵션 조합으로 최종 로그 레벨을 계산합니다."""
    if verbose:
        return logging.DEBUG
    if quiet:
        return logging.WARNING
    return getattr(logging, log_level.upper(), logging.INFO)


def configure_logging(
    *,
    log_level: str = "INFO",
    verbose: bool = False,
    quiet: bool = False,
    log_file: str | None = None,
) -> None:
    """콘솔/파일 핸들러를 포함한 로깅을 설정합니다."""
    level = resolve_log_level(log_level=log_level, verbose=verbose, quiet=quiet)
    formatter = logging.Formatter(
        "%(levelname)s\t%(asctime)s\t%(name)s\t%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    # force=True로 기존 basicConfig를 덮어써 중복/무시 이슈를 방지합니다.
    logging.basicConfig(level=level, handlers=handlers, force=True)
