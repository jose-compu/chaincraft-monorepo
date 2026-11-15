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


def wrap_description(text: str, width: int, max_lines: int = 2) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return textwrap.wrap(text, width=width, max_lines=max_lines)


def description_block(lines: list[str], x: int, y0: int, font_size: int, line_gap: int) -> str:
    if not lines:
        return ""
    return "\n  ".join(
        f'<text x="{x}" y="{y0 + i * line_gap}" class="sans" fill="#8b939e" '
        f'font-size="{font_size}" font-weight="400">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )


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
        desc_lines = wrap_description(description, width=48)
        desc_block = description_block(desc_lines, x=530, y0=428, font_size=20, line_gap=26)
    else:
        desc_lines = wrap_description(description, width=72)
        desc_block = description_block(desc_lines, x=360, y0=312, font_size=16, line_gap=22)

    fields = {
        "VERSION": version,
        "HEADLINE": headline,
        "DETAIL": detail,
        "URL": url,
        "TAGLINE": TAGLINE,
    }
    raw = {"DESCRIPTION_BLOCK": desc_block}

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
        help="Optional release note (up to two wrapped lines, light gray, below languages)",
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
