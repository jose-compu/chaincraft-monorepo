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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
ASSETS = ROOT / "assets"
FONTS = ROOT / "fonts"
OUT = ROOT / "out"

TAGLINE = "Open-source framework for peer-to-peer protocols"


def banner_display_url(url: str) -> str:
    """Canonical site URL for banner copy (always includes a scheme)."""
    site = url.strip() or "chaincraft.network"
    if "://" not in site:
        site = f"https://{site.removeprefix('/')}"
    return site


def banner_url_font_size(kind: str, display_url: str) -> int:
    """Pick a size that keeps the full URL inside each banner's text area."""
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


SIZES = {
    "identity-card": (1920, 1080),
    "linkedin-landscape": (1200, 627),
    "linkedin-cover": (1584, 396),
}


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


def fit_description(
    text: str,
    *,
    min_width: int,
    max_width: int,
    line_budget: tuple[int, ...],
) -> tuple[list[str], int]:
    """Return wrapped lines and character width; never uses textwrap max_lines (no ellipsis)."""
    text = text.strip()
    if not text:
        return [], max_width
    for budget in line_budget:
        for width in range(max_width, min_width - 1, -1):
            lines = wrap_full(text, width)
            if len(lines) <= budget:
                return lines, width
    lines = wrap_full(text, min_width)
    return lines[: line_budget[-1]], min_width


def text_block(
    lines: list[str],
    x: int,
    y0: int,
    font_size: int,
    line_gap: int,
    *,
    css_class: str = "sans",
    fill: str = "#a7b0b8",
    weight: str = "400",
) -> str:
    if not lines:
        return ""
    return "\n  ".join(
        f'<text x="{x}" y="{y0 + i * line_gap}" class="{css_class}" fill="{fill}" '
        f'font-size="{font_size}" font-weight="{weight}">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )


def landscape_layout(description: str) -> dict[str, object]:
    """Vertical rhythm inside the right panel (y is text baseline)."""
    url_y = 532
    tagline_lines = wrap_full(TAGLINE, width=36)
    tagline_size = 24
    tagline_gap = 30
    tagline_y0 = 238
    release_y = tagline_y0 + len(tagline_lines) * tagline_gap + 24
    headline_y = release_y + 72
    detail_y = headline_y + 68

    desc_lines: list[str] = []
    desc_size = 19
    desc_gap = 24
    desc_y0 = detail_y + 36
    if description.strip():
        for desc_size, desc_gap, budgets in (
            (18, 24, (2, 3)),
            (17, 22, (2, 3)),
            (16, 20, (3,)),
        ):
            desc_lines, _ = fit_description(
                description,
                min_width=30,
                max_width=54,
                line_budget=budgets,
            )
            if not desc_lines:
                break
            desc_end = desc_y0 + (len(desc_lines) - 1) * desc_gap
            if desc_end <= url_y - 26:
                break

    raw: dict[str, str] = {
        "TAGLINE_BLOCK": text_block(
            tagline_lines,
            530,
            tagline_y0,
            tagline_size,
            tagline_gap,
            fill="#a7b0b8",
        ),
        "DESCRIPTION_BLOCK": text_block(
            desc_lines,
            530,
            desc_y0,
            desc_size,
            desc_gap,
            fill="#8b939e",
        ),
    }
    fields = {
        "RELEASE_Y": release_y,
        "HEADLINE_Y": headline_y,
        "DETAIL_Y": detail_y,
        "URL_Y": url_y,
    }
    return {"fields": fields, "raw": raw}


def cover_layout(description: str) -> dict[str, str | int]:
    tagline_lines = wrap_full(TAGLINE, width=48)
    tagline_size = 15
    tagline_gap = 20
    tagline_y0 = 232
    headline_y = tagline_y0 + len(tagline_lines) * tagline_gap + 18
    detail_y = headline_y + 30

    desc_lines: list[str] = []
    desc_size = 15
    desc_gap = 19
    if description.strip():
        desc_lines, _ = fit_description(
            description,
            min_width=40,
            max_width=68,
            line_budget=(2, 3),
        )
        if len(desc_lines) >= 3:
            desc_size = 14
            desc_gap = 18

    raw: dict[str, str] = {
        "TAGLINE_BLOCK": text_block(
            tagline_lines,
            360,
            tagline_y0,
            tagline_size,
            tagline_gap,
            fill="#a7b0b8",
        ),
        "DESCRIPTION_BLOCK": text_block(
            desc_lines,
            360,
            detail_y + 22,
            desc_size,
            desc_gap,
            fill="#8b939e",
        ),
    }
    fields: dict[str, str | int] = {
        "HEADLINE_Y": headline_y,
        "DETAIL_Y": detail_y,
    }
    return {"fields": fields, "raw": raw}


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
    if kind == "linkedin-landscape":
        layout = landscape_layout(description)
    else:
        layout = cover_layout(description)

    display_url = banner_display_url(url)
    fields = {
        "VERSION": version,
        "HEADLINE": headline,
        "DETAIL": detail,
        "URL": display_url,
        "URL_SIZE": str(banner_url_font_size(kind, display_url)),
        **{k: str(v) for k, v in layout["fields"].items()},
    }
    raw = layout["raw"]

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
