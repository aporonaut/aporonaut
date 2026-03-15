"""Build focus section SVGs from config in README.md.

Reads FOCUS:CONFIG comment block from README, fetches SimpleIcons SVGs,
generates combined icon+text SVGs with proper vertical centering, and
updates the README with <img> tags pointing to the generated files.
"""

import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"
FOCUS_DIR = ROOT / "assets" / "focus"

# SVG layout constants
LINE_HEIGHT = 28
ICON_SIZE = 20
ICON_Y = (LINE_HEIGHT - ICON_SIZE) // 2  # 4px — vertically centered
ICON_VIEWBOX = "0 0 24 24"
TEXT_Y = LINE_HEIGHT // 2  # 14px — used with dominant-baseline="central"
FONT_SIZE = 14
FONT_FAMILY = "'Segoe UI', Helvetica, Arial, sans-serif"
ICON_TEXT_GAP = 8   # px between icon right edge and name text
TSPAN_DX = 12       # px relative gap between name/pipe and pipe/tagline
WRAP_DY = 18        # px vertical offset for wrapped lines
VIEWBOX_WIDTH = 850  # fixed viewBox width for all SVGs (uniform scaling)
PIPE_WIDTH = 4.0    # estimated width of "|" character

# Rough average char width for viewBox sizing (proportional font estimate)
AVG_CHAR_WIDTH_BOLD = 8.0
AVG_CHAR_WIDTH = 7.6


def estimate_width(text: str, bold: bool = False) -> float:
    """Rough pixel width estimate for a string at FONT_SIZE."""
    avg = AVG_CHAR_WIDTH_BOLD if bold else AVG_CHAR_WIDTH
    return len(text) * avg


def wrap_text(text: str, max_width: float) -> list[str]:
    """Split text into lines that fit within max_width pixels."""
    words = text.split()
    lines, current = [], []
    current_width = 0.0
    for word in words:
        word_width = estimate_width(word)
        space_width = AVG_CHAR_WIDTH if current else 0
        if current and current_width + space_width + word_width > max_width:
            lines.append(" ".join(current))
            current, current_width = [word], word_width
        else:
            current.append(word)
            current_width += space_width + word_width
    if current:
        lines.append(" ".join(current))
    return lines


def fetch_icon_path(slug: str) -> str:
    """Fetch SimpleIcons SVG and extract the path d attribute."""
    url = f"https://cdn.simpleicons.org/{slug}"
    req = urllib.request.Request(url, headers={"User-Agent": "build-focus/1.0"})
    with urllib.request.urlopen(req) as resp:
        svg_text = resp.read().decode()
    # Parse and extract path data (handle default SVG namespace)
    root = ET.fromstring(svg_text)
    path_el = root.find(".//{http://www.w3.org/2000/svg}path")
    if path_el is None:
        path_el = root.find(".//path")
    if path_el is None:
        raise ValueError(f"No <path> found in SimpleIcons SVG for '{slug}'")
    return path_el.get("d")


def build_svg(name: str, tagline: str, color: str, icon_path_d: str) -> str:
    """Generate an SVG with icon + name + pipe + tagline, all vertically centered."""
    x_text = ICON_SIZE + ICON_TEXT_GAP  # 28px — content left-aligned at x=0

    # Estimate first-line width for wrapping and viewBox sizing
    name_width = estimate_width(name, bold=True)
    first_line_prefix = x_text + name_width + TSPAN_DX + PIPE_WIDTH + TSPAN_DX
    available_for_tagline = VIEWBOX_WIDTH - first_line_prefix - 8

    tag_lines = wrap_text(tagline, available_for_tagline)

    # Build tagline tspans
    tagline_x = int(first_line_prefix)
    tag_tspans = f'<tspan class="tag" dx="{TSPAN_DX}">{tag_lines[0]}</tspan>'
    for extra_line in tag_lines[1:]:
        tag_tspans += f'\n    <tspan class="tag" x="{tagline_x}" dy="{WRAP_DY}">{extra_line}</tspan>'

    extra_lines = len(tag_lines) - 1
    svg_height = LINE_HEIGHT + extra_lines * WRAP_DY

    # Tight viewBox width (content only), but fixed SVG width for uniform scaling
    first_line_width = int(first_line_prefix + estimate_width(tag_lines[0]) + 8)
    wrapped_widths = [int(tagline_x + estimate_width(line) + 8) for line in tag_lines[1:]]
    vb_width = max(first_line_width, *wrapped_widths) if wrapped_widths else first_line_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{VIEWBOX_WIDTH}" height="{svg_height}" viewBox="0 0 {vb_width} {svg_height}" preserveAspectRatio="xMidYMid meet">
  <style>
    .name {{ font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}px; font-weight: 600; }}
    .sep  {{ font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}px; opacity: 0.5; }}
    .tag  {{ font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}px; }}
    @media (prefers-color-scheme: dark) {{
      .name, .sep, .tag {{ fill: #E6EDF3; }}
    }}
    @media (prefers-color-scheme: light) {{
      .name, .sep, .tag {{ fill: #1F2328; }}
    }}
  </style>
  <svg x="0" y="{ICON_Y}" width="{ICON_SIZE}" height="{ICON_SIZE}" viewBox="{ICON_VIEWBOX}">
    <path d="{icon_path_d}" fill="#{color}"/>
  </svg>
  <text y="{TEXT_Y}" dominant-baseline="central">
    <tspan class="name" x="{x_text}">{name}</tspan>
    <tspan class="sep" dx="{TSPAN_DX}">|</tspan>
    {tag_tspans}
  </text>
</svg>
"""


def sanitize_filename(name: str) -> str:
    """Convert project name to a safe filename slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_config(readme_text: str) -> list[tuple[str, str, str, str]]:
    """Extract focus items from FOCUS:CONFIG comment block."""
    match = re.search(
        r"<!-- FOCUS:CONFIG\s*\n(.*?)\n\s*FOCUS:CONFIG -->",
        readme_text,
        re.DOTALL,
    )
    if not match:
        raise ValueError("FOCUS:CONFIG block not found in README.md")

    items = []
    for line in match.group(1).strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",", 3)
        if len(parts) != 4:
            raise ValueError(f"Invalid config line (expected slug,color,name,tagline): {line}")
        slug, color, name, tagline = (p.strip() for p in parts)
        items.append((slug, color, name, tagline))
    return items


def build_readme_block(items: list[tuple[str, str, str, str]], filenames: list[str]) -> str:
    """Generate the HTML block with <img> tags for the README."""
    lines = []
    for (_slug, _color, name, tagline), filename in zip(items, filenames):
        alt = f"{name} | {tagline}"
        lines.append(f'    <img src="assets/focus/{filename}" alt="{alt}" />')
    inner = "<br /><br />\n".join(lines)
    return f"<!-- FOCUS:START -->\n  <p>\n{inner}\n  </p>\n<!-- FOCUS:END -->"


def main():
    readme_text = README.read_text(encoding="utf-8")
    items = parse_config(readme_text)
    print(f"Found {len(items)} focus items in config")

    # Clear and recreate output directory
    if FOCUS_DIR.exists():
        shutil.rmtree(FOCUS_DIR)
    FOCUS_DIR.mkdir(parents=True)

    filenames = []
    for slug, color, name, tagline in items:
        print(f"  Fetching icon: {slug}")
        icon_path_d = fetch_icon_path(slug)

        svg_content = build_svg(name, tagline, color, icon_path_d)
        filename = f"{sanitize_filename(name)}.svg"
        (FOCUS_DIR / filename).write_text(svg_content, encoding="utf-8")
        filenames.append(filename)
        print(f"  Generated: {filename}")

    # Update README
    new_block = build_readme_block(items, filenames)
    updated = re.sub(
        r"<!-- FOCUS:START -->.*?<!-- FOCUS:END -->",
        new_block,
        readme_text,
        flags=re.DOTALL,
    )
    README.write_text(updated, encoding="utf-8")
    print("README.md updated")


if __name__ == "__main__":
    main()
