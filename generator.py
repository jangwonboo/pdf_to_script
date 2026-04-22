"""Core reusable generator logic."""

from __future__ import annotations

import logging
import os
import time
import json
import ssl
import base64
import mimetypes
import re
from pathlib import Path

import certifi
import fitz  # PyMuPDF
import urllib3
import anthropic
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

from config import GeneratorConfig
from prompts import build_slide_prompt, split_script_header

logger = logging.getLogger(__name__)


class PresentationScriptGenerator:
    def __init__(
        self,
        client: genai.Client | None = None,
        config: GeneratorConfig | None = None,
        api_key: str | None = None,
    ):
        self.config = config or GeneratorConfig()
        self.client = client or self._build_client(api_key)

    @staticmethod
    def _configure_ssl_certificates() -> None:
        """
        SSL 인증서 경로가 비어 있으면 certifi CA 번들을 기본값으로 설정합니다.
        회사/프록시 인증서가 필요하면 REQUESTS_CA_BUNDLE 또는 SSL_CERT_FILE을 직접 지정하세요.
        """
        requests_bundle = os.getenv("REQUESTS_CA_BUNDLE")
        ssl_cert_file = os.getenv("SSL_CERT_FILE")
        if requests_bundle or ssl_cert_file:
            logger.debug("Custom CA bundle already set by environment.")
            return

        ca_bundle = certifi.where()
        os.environ["SSL_CERT_FILE"] = ca_bundle
        os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
        logger.debug("Default CA bundle configured: %s", ca_bundle)

    @staticmethod
    def _configure_insecure_ssl_if_requested() -> None:
        """
        DISABLE_SSL_VERIFY=1일 때 SSL 검증을 비활성화합니다.
        테스트/임시 우회용이며 운영 환경 사용은 권장하지 않습니다.
        """
        disable_ssl = os.getenv("DISABLE_SSL_VERIFY", "").strip().lower() in {"1", "true", "yes"}
        if not disable_ssl:
            return

        ssl._create_default_https_context = ssl._create_unverified_context
        os.environ["PYTHONHTTPSVERIFY"] = "0"
        os.environ["CURL_CA_BUNDLE"] = ""
        os.environ["REQUESTS_CA_BUNDLE"] = ""
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("SSL certificate verification is DISABLED (DISABLE_SSL_VERIFY=1).")

    @staticmethod
    def _build_client(api_key: str | None = None) -> genai.Client:
        load_dotenv(override=True)
        PresentationScriptGenerator._configure_insecure_ssl_if_requested()
        PresentationScriptGenerator._configure_ssl_certificates()
        effective_api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if effective_api_key:
            logger.debug("Gemini client initialized with API key from %s", "arg" if api_key else "env")
            return genai.Client(api_key=effective_api_key)

        # API Key가 없으면 service_account.json(ADC + Vertex AI)로 fallback
        project_root = Path(__file__).resolve().parent
        service_account_path = project_root / "service_account.json"
        if service_account_path.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(service_account_path)
            project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
            if not project_id:
                with open(service_account_path, "r", encoding="utf-8") as fp:
                    service_account_info = json.load(fp)
                project_id = service_account_info.get("project_id")

            location = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-northeast3")
            if not project_id:
                raise ValueError("service_account.json에서 project_id를 찾을 수 없습니다.")

            logger.info("GOOGLE_API_KEY 미설정: service_account.json 기반 Vertex AI 인증 사용")
            logger.debug("Vertex AI config: project=%s, location=%s", project_id, location)
            return genai.Client(vertexai=True, project=project_id, location=location)

        raise ValueError(
            "GOOGLE_API_KEY 환경 변수가 없고 service_account.json도 찾지 못했습니다. "
            "GOOGLE_API_KEY를 설정하거나 프로젝트 루트에 service_account.json을 두세요."
        )

    @staticmethod
    def _resolve_page_range(total_pages: int, start_page: int | None, end_page: int | None) -> tuple[int, int]:
        start = 1 if start_page is None else start_page
        end = total_pages if end_page is None else end_page

        if start < 1:
            raise ValueError(f"start_page는 1 이상이어야 합니다: {start}")
        if end < 1:
            raise ValueError(f"end_page는 1 이상이어야 합니다: {end}")
        if start > total_pages:
            return total_pages + 1, total_pages
        if start > end:
            raise ValueError(f"start_page({start})가 end_page({end})보다 클 수 없습니다.")

        return start, min(end, total_pages)

    @staticmethod
    def _extract_last_completed_page(markdown_path: Path) -> int:
        """
        기존 마크다운에서 '---'로 닫힌(완료된) 마지막 페이지 번호를 반환합니다.
        완료된 페이지가 없으면 0을 반환합니다.
        """
        if not markdown_path.exists():
            return 0

        content = markdown_path.read_text(encoding="utf-8")
        if not content.strip():
            return 0

        last_completed_page = 0
        current_lines: list[str] = []
        for line in content.splitlines():
            if line.strip() == "---":
                page_num = PresentationScriptGenerator._extract_page_num_from_lines(current_lines)
                if page_num is not None:
                    last_completed_page = max(last_completed_page, page_num)
                current_lines = []
                continue
            current_lines.append(line)

        return last_completed_page

    @staticmethod
    def _extract_page_num_from_lines(lines: list[str]) -> int | None:
        for line in lines:
            matched = re.search(r"^####\s+Page\s+(\d+)", line.strip())
            if matched:
                return int(matched.group(1))
        return None

    def pdf_to_images(
        self,
        pdf_path: Path,
        output_dir: Path,
        start_page: int | None = None,
        end_page: int | None = None,
    ) -> list[tuple[int, Path]]:
        logger.info("PDF 파일 여는 중: %s", pdf_path.name)
        logger.debug("PDF to image config: zoom=%s, jpeg_quality=%s", self.config.zoom, self.config.jpeg_quality)
        image_paths: list[tuple[int, Path]] = []

        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            resolved_start, resolved_end = self._resolve_page_range(total_pages, start_page, end_page)
            if resolved_start > resolved_end:
                logger.info("요청한 범위에 처리할 페이지가 없습니다. (총 %s페이지)", total_pages)
                doc.close()
                return image_paths
            logger.info("처리 페이지 범위: %s-%s / 총 %s페이지", resolved_start, resolved_end, total_pages)

            for page_num in range(resolved_start, resolved_end + 1):
                page = doc.load_page(page_num - 1)
                mat = fitz.Matrix(self.config.zoom, self.config.zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)

                img_filename = f"slide_{page_num:02d}.jpg"
                img_path = output_dir / img_filename
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                img.save(img_path, "JPEG", quality=self.config.jpeg_quality)

                image_paths.append((page_num, img_path))
                logger.info("이미지 저장 완료: %s", img_filename)

            doc.close()
            return image_paths
        except Exception as exc:
            logger.error("PDF 변환 중 오류 발생: %s", exc)
            raise

    def generate_script_from_image(self, image_path: Path, page_num: int) -> str:
        logger.info("Gemini API 호출 중 (Slide %s)...", page_num)
        prompt = build_slide_prompt(page_num)

        try:
            image_part = self._build_image_part(image_path)
            for attempt in range(self.config.max_retries):
                try:
                    response = self.client.models.generate_content(
                        model=self.config.model_name,
                        contents=[image_part, prompt],
                        config=types.GenerateContentConfig(
                            system_instruction=self.config.system_prompt,
                            temperature=self.config.temperature,
                        ),
                    )
                    time.sleep(self.config.request_interval_sec)
                    return (response.text or "").strip()
                except Exception as exc:
                    error_text = str(exc)
                    if "SSLCertVerificationError" in error_text or "certificate verify failed" in error_text:
                        logger.error(
                            "SSL 인증서 검증 실패. '--ca-bundle <pem>' 또는 '--insecure' 옵션으로 실행해보세요."
                        )
                    if attempt < self.config.max_retries - 1:
                        logger.warning(
                            "API 호출 실패, %s초 후 재시도... (%s)",
                            self.config.retry_delay_sec,
                            exc,
                        )
                        logger.debug("API retry attempt %s/%s", attempt + 1, self.config.max_retries)
                        time.sleep(self.config.retry_delay_sec)
                    else:
                        raise
        except Exception as exc:
            logger.error("스크립트 생성 중 오류 발생: %s", exc)
            return f"#### Page {page_num} — [Error generating script]\n- [ ] 오류가 발생했습니다: {exc}"

    @staticmethod
    def _build_image_part(image_path: Path):
        """
        google-genai 버전 차이를 흡수하여 이미지 Part를 생성합니다.
        """
        if hasattr(types.Part, "from_image"):
            with Image.open(image_path) as img:
                return types.Part.from_image(img)

        if hasattr(types.Part, "from_bytes"):
            image_bytes = image_path.read_bytes()
            suffix = image_path.suffix.lower()
            mime_type = "image/png" if suffix == ".png" else "image/jpeg"
            return types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        raise RuntimeError(
            "현재 google-genai 버전에서 이미지 입력 API를 찾지 못했습니다. "
            "google-genai를 최신 버전으로 업그레이드하세요."
        )

    def process_presentation(
        self,
        pdf_path: str | Path,
        output_dir: str | Path | None = None,
        start_page: int | None = None,
        end_page: int | None = None,
    ) -> Path:
        input_pdf = Path(pdf_path)
        if not input_pdf.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {input_pdf}")

        base_name = input_pdf.stem
        final_output_dir = Path(output_dir) if output_dir else Path(f"./output_{base_name}")
        images_dir = final_output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = final_output_dir / f"{base_name}_gemini.md"

        logger.info("=== 프레젠테이션 처리 시작: %s ===", input_pdf.name)
        logger.debug("Output directory resolved: %s", final_output_dir)
        resume_from_page = self._extract_last_completed_page(markdown_path) + 1
        requested_start = 1 if start_page is None else start_page
        effective_start = max(requested_start, resume_from_page)
        if effective_start != requested_start:
            logger.info(
                "기존 진행 상태 감지: 마지막 완료 페이지=%s, %s페이지부터 이어서 생성",
                effective_start - 1,
                effective_start,
            )

        image_paths = self.pdf_to_images(
            input_pdf,
            images_dir,
            start_page=effective_start,
            end_page=end_page,
        )

        file_mode = "a" if markdown_path.exists() and resume_from_page > 1 else "w"
        with open(markdown_path, file_mode, encoding="utf-8") as md_file:
            if file_mode == "w":
                md_file.write(f"# Presentation Script: {base_name}\n\n")
            elif markdown_path.stat().st_size > 0:
                md_file.write("\n")

            for page_num, img_path in image_paths:
                rel_img_path = img_path.relative_to(final_output_dir)
                script_content = self.generate_script_from_image(img_path, page_num)
                header_line, script_body = split_script_header(script_content, page_num)

                md_file.write(f"{header_line}\n\n")
                md_file.write(f"![Slide {page_num}]({rel_img_path})\n\n")
                md_file.write(f"{script_body}\n\n")
                md_file.write("---\n\n")
                md_file.flush()
                os.fsync(md_file.fileno())
                logger.info("Slide %s 마크다운 작성 완료", page_num)

        if not image_paths:
            logger.info("새로 생성할 페이지가 없습니다. 기존 결과를 유지합니다.")

        logger.info("=== 모든 처리 완료! ===")
        logger.info("결과물 확인: %s", markdown_path)
        return markdown_path

    def improve_markdown_with_claude(self, gemini_markdown_path: str | Path) -> Path:
        """
        Gemini가 생성한 마크다운을 페이지 단위로 읽어 Claude로 개선해
        동일한 포맷의 *_claude.md 파일을 생성합니다.
        """
        markdown_path = Path(gemini_markdown_path)
        if not markdown_path.exists():
            raise FileNotFoundError(f"Gemini 마크다운 파일을 찾을 수 없습니다: {markdown_path}")

        load_dotenv(override=True)
        claude_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not claude_api_key:
            raise ValueError(
                "Claude 개선 옵션 사용 시 ANTHROPIC_API_KEY가 필요합니다. "
                ".env 또는 환경 변수에 설정하세요."
            )

        client = anthropic.Anthropic(api_key=claude_api_key)
        source_text = markdown_path.read_text(encoding="utf-8")
        title, sections = self._parse_markdown_sections(source_text)
        if not sections:
            raise ValueError(f"페이지 섹션을 파싱하지 못했습니다: {markdown_path}")

        claude_markdown_path = markdown_path.with_name(
            markdown_path.name.replace("_gemini.md", "_claude.md").replace("_script.md", "_claude.md")
        )
        if claude_markdown_path == markdown_path:
            claude_markdown_path = markdown_path.with_name(f"{markdown_path.stem}_claude.md")

        last_claude_page = self._extract_last_completed_page(claude_markdown_path)
        if last_claude_page > 0:
            logger.info(
                "기존 Claude 진행 상태 감지: 마지막 완료 페이지=%s, %s페이지부터 이어서 생성",
                last_claude_page,
                last_claude_page + 1,
            )

        pending_sections = [section for section in sections if int(section["page_num"]) > last_claude_page]
        if not pending_sections:
            logger.info("Claude 개선본도 새로 생성할 페이지가 없습니다. 기존 결과를 유지합니다.")
            return claude_markdown_path

        file_mode = "a" if claude_markdown_path.exists() and last_claude_page > 0 else "w"
        with open(claude_markdown_path, file_mode, encoding="utf-8") as out_file:
            if file_mode == "w" and title:
                out_file.write(f"{title}\n\n")
            elif file_mode == "a" and claude_markdown_path.stat().st_size > 0:
                out_file.write("\n")

            for section in pending_sections:
                resolved_image_path = (markdown_path.parent / str(section["image_path"])).resolve()
                section["resolved_image_path"] = str(resolved_image_path)
                improved_header, improved_body = self._improve_section_with_claude(client, section)
                out_file.write(f"{improved_header}\n\n")
                out_file.write(f"![Slide {section['page_num']}]({section['image_path']})\n\n")
                out_file.write(f"{improved_body}\n\n")
                out_file.write("---\n\n")
                out_file.flush()
                os.fsync(out_file.fileno())
                logger.info("Claude 개선 마크다운 작성 완료 (Slide %s)", section["page_num"])

        logger.info("Claude 개선 파일 생성 완료: %s", claude_markdown_path)
        return claude_markdown_path

    def _improve_section_with_claude(
        self, client: anthropic.Anthropic, section: dict[str, str | int]
    ) -> tuple[str, str]:
        image_path = Path(str(section["resolved_image_path"]))
        image_bytes = image_path.read_bytes()
        media_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        section_text = str(section["raw_text"])
        page_num = int(section["page_num"])
        claude_model = os.getenv("ANTHROPIC_MODEL", self.config.claude_model_name).strip()
        if not claude_model:
            raise ValueError("ANTHROPIC_MODEL이 비어 있습니다. 유효한 모델명을 지정하세요.")

        try:
            response = client.messages.create(
                model=claude_model,
                max_tokens=1800,
                temperature=self.config.temperature,
                system=(
                    "You are a senior executive speechwriter. Improve the script quality while preserving the same markdown "
                    "output structure. Keep the page header format (`#### Page N — ... (⏱ ~... min)`), keep hierarchical "
                    "bullet points, and do not use checkbox/task markers like [ ] or [] at the start of bullets. "
                    "Do not add commentary outside the markdown for this page."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Page number: {page_num}\n"
                                    "Below is the current markdown section for one slide. Improve clarity, executive tone, "
                                    "and logical flow, but keep the same structure:\n\n"
                                    f"{section_text}\n"
                                ),
                            },
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                            },
                        ],
                    }
                ],
            )
        except anthropic.NotFoundError as exc:
            raise ValueError(
                f"Claude 모델을 찾을 수 없습니다: {claude_model}. "
                "계정에서 사용 가능한 모델로 ANTHROPIC_MODEL(.env) 값을 변경하세요."
            ) from exc
        content_text = self._extract_claude_text(response)
        header_line, body = split_script_header(content_text, page_num)
        cleaned_body_lines: list[str] = []
        for line in body.splitlines():
            # Claude가 이미지 태그를 다시 출력해도 최종 파일에서는 코드가 단일 이미지 태그만 쓰도록 정리
            if re.match(r"^\s*!\[Slide\s+\d+\]\((.+)\)\s*$", line):
                continue
            cleaned_body_lines.append(line)
        cleaned_body = "\n".join(cleaned_body_lines).strip()
        return header_line, cleaned_body

    @staticmethod
    def _extract_claude_text(response) -> str:
        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", "") == "text":
                text_parts.append(getattr(block, "text", ""))
        return "\n".join(text_parts).strip()

    @staticmethod
    def _parse_markdown_sections(markdown_text: str) -> tuple[str, list[dict[str, str | int]]]:
        lines = markdown_text.splitlines()
        title = ""
        index = 0

        while index < len(lines) and not lines[index].startswith("#### Page "):
            if not title and lines[index].startswith("# "):
                title = lines[index].strip()
            index += 1

        sections: list[dict[str, str | int]] = []
        current: list[str] = []
        for line in lines[index:]:
            if line.strip() == "---":
                if current:
                    parsed = PresentationScriptGenerator._parse_single_section("\n".join(current).strip())
                    if parsed:
                        sections.append(parsed)
                    current = []
                continue
            current.append(line)

        if current:
            parsed = PresentationScriptGenerator._parse_single_section("\n".join(current).strip())
            if parsed:
                sections.append(parsed)

        return title, sections

    @staticmethod
    def _parse_single_section(section_text: str) -> dict[str, str | int] | None:
        if not section_text:
            return None
        section_lines = [line for line in section_text.splitlines() if line.strip()]
        if not section_lines:
            return None

        header_line = section_lines[0].strip()
        if not header_line.startswith("#### Page "):
            return None

        page_match = re.search(r"^####\s+Page\s+(\d+)", header_line)
        if not page_match:
            return None
        page_num = int(page_match.group(1))

        image_path = ""
        for line in section_lines:
            image_match = re.match(r"!\[Slide\s+\d+\]\((.+)\)", line.strip())
            if image_match:
                image_path = image_match.group(1)
                break

        if not image_path:
            return None

        content_lines: list[str] = [header_line, f"![Slide {page_num}]({image_path})"]
        after_image = False
        for line in section_lines[1:]:
            if not after_image:
                if re.match(r"!\[Slide\s+\d+\]\((.+)\)", line.strip()):
                    after_image = True
                continue
            content_lines.append(line)

        return {
            "page_num": page_num,
            "image_path": image_path,
            "raw_text": "\n".join(content_lines).strip(),
        }
