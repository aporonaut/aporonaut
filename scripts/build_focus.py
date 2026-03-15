"""Build focus section SVGs from config in README.md.

Reads FOCUS:CONFIG comment block from README, fetches SimpleIcons SVGs,
generates combined icon+text SVGs with algebraically balanced column layout,
and updates the README with <img> tags pointing to the generated files.
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
SVG_WIDTH = 838       # fixed width matching GitHub repo content area
BASE_HEIGHT = 28      # single-line item height
LINE_HEIGHT_PX = 18   # line spacing for wrapped text
ICON_SIZE = 20
ICON_VIEWBOX = "0 0 24 24"
FONT_SIZE = 14
FONT_FAMILY = "'Segoe UI', Helvetica, Arial, sans-serif"

# Icon positioning
ICON_PAD = 10
ICON_X = ICON_PAD                      # 10px — icon left edge
ICON_RIGHT = ICON_X + ICON_SIZE        # 30px — icon right edge

# Initial column widths for first-pass wrapping (25%/75% of text area)
INIT_TITLE_WIDTH = int((SVG_WIDTH - ICON_RIGHT - ICON_PAD) * 0.25)
INIT_TAG_WIDTH = int((SVG_WIDTH - ICON_RIGHT - ICON_PAD) * 0.75)

# Per-character width table for Segoe UI at 14px (approximate font metrics)
CHAR_WIDTHS = {
    ' ': 3.5,
    'a': 7.7, 'b': 7.9, 'c': 6.5, 'd': 7.9, 'e': 7.3,
    'f': 4.5, 'g': 7.9, 'h': 7.8, 'i': 3.2, 'j': 3.8,
    'k': 7.0, 'l': 3.2, 'm': 11.8, 'n': 7.8, 'o': 7.9,
    'p': 7.9, 'q': 7.9, 'r': 5.0, 's': 6.3, 't': 4.8,
    'u': 7.8, 'v': 7.0, 'w': 10.2, 'x': 6.8, 'y': 7.0,
    'z': 6.3,
    'A': 8.8, 'B': 8.0, 'C': 7.8, 'D': 9.0, 'E': 7.3,
    'F': 6.8, 'G': 8.8, 'H': 9.2, 'I': 3.5, 'J': 5.5,
    'K': 8.0, 'L': 7.0, 'M': 10.8, 'N': 9.2, 'O': 9.3,
    'P': 7.8, 'Q': 9.3, 'R': 8.2, 'S': 7.3, 'T': 7.5,
    'U': 9.0, 'V': 8.5, 'W': 12.0, 'X': 8.0, 'Y': 7.8,
    'Z': 7.8,
    '-': 4.5, '.': 3.5, ',': 3.5, "'": 3.0,
}
DEFAULT_CHAR_WIDTH = 7.0
BOLD_MULTIPLIER = 1.0


def estimate_width(text: str, bold: bool = False) -> float:
    """Estimate pixel width using per-character lookup table."""
    width = sum(CHAR_WIDTHS.get(c, DEFAULT_CHAR_WIDTH) for c in text)
    return width * BOLD_MULTIPLIER if bold else width


def wrap_text(text: str, max_width: float) -> list[str]:
    """Split text into lines that fit within max_width pixels."""
    words = text.split()
    lines, current = [], []
    current_width = 0.0
    for word in words:
        word_width = estimate_width(word)
        space_width = CHAR_WIDTHS[' '] if current else 0
        if current and current_width + space_width + word_width > max_width:
            lines.append(" ".join(current))
            current, current_width = [word], word_width
        else:
            current.append(word)
            current_width += space_width + word_width
    if current:
        lines.append(" ".join(current))
    return lines


def max_line_width(text: str, col_width: float, bold: bool = False) -> float:
    """Get the estimated width of the widest line after wrapping."""
    lines = wrap_text(text, col_width)
    return max(estimate_width(line, bold) for line in lines)


def solve_layout(items: list[tuple[str, str, str, str]]) -> dict:
    """Solve for balanced separator and column center positions.

    System of equations:
      sep1 = midpoint(icon_right, title_left)
      title_center = midpoint(sep1, sep2)
      sep2 = midpoint(title_right, tag_left)
      tag_center = midpoint(sep2, SVG_WIDTH)

    Solved algebraically for sep1, sep2, title_center, tag_center.
    """
    R = ICON_RIGHT  # 30
    W = SVG_WIDTH   # 838

    # Pass 1: wrap with initial estimates, find max line widths
    max_t = max(max_line_width(name, INIT_TITLE_WIDTH, bold=True)
                for _, _, name, _ in items)
    max_g = max(max_line_width(tag, INIT_TAG_WIDTH, bold=False)
                for _, _, _, tag in items)

    T = max_t / 2  # half-width of widest title line
    G = max_g / 2  # half-width of widest tagline line

    # Solve
    sep2 = (2 * R + 4 * T + 3 * W - 6 * G) / 5
    sep1 = (2 * R + sep2 - 2 * T) / 3
    title_center = (sep1 + sep2) / 2
    tag_center = (sep2 + W) / 2

    # Column widths for wrapping (space between separators / edges)
    title_col_width = sep2 - sep1
    tag_col_width = W - sep2

    return {
        "sep1": int(sep1),
        "sep2": int(sep2),
        "title_center": int(title_center),
        "tag_center": int(tag_center),
        "title_col_width": title_col_width,
        "tag_col_width": tag_col_width,
    }


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


def build_svg(name: str, tagline: str, color: str, icon_path_d: str,
              layout: dict) -> str:
    """Generate an SVG with algebraically balanced column layout."""
    sep1 = layout["sep1"]
    sep2 = layout["sep2"]
    tc = layout["title_center"]
    gc = layout["tag_center"]

    title_lines = wrap_text(name, layout["title_col_width"])
    tag_lines = wrap_text(tagline, layout["tag_col_width"])

    max_lines = max(len(title_lines), len(tag_lines), 1)
    svg_height = max(BASE_HEIGHT, (max_lines - 1) * LINE_HEIGHT_PX + BASE_HEIGHT)
    mid_y = svg_height / 2

    def col_start_y(num_lines: int) -> float:
        block_height = (num_lines - 1) * LINE_HEIGHT_PX
        return mid_y - block_height / 2

    title_tspans = _build_column_tspans(title_lines, tc, "name", col_start_y(len(title_lines)))
    tag_tspans = _build_column_tspans(tag_lines, gc, "tag", col_start_y(len(tag_lines)))

    icon_y = int(mid_y - ICON_SIZE / 2)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{svg_height}" viewBox="0 0 {SVG_WIDTH} {svg_height}">
  <style>
    .name {{ font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}px; font-weight: 600; }}
    .tag  {{ font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}px; }}
    @media (prefers-color-scheme: dark) {{
      .name, .tag {{ fill: #E6EDF3; }}
      .sep {{ stroke: #E6EDF3; }}
    }}
    @media (prefers-color-scheme: light) {{
      .name, .tag {{ fill: #1F2328; }}
      .sep {{ stroke: #1F2328; }}
    }}
  </style>
  <svg x="{ICON_X}" y="{icon_y}" width="{ICON_SIZE}" height="{ICON_SIZE}" viewBox="{ICON_VIEWBOX}">
    <path d="{icon_path_d}" fill="#{color}"/>
  </svg>
  <line class="sep" x1="{sep2}" y1="4" x2="{sep2}" y2="{svg_height - 4}" stroke-width="1" opacity="0.3"/>
  <text>
    {title_tspans}
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

    # Solve balanced layout from content widths
    layout = solve_layout(items)
    print(f"Layout: sep1={layout['sep1']}, sep2={layout['sep2']}, "
          f"title@{layout['title_center']}, tag@{layout['tag_center']}")

    if FOCUS_DIR.exists():
        shutil.rmtree(FOCUS_DIR)
    FOCUS_DIR.mkdir(parents=True)

    filenames = []
    for slug, color, name, tagline in items:
        print(f"  Fetching icon: {slug}")
        icon_path_d = fetch_icon_path(slug)

        svg_content = build_svg(name, tagline, color, icon_path_d, layout)
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
