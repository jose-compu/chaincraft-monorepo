#!/usr/bin/env python3
"""Rasterise the identity card and LinkedIn banners from brand/templates.

Identity, logos, fonts, and templates are committed. PNG output is local:

    python3 brand/render.py card
    python3 brand/render.py banner --version 1.4.0 --headline "Avalanche and CRDT KV"
"""

from __future__ import annotations

import argparse
import base64
import html
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
ASSETS = ROOT / "assets"
FONTS = ROOT / "fonts"
OUT = ROOT / "out"

TAGLINE = "Open-source framework for peer-to-peer protocols"

Family = Literal["sans", "mono", "pixel"]

METRICS: dict[Family, dict[str, float]] = {
    "sans": {"ascent": 0.78, "descent": 0.22, "width": 0.50},
    "mono": {"ascent": 0.75, "descent": 0.25, "width": 0.56},
    "pixel": {"ascent": 1.0, "descent": 0.05, "width": 0.62},
}

SIZES = {
    "identity-card": (1920, 1080),
    "linkedin-landscape": (1200, 627),
    "linkedin-cover": (1584, 396),
}

LANDSCAPE_PANEL = (530, 1148, 118, 536)
COVER_PANEL_LEFT = (360, 1260, 115, 382)
COVER_PANEL_URL = (1280, 1568, 115, 382)


class LayoutError(ValueError):
    """Banner text would overlap or sit outside the panel."""


@dataclass
class TextBox:
    x: int
    baseline: float
    font_size: int
    line_height: float
    lines: list[str]
    family: Family
    weight: str = "400"

    def top(self) -> float:
        return self.baseline - self.font_size * METRICS[self.family]["ascent"]

    def bottom(self) -> float:
        last = self.baseline + (len(self.lines) - 1) * self.line_height
        return last + self.font_size * METRICS[self.family]["descent"]

    def right(self) -> float:
        m = METRICS[self.family]
        widest = max((len(line) for line in self.lines), default=0)
        return self.x + widest * self.font_size * m["width"]


def banner_display_url(url: str) -> str:
    site = url.strip() or "chaincraft.network"
    if "://" not in site:
        site = f"https://{site.removeprefix('/')}"
    return site


def banner_url_font_size(kind: str, display_url: str) -> int:
    length = len(display_url)
    if kind == "linkedin-landscape":
        if length <= 28:
            return 24
        if length <= 36:
            return 22
        return 20
    if length <= 28:
        return 15
    if length <= 34:
        return 14
    return 13


def text_width_px(text: str, font_size: int, family: Family) -> float:
    return len(text) * font_size * METRICS[family]["width"]


def first_baseline_below(y_bottom: float, gap: float, font_size: int, family: Family) -> float:
    return y_bottom + gap + font_size * METRICS[family]["ascent"]


def line_step(font_size: int, family: Family) -> float:
    return font_size * (1.15 if family == "sans" else 1.2)


def font_css() -> str:
    faces = [
        ("Press Start 2P", 400, "PressStart2P-Regular.ttf"),
        ("IBM Plex Sans", 400, "IBMPlexSans-Regular.ttf"),
        ("IBM Plex Sans", 500, "IBMPlexSans-Medium.ttf"),
        ("IBM Plex Sans", 600, "IBMPlexSans-SemiBold.ttf"),
        ("IBM Plex Mono", 400, "IBMPlexMono-Regular.ttf"),
        ("IBM Plex Mono", 500, "IBMPlexMono-Medium.ttf"),
    ]
    rules = []
    for family, weight, name in faces:
        uri = (FONTS / name).as_uri()
        rules.append(
            f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
            f'font-style: normal; src: url("{uri}"); }}'
        )
    return "\n      ".join(rules)


def png_data_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def fill(
    template: str,
    fields: dict[str, str],
    raw_fields: dict[str, str] | None = None,
) -> str:
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    mapping = {
        "{{FONT_CSS}}": font_css(),
        "{{MARK}}": png_data_uri(ASSETS / "chaincraft-logo.png"),
        "{{WORDMARK}}": png_data_uri(ASSETS / "chaincraft-logo-text.png"),
        "{{LOCKUP}}": png_data_uri(ASSETS / "chaincraft-logo-full.png"),
        **{"{{" + k + "}}": html.escape(v, quote=True) for k, v in fields.items()},
    }
    for key, value in mapping.items():
        text = text.replace(key, value)
    for key, value in (raw_fields or {}).items():
        text = text.replace("{{" + key + "}}", value)
    return text


def wrap_full(text: str, width: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def wrap_to_width_px(
    text: str,
    font_size: int,
    family: Family,
    max_px: float,
    max_lines: int,
) -> list[str]:
    for width in range(80, 8, -1):
        lines = wrap_full(text, width)
        if len(lines) > max_lines:
            continue
        if all(text_width_px(line, font_size, family) <= max_px for line in lines):
            return lines
    return wrap_full(text, 12)[:max_lines]


def fit_description_two_lines(text: str, panel_width: float, font_size: int) -> list[str]:
    """Exactly up to two lines at >= font_size; never truncates with ellipsis."""
    text = text.strip()
    if not text:
        return []
    for width in range(72, 24, -1):
        lines = wrap_full(text, width)
        if len(lines) <= 2 and all(
            text_width_px(line, font_size, "sans") <= panel_width for line in lines
        ):
            return lines
    lines = wrap_full(text, 24)
    return lines[:2]


def pick_single_line_tagline_size(panel_width: float) -> int:
    for size in (19, 18, 17, 16, 15):
        if text_width_px(TAGLINE, size, "sans") <= panel_width:
            return size
    return 15


def text_block(
    lines: list[str],
    x: int,
    y0: float,
    font_size: int,
    line_gap: float,
    *,
    css_class: str = "sans",
    fill: str = "#a7b0b8",
    weight: str = "400",
) -> str:
    if not lines:
        return ""
    return "\n  ".join(
        f'<text x="{x}" y="{y0 + i * line_gap:.2f}" class="{css_class}" fill="{fill}" '
        f'font-size="{font_size}" font-weight="{weight}">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )


def x_ranges_overlap(a: TextBox, b: TextBox) -> bool:
    return a.x < b.right() and b.x < a.right()


def validate_layout(boxes: list[TextBox], panel: tuple[float, float, float, float], *, min_gap: float) -> None:
    left, right, top, bottom = panel
    for box in boxes:
        if box.top() < top - 0.5:
            raise LayoutError(f"{box.lines[0]!r} above panel top")
        if box.bottom() > bottom + 0.5:
            raise LayoutError(f"{box.lines[-1]!r} below panel bottom")
        if box.x < left - 1 or box.right() > right + 1:
            raise LayoutError(f"text wider than panel: {box.lines[0]!r}")
    ordered = sorted(boxes, key=lambda b: b.top())
    for upper, lower in zip(ordered, ordered[1:]):
        if not x_ranges_overlap(upper, lower):
            continue
        gap = lower.top() - upper.bottom()
        if gap < min_gap - 0.5:
            raise LayoutError(
                f"overlap between {upper.lines[0]!r} and {lower.lines[0]!r} (gap {gap:.1f}px)"
            )


def compose_landscape_layout(
    headline: str,
    detail: str,
    description: str,
    display_url: str,
) -> tuple[dict[str, str | int], dict[str, str], list[TextBox]]:
    left, right, top, bottom = LANDSCAPE_PANEL
    panel_w = right - left
    x = int(left)
    wordmark_bottom = 132 + 76
    desc_lines = fit_description_two_lines(description, panel_w, 20)
    desc_size = 20
    desc_gap = 26
    url_size = banner_url_font_size("linkedin-landscape", display_url)

    boxes: list[TextBox] = []
    tagline_baseline = release_baseline = headline_baseline = detail_baseline = desc_baseline = url_baseline = 0.0
    headline_size = 44
    headline_lines: list[str] = []
    tagline_size = pick_single_line_tagline_size(panel_w)
    tagline_gap = line_step(tagline_size, "sans")

    for tight in (False, True):
        gap_tagline = 10 if not tight else 8
        gap_release = 20 if not tight else 14
        gap_headline = 18 if not tight else 12
        gap_detail = 20 if not tight else 14
        gap_desc = 18 if not tight else 14
        gap_url = 20
        sizes = (44, 40, 38, 36, 34, 32) if not tight else (36, 34, 32, 30)
        for headline_size in sizes:
            headline_lines = wrap_to_width_px(headline, headline_size, "sans", panel_w, 2)
            headline_gap = line_step(headline_size, "sans")

            tagline_baseline = first_baseline_below(wordmark_bottom, gap_tagline, tagline_size, "sans")
            tagline_box = TextBox(x, tagline_baseline, tagline_size, tagline_gap, [TAGLINE], "sans")

            release_size = 28
            release_baseline = first_baseline_below(tagline_box.bottom(), gap_release, release_size, "pixel")
            release_box = TextBox(
                x, release_baseline, release_size, line_step(release_size, "pixel"), ["RELEASE"], "pixel"
            )

            headline_baseline = first_baseline_below(release_box.bottom(), gap_headline, headline_size, "sans")
            headline_box = TextBox(
                x, headline_baseline, headline_size, headline_gap, headline_lines, "sans", "600"
            )

            detail_size = 28
            detail_baseline = first_baseline_below(headline_box.bottom(), gap_detail, detail_size, "mono")
            detail_box = TextBox(x, detail_baseline, detail_size, line_step(detail_size, "mono"), [detail], "mono")

            desc_box = None
            if desc_lines:
                desc_baseline = first_baseline_below(detail_box.bottom(), gap_desc, desc_size, "sans")
                desc_box = TextBox(x, desc_baseline, desc_size, desc_gap, desc_lines, "sans")

            anchor = desc_box.bottom() if desc_box else detail_box.bottom()
            url_baseline = first_baseline_below(anchor, gap_url, url_size, "sans")
            url_box = TextBox(
                x, url_baseline, url_size, line_step(url_size, "sans"), [display_url], "sans", "600"
            )

            boxes = [tagline_box, release_box, headline_box, detail_box, url_box]
            if desc_box:
                boxes.insert(4, desc_box)
            try:
                validate_layout(boxes, LANDSCAPE_PANEL, min_gap=18)
            except LayoutError:
                continue
            if url_box.bottom() <= bottom + 0.5:
                break
        else:
            continue
        break
    else:
        raise LayoutError("banner content does not fit in landscape panel")

    validate_layout(boxes, LANDSCAPE_PANEL, min_gap=18)

    fields: dict[str, str | int] = {
        "RELEASE_Y": round(release_baseline),
        "HEADLINE_SIZE": headline_size,
        "DETAIL_Y": round(detail_baseline),
        "URL_Y": round(url_baseline),
        "URL_SIZE": url_size,
    }
    raw = {
        "TAGLINE_BLOCK": text_block([TAGLINE], x, tagline_baseline, tagline_size, tagline_gap, fill="#a7b0b8"),
        "HEADLINE_BLOCK": text_block(
            headline_lines,
            x,
            headline_baseline,
            headline_size,
            headline_gap,
            fill="#e8ecef",
            weight="600",
        ),
        "DESCRIPTION_BLOCK": text_block(
            desc_lines,
            x,
            desc_baseline if desc_lines else 0,
            desc_size,
            desc_gap,
            fill="#8b939e",
        )
        if desc_lines
        else "",
    }
    return fields, raw, boxes


def compose_cover_layout(
    headline: str,
    detail: str,
    description: str,
    display_url: str,
) -> tuple[dict[str, str | int], dict[str, str], list[TextBox]]:
    left, right, top, bottom = COVER_PANEL_LEFT
    panel_w = right - left
    x = int(left)
    wordmark_bottom = 120 + 99

    tagline_size = pick_single_line_tagline_size(panel_w)
    tagline_baseline = first_baseline_below(wordmark_bottom, 8, tagline_size, "sans")
    tagline_box = TextBox(x, tagline_baseline, tagline_size, line_step(tagline_size, "sans"), [TAGLINE], "sans")

    headline_size = 24
    headline_lines = wrap_to_width_px(headline, headline_size, "sans", panel_w, 2)
    headline_baseline = first_baseline_below(tagline_box.bottom(), 12, headline_size, "sans")
    headline_box = TextBox(
        x,
        headline_baseline,
        headline_size,
        line_step(headline_size, "sans"),
        headline_lines,
        "sans",
    )

    detail_size = 18
    detail_baseline = first_baseline_below(headline_box.bottom(), 10, detail_size, "mono")
    detail_box = TextBox(x, detail_baseline, detail_size, line_step(detail_size, "mono"), [detail], "mono")

    desc_size = 16
    desc_lines = fit_description_two_lines(description, panel_w, desc_size)
    desc_gap = 22
    desc_baseline = first_baseline_below(detail_box.bottom(), 10, desc_size, "sans")
    desc_box = (
        TextBox(x, desc_baseline, desc_size, desc_gap, desc_lines, "sans") if desc_lines else None
    )

    url_x = 1280
    url_size = banner_url_font_size("linkedin-cover", display_url)
    url_baseline = 230.0
    url_box = TextBox(url_x, url_baseline, url_size, line_step(url_size, "sans"), [display_url], "sans")

    left_boxes = [tagline_box, headline_box, detail_box]
    if desc_box:
        left_boxes.append(desc_box)
    boxes = left_boxes + [url_box]

    validate_layout(left_boxes, COVER_PANEL_LEFT, min_gap=8)
    validate_layout([url_box], COVER_PANEL_URL, min_gap=8)

    fields: dict[str, str | int] = {
        "HEADLINE_Y": round(headline_baseline),
        "DETAIL_Y": round(detail_baseline),
        "URL_SIZE": url_size,
    }
    raw = {
        "TAGLINE_BLOCK": text_block([TAGLINE], x, tagline_baseline, tagline_size, line_step(tagline_size, "sans"), fill="#a7b0b8"),
        "HEADLINE_BLOCK": text_block(
            headline_lines,
            x,
            headline_baseline,
            headline_size,
            line_step(headline_size, "sans"),
            fill="#a7b0b8",
        ),
        "DESCRIPTION_BLOCK": text_block(
            desc_lines,
            x,
            desc_baseline if desc_lines else 0,
            desc_size,
            desc_gap,
            fill="#8b939e",
        )
        if desc_lines
        else "",
    }
    return fields, raw, boxes


def rasterise(name: str, svg: str, scale: int) -> Path:
    width, _height = SIZES[name]
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / f"{name}.svg"
    dest = OUT / f"{name}.png"
    src.write_text(svg, encoding="utf-8")
    cmd = [
        "rsvg-convert",
        f"--width={width * scale}",
        str(src),
        "-o",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.stderr.write("rsvg-convert is required (librsvg)\n")
        raise SystemExit(2)
    return dest


def card(scale: int) -> Path:
    svg = fill("identity-card.svg", {})
    return rasterise("identity-card", svg, scale)


def banner(
    version: str,
    headline: str,
    detail: str,
    url: str,
    kind: str,
    scale: int,
    description: str = "",
) -> Path:
    display_url = banner_display_url(url)
    if kind == "linkedin-landscape":
        layout_fields, raw, _boxes = compose_landscape_layout(headline, detail, description, display_url)
    else:
        layout_fields, raw, _boxes = compose_cover_layout(headline, detail, description, display_url)

    fields = {
        "VERSION": version,
        "HEADLINE": headline,
        "DETAIL": detail,
        "URL": display_url,
        **{k: str(v) for k, v in layout_fields.items()},
    }

    template = f"{kind}.svg"
    svg = fill(template, fields, raw)
    stem = f"{kind}-{version.replace('.', '')}"
    width, _height = SIZES[kind]
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / f"{stem}.svg"
    dest = OUT / f"{stem}.png"
    src.write_text(svg, encoding="utf-8")
    subprocess.run(
        ["rsvg-convert", f"--width={width * scale}", str(src), "-o", str(dest)],
        check=True,
    )
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=int, default=2, help="output multiplier (2 = publication)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("card", help="render brand/out/identity-card.png")

    b = sub.add_parser("banner", help="render a local LinkedIn banner")
    b.add_argument("--version", required=True)
    b.add_argument("--headline", required=True)
    b.add_argument("--detail", default="Python · Rust · TypeScript")
    b.add_argument(
        "--description",
        default="",
        help="Optional release note (wrapped, light gray, below languages; full text, no ellipsis)",
    )
    b.add_argument("--url", default="chaincraft.network")
    b.add_argument(
        "--kind",
        choices=("linkedin-landscape", "linkedin-cover"),
        default="linkedin-landscape",
    )

    args = parser.parse_args()
    if args.cmd == "card":
        path = card(args.scale)
    else:
        path = banner(
            args.version,
            args.headline,
            args.detail,
            args.url,
            args.kind,
            args.scale,
            args.description,
        )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())