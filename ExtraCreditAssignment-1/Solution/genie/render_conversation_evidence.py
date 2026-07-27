"""Render the three captured live Genie conversations as visual evidence."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "genie" / "conversation_evidence.json"
OUTPUT_DIR = ROOT / "genie" / "screenshots"
WIDTH = 1600
PADDING = 56
LINE_HEIGHT = 30


def _font(size: int, *, bold: bool = False):
    candidates = [
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        (
            "/System/Library/Fonts/SFNSMono.ttf"
            if not bold
            else "/System/Library/Fonts/SFNSMono-Bold.ttf"
        ),
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _wrap(text: str, width: int) -> list[str]:
    lines = []
    for raw_line in text.splitlines() or [""]:
        lines.extend(textwrap.wrap(raw_line, width=width) or [""])
    return lines


def _table(record: dict) -> list[str]:
    columns = [str(column) for column in record["columns"]]
    rows = [[str(value) for value in row] for row in record["rows"]]
    widths = [
        max(len(columns[index]), *(len(row[index]) for row in rows))
        for index in range(len(columns))
    ]

    def format_row(row: list[str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    return [
        format_row(columns),
        "-+-".join("-" * width for width in widths),
        *(format_row(row) for row in rows),
    ]


def _render(record: dict, index: int) -> Path:
    title_font = _font(36, bold=True)
    label_font = _font(25, bold=True)
    body_font = _font(23)
    mono_font = _font(21)

    sections = [
        ("Question", _wrap(record["question"], 105), body_font),
        ("Generated SQL", _wrap(record["generated_sql"], 112), mono_font),
        ("Result", _table(record), mono_font),
    ]
    height = 150
    for _, lines, _ in sections:
        height += 54 + max(1, len(lines)) * LINE_HEIGHT + 36
    if record.get("text"):
        answer_lines = _wrap(str(record["text"]), 105)
        sections.append(("Genie answer", answer_lines, body_font))
        height += 54 + len(answer_lines) * LINE_HEIGHT + 36

    image = Image.new("RGB", (WIDTH, height), "#f4f7fb")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (24, 24, WIDTH - 24, height - 24),
        radius=22,
        fill="#ffffff",
        outline="#cbd5e1",
        width=2,
    )
    draw.text(
        (PADDING, 48),
        f"Live Genie conversation evidence {index}",
        font=title_font,
        fill="#111827",
    )
    draw.text(
        (PADDING, 94),
        f"Conversation ID: {record['conversation_id']}",
        font=body_font,
        fill="#64748b",
    )
    y = 145
    for label, lines, font in sections:
        draw.text((PADDING, y), label, font=label_font, fill="#1d4ed8")
        y += 44
        box_height = max(1, len(lines)) * LINE_HEIGHT + 28
        draw.rounded_rectangle(
            (PADDING, y, WIDTH - PADDING, y + box_height),
            radius=12,
            fill="#f8fafc",
            outline="#e2e8f0",
        )
        text_y = y + 14
        for line in lines:
            draw.text((PADDING + 18, text_y), line, font=font, fill="#0f172a")
            text_y += LINE_HEIGHT
        y += box_height + 28

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"genie_question_{index}.png"
    image.save(output)
    return output


def main() -> None:
    records = json.loads(SOURCE.read_text(encoding="utf-8"))
    if len(records) < 3:
        raise ValueError("Task 2.2 requires at least three Genie conversations")
    for index, record in enumerate(records[:3], start=1):
        output = _render(record, index)
        print(output)


if __name__ == "__main__":
    main()
