"""Slide prompt and response parsing helpers."""


def build_slide_prompt(page_num: int) -> str:
    return f"""
This is Slide {page_num} of the presentation.
Follow the system instructions strictly.
Extract the exact slide title from the image.
Start with this header format:
#### Page {page_num} — [Exact Slide Title from Image] (⏱ ~[Estimate Time] min)
""".strip()


def split_script_header(script_content: str, page_num: int) -> tuple[str, str]:
    lines = script_content.split("\n")
    header_line = ""
    script_lines: list[str] = []

    for line in lines:
        if line.startswith("#### Page") and not header_line:
            header_line = line
        else:
            script_lines.append(line)

    if not header_line:
        header_line = f"#### Page {page_num} — Untitled"

    script_body = "\n".join(script_lines).strip()
    return header_line, script_body
