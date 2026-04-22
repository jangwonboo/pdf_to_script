"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from generator import PresentationScriptGenerator
from logging_config import LOG_LEVELS, configure_logging


def _validate_ca_bundle_path(ca_bundle: str) -> str:
    """
    CA 번들 경로를 검증합니다.
    - 파일 존재 여부
    - PEM 인증서 형식 여부(-----BEGIN CERTIFICATE-----)
    """
    ca_path = Path(ca_bundle).expanduser().resolve()
    if not ca_path.exists():
        raise FileNotFoundError(f"CA bundle 파일을 찾을 수 없습니다: {ca_path}")

    text = ca_path.read_text(encoding="utf-8", errors="ignore")
    if "-----BEGIN CERTIFICATE-----" not in text:
        raise ValueError(
            "CA bundle 파일이 PEM 형식이 아닙니다. "
            "CER/DER 파일이면 PEM으로 변환 후 사용하세요. "
            "예: certutil -encode corp-ca.cer corp-ca.pem"
        )

    return str(ca_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDF 슬라이드 기반 발표 스크립트 생성기")
    parser.add_argument("pdf_path", help="입력 PDF 파일 경로")
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="출력 디렉터리 (미지정 시 output_<PDF파일명>)",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=None,
        help="처리 시작 페이지(1부터 시작, 포함)",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="처리 종료 페이지(포함)",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="로그 레벨 (기본값: INFO)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="로그 파일 경로 (예: ./logs/run.log)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="디버그 로그 출력 (log-level보다 우선)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="경고/에러만 출력 (log-level보다 우선)",
    )
    parser.add_argument(
        "--ca-bundle",
        default=None,
        help="사내 루트 인증서 PEM 경로 (SSL_CERT_FILE/REQUESTS_CA_BUNDLE에 적용)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="SSL 인증서 검증 비활성화(테스트/임시 용도)",
    )
    parser.add_argument(
        "--improve-with-claude",
        action="store_true",
        help="Gemini 생성본을 Claude로 재가공해 *_claude.md 추가 생성",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.insecure:
        os.environ["DISABLE_SSL_VERIFY"] = "1"
    if args.ca_bundle:
        ca_bundle_path = _validate_ca_bundle_path(args.ca_bundle)
        os.environ["SSL_CERT_FILE"] = ca_bundle_path
        os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle_path
    configure_logging(
        log_level=args.log_level,
        verbose=args.verbose,
        quiet=args.quiet,
        log_file=args.log_file,
    )
    generator = PresentationScriptGenerator()
    markdown_path = generator.process_presentation(
        args.pdf_path,
        output_dir=args.output_dir,
        start_page=args.start_page,
        end_page=args.end_page,
    )
    logging.getLogger(__name__).info("생성된 마크다운: %s", markdown_path)
    if args.improve_with_claude:
        claude_markdown_path = generator.improve_markdown_with_claude(markdown_path)
        logging.getLogger(__name__).info("Claude 개선 마크다운: %s", claude_markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
