"""Layout checks for brand/render.py banner composition."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("brand_render", ROOT / "render.py")
assert SPEC and SPEC.loader
render = importlib.util.module_from_spec(SPEC)
sys.modules["brand_render"] = render
SPEC.loader.exec_module(render)

STRESS_HEADLINE = "Distributed message field index and ordered query API"
STRESS_DESC = (
    "Register a message field, then query it to get matching message ids "
    "in insertion order. Local only."
)


class BannerLayoutTests(unittest.TestCase):
    def test_landscape_stress_layout(self) -> None:
        url = render.banner_display_url("chaincraft.network")
        _fields, _raw, boxes = render.compose_landscape_layout(
            STRESS_HEADLINE, "Python · Rust · TypeScript", STRESS_DESC, url
        )
        render.validate_layout(boxes, render.LANDSCAPE_PANEL, min_gap=18)
        desc = next(b for b in boxes if len(b.lines) > 1 and b.font_size >= 20)
        self.assertEqual(len(desc.lines), 2)
        self.assertEqual(len(next(b for b in boxes if b.lines == [render.TAGLINE]).lines), 1)

    def test_cover_stress_layout(self) -> None:
        url = render.banner_display_url("chaincraft.network")
        _fields, _raw, boxes = render.compose_cover_layout(
            STRESS_HEADLINE, "Python · Rust · TypeScript", STRESS_DESC, url
        )
        left = [b for b in boxes if b.x < 1280]
        render.validate_layout(left, render.COVER_PANEL_LEFT, min_gap=8)
        render.validate_layout(
            [b for b in boxes if b.x >= 1280],
            render.COVER_PANEL_URL,
            min_gap=8,
        )

    def test_stress_render_all_kinds(self) -> None:
        for kind in ("linkedin-landscape", "linkedin-cover"):
            render.banner(
                "9.9.9",
                STRESS_HEADLINE,
                "Python · Rust · TypeScript",
                "chaincraft.network",
                kind,
                1,
                STRESS_DESC,
            )


if __name__ == "__main__":
    unittest.main()