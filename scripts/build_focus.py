"""Build focus section SVGs from config in README.md.

Reads FOCUS:CONFIG comment block from README, fetches SimpleIcons SVGs,
generates combined icon+text SVGs with tabular column layout, and
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
SVG_WIDTH = 846       # fixed width matching GitHub profile content area
BASE_HEIGHT = 28      # single-line item height
LINE_HEIGHT_PX = 18   # line spacing for wrapped text
ICON_SIZE = 20
ICON_VIEWBOX = "0 0 24 24"
FONT_SIZE = 14
FONT_FAMILY = "'Segoe UI', Helvetica, Arial, sans-serif"

# Column definitions: (x_start, width, center_x)
COL_ICON = (0, 30, 15)       # 30px for 20px icon with padding
COL_TITLE = (30, 197, 128)   # 25% of text space
COL_PIPE = (227, 20, 237)    # narrow slot for "|"
COL_TAG = (247, 599, 546)    # 75% of text space

# Rough average char width for wrap estimation (proportional font)
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
    root = ET.fromstring(svg_text)
    path_el = root.find(".//{http://www.w3.org/2000/svg}path")
    if path_el is None:
        path_el = root.find(".//path")
    if path_el is None:
        raise ValueError(f"No <path> found in SimpleIcons SVG for '{slug}'")
    return path_el.get("d")


def _build_column_tspans(lines: list[str], center_x: int, css_class: str,
                         start_y: float) -> str:
    """Build tspan elements for a column, vertically centered."""
    tspans = []
    for i, line in enumerate(lines):
        y = start_y + i * LINE_HEIGHT_PX
        tspans.append(
            f'<tspan class="{css_class}" x="{center_x}" y="{y:.1f}" '
            f'text-anchor="middle" dominant-baseline="central">{line}</tspan>'
        )
    return "\n    ".join(tspans)


def build_svg(name: str, tagline: str, color: str, icon_path_d: str) -> str:
    """Generate an SVG with tabular column layout."""
    # Wrap title and tagline within their column widths
    title_lines = wrap_text(name, COL_TITLE[1])
    tag_lines = wrap_text(tagline, COL_TAG[1])

    # SVG height based on tallest column
    max_lines = max(len(title_lines), len(tag_lines), 1)
    svg_height = max(BASE_HEIGHT, (max_lines - 1) * LINE_HEIGHT_PX + BASE_HEIGHT)
    mid_y = svg_height / 2

    # Vertical start y for each column (centered on midline)
    def col_start_y(num_lines: int) -> float:
        block_height = (num_lines - 1) * LINE_HEIGHT_PX
        return mid_y - block_height / 2

    # Build tspans for each column
    title_tspans = _build_column_tspans(title_lines, COL_TITLE[2], "name", col_start_y(len(title_lines)))
    pipe_tspan = (
        f'<tspan class="sep" x="{COL_PIPE[2]}" y="{mid_y:.1f}" '
        f'text-anchor="middle" dominant-baseline="central">|</tspan>'
    )
    tag_tspans = _build_column_tspans(tag_lines, COL_TAG[2], "tag", col_start_y(len(tag_lines)))

    # Icon vertically centered
    icon_x = COL_ICON[2] - ICON_SIZE // 2  # center icon in column
    icon_y = int(mid_y - ICON_SIZE / 2)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{svg_height}" viewBox="0 0 {SVG_WIDTH} {svg_height}">
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
  <svg x="{icon_x}" y="{icon_y}" width="{ICON_SIZE}" height="{ICON_SIZE}" viewBox="{ICON_VIEWBOX}">
    <path d="{icon_path_d}" fill="#{color}"/>
  </svg>
  <text>
    {title_tspans}
    {pipe_tspan}
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
