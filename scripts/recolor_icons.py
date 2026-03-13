"""Generate transparent-background icon SVGs in assets/icons_rec/.

- Icons with Dark/Light content variation: strip background, keep both variants
- Icons without variation: strip background from Dark version, save as single file
- Single-version icons: wrap in 256x256 transparent canvas
- Jupyter: wrap + recolor text paths for Dark/Light
- Brand-colored icons: copy unchanged
"""

import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons_og"
OUTPUT_DIR = Path(__file__).parent.parent / "assets" / "icons_rec"

# Icons to copy unchanged (brand-colored, already transparent, correct shape)
COPY_AS_IS = {
    "claude.svg", "Django.svg", "Docker.svg", "Git.svg",
    "Instagram.svg", "LinkedIn.svg",
}

# Icons with actual content variation between Dark/Light (not just background)
# These produce {Name}-Dark.svg and {Name}-Light.svg
HAS_CONTENT_VARIATION = {"Github", "Bash", "LaTeX", "Markdown"}

# Single-version icons — wrap in 256x256 transparent canvas, single file
SINGLE_VERSION = {
    "huggingface.svg", "cuda.svg", "numpy.svg", "qdrant.svg", "uv.svg",
}

# Icons with path-based backgrounds instead of <rect>
PATH_BG_STEMS = {"Arch", "Obsidian", "Windows"}

SYNTHETIC_TARGET = 200  # Icon content scaled to ~200px within 256px canvas

# Jupyter text fill color in the original SVG
JUPYTER_TEXT_COLOR = "#4E4E4E"


def get_viewbox(filepath: Path) -> tuple[float, float, float, float]:
    """Extract viewBox as (x, y, w, h) from an SVG file."""
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    root = ET.parse(filepath).getroot()
    vb = root.get("viewBox", "")
    if vb:
        parts = vb.split()
        return tuple(float(p) for p in parts)
    w = float(root.get("width", "256").replace("px", ""))
    h = float(root.get("height", "256").replace("px", ""))
    return (0, 0, w, h)


def strip_background(content: str, base_stem: str) -> str:
    """Remove background rect or path from SVG content."""
    if base_stem in PATH_BG_STEMS:
        content = re.sub(
            r'<path\s+d="M196 0H60C[^"]*"\s+fill="[^"]*"\s*/?>',
            '', content, count=1,
        )
    else:
        content = re.sub(
            r'<rect\s+(?=(?:[^>]*\bwidth="256"))(?=(?:[^>]*\bheight="256"))(?=(?:[^>]*\brx="60"))[^>]*/?>',
            '', content, count=1,
        )
    return content


def extract_inner_content(svg_text: str) -> str:
    """Extract content between <svg> tags, stripping XML declaration and comments."""
    inner = re.sub(r"<\?xml[^?]*\?>", "", svg_text).strip()
    inner = re.sub(r"<!--.*?-->", "", inner, flags=re.DOTALL).strip()
    match = re.search(r"<svg[^>]*>(.*)</svg>", inner, re.DOTALL)
    return match.group(1).strip() if match else inner


def inline_css_and_styles(content: str) -> str:
    """Inline CSS classes and style attributes."""
    style_match = re.search(r"<style[^>]*>(.*?)</style>", content, re.DOTALL)
    if style_match:
        style_text = style_match.group(1)
        class_fills = {}
        for m in re.finditer(r"\.(\w[\w-]*)\s*\{[^}]*fill:\s*([^;}\s]+)", style_text):
            class_fills[m.group(1)] = m.group(2)
        content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)
        for cls_name, fill_val in class_fills.items():
            content = re.sub(rf'class="{cls_name}"', f'fill="{fill_val}"', content)

    def replace_style(m):
        style_val = m.group(1)
        fill_match = re.search(r"fill:\s*([^;\"]+)", style_val)
        if fill_match:
            return f'fill="{fill_match.group(1).strip()}"'
        return m.group(0)
    content = re.sub(r'style="([^"]*)"', replace_style, content)

    content = re.sub(r"<title>[^<]*</title>", "", content)
    return content


def wrap_transparent(src: Path, dst: Path, text_recolor: str | None = None):
    """Wrap icon in 256x256 transparent canvas. Optionally recolor text paths."""
    svg_text = src.read_text(encoding="utf-8")
    vb = get_viewbox(src)

    content_size = max(vb[2], vb[3])
    scale = SYNTHETIC_TARGET / content_size
    offset_x = (256 - vb[2] * scale) / 2
    offset_y = (256 - vb[3] * scale) / 2
    origin_x = -vb[0] * scale
    origin_y = -vb[1] * scale

    inner_content = extract_inner_content(svg_text)
    inner_content = inline_css_and_styles(inner_content)

    if text_recolor:
        inner_content = inner_content.replace(
            f'fill="{JUPYTER_TEXT_COLOR}"', f'fill="{text_recolor}"'
        )

    output = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <g transform="translate({offset_x + origin_x:.1f},{offset_y + origin_y:.1f}) scale({scale:.6f})">
    {inner_content}
  </g>
</svg>
"""
    dst.write_text(output, encoding="utf-8")


def main():
    """Generate transparent-background icons in assets/icons_rec/."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    print("Generating transparent-background icons in assets/icons_rec/...")
    print()

    processed = 0

    for src_file in sorted(ICONS_DIR.glob("*.svg")):
        name = src_file.name
        stem = src_file.stem  # e.g., "Python-Dark"

        if name in COPY_AS_IS:
            shutil.copy2(src_file, OUTPUT_DIR / name)
            print(f"  [copy]   {name}")
            processed += 1
            continue

        if name == "jupyter.svg":
            # Jupyter: wrap with text recolor for Dark/Light
            wrap_transparent(src_file, OUTPUT_DIR / "Jupyter-Dark.svg", text_recolor="#FFFFFF")
            wrap_transparent(src_file, OUTPUT_DIR / "Jupyter-Light.svg", text_recolor="#000000")
            print(f"  [jup]    {name} -> Jupyter-Dark.svg, Jupyter-Light.svg")
            processed += 1
            continue

        if name in SINGLE_VERSION:
            # Wrap in transparent canvas, single file
            cap_stem = stem.capitalize()
            wrap_transparent(src_file, OUTPUT_DIR / f"{cap_stem}.svg")
            print(f"  [wrap]   {name} -> {cap_stem}.svg")
            processed += 1
            continue

        # Dark/Light variant icon — check if it has content variation
        base = stem.rsplit("-", 1)[0]  # e.g., "Python"
        variant = stem.rsplit("-", 1)[1] if "-" in stem else ""  # "Dark" or "Light"

        if base in HAS_CONTENT_VARIATION:
            # Keep both Dark and Light files
            content = src_file.read_text(encoding="utf-8")
            content = strip_background(content, base)
            (OUTPUT_DIR / name).write_text(content, encoding="utf-8")
            print(f"  [strip]  {name}")
            processed += 1
        elif variant == "Dark":
            # No content variation — use Dark version as the single file
            content = src_file.read_text(encoding="utf-8")
            content = strip_background(content, base)
            (OUTPUT_DIR / f"{base}.svg").write_text(content, encoding="utf-8")
            print(f"  [dedup]  {name} -> {base}.svg")
            processed += 1
        elif variant == "Light":
            # Skip Light version (duplicate content, Dark already processed)
            print(f"  [skip]   {name} (duplicate of Dark)")
        else:
            # No variant suffix (e.g., microsoft-outlook.svg)
            content = src_file.read_text(encoding="utf-8")
            content = strip_background(content, base)
            (OUTPUT_DIR / name).write_text(content, encoding="utf-8")
            print(f"  [strip]  {name}")
            processed += 1

    print()
    print(f"Done. {processed} source icons -> {len(list(OUTPUT_DIR.glob('*.svg')))} files in icons_rec/")


if __name__ == "__main__":
    main()
