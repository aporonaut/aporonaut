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
SVG_WIDTH = 838       # fixed width matching GitHub repo content area (smaller of repo/profile)
BASE_HEIGHT = 28      # single-line item height
LINE_HEIGHT_PX = 18   # line spacing for wrapped text
ICON_SIZE = 20
ICON_VIEWBOX = "0 0 24 24"
FONT_SIZE = 14
FONT_FAMILY = "'Segoe UI', Helvetica, Arial, sans-serif"

# Column layout
ICON_PAD = 10                          # padding on left of icon AND between icon and title
ICON_X = ICON_PAD                      # 10px — icon left edge
ICON_TITLE_SEP_X = ICON_PAD + ICON_SIZE + ICON_PAD  # 40 — equal buffer on both sides of icon
TITLE_COL_START = ICON_TITLE_SEP_X + 5              # 45 — small gap after separator

TEXT_AREA = SVG_WIDTH - TITLE_COL_START              # 793px
TITLE_WIDTH = int(TEXT_AREA * 0.25)                  # 198px
TAG_WIDTH = TEXT_AREA - TITLE_WIDTH                  # 595px

COL_TITLE_CENTER = TITLE_COL_START + TITLE_WIDTH // 2                    # ~144
COL_TAG_CENTER = TITLE_COL_START + TITLE_WIDTH + TAG_WIDTH // 2          # ~540

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


def build_svg(name: str, tagline: str, color: str, icon_path_d: str,
              sep_x: int) -> str:
    """Generate an SVG with tabular column layout and balanced separator."""
    title_lines = wrap_text(name, TITLE_WIDTH)
    tag_lines = wrap_text(tagline, TAG_WIDTH)

    max_lines = max(len(title_lines), len(tag_lines), 1)
    svg_height = max(BASE_HEIGHT, (max_lines - 1) * LINE_HEIGHT_PX + BASE_HEIGHT)
    mid_y = svg_height / 2

    def col_start_y(num_lines: int) -> float:
        block_height = (num_lines - 1) * LINE_HEIGHT_PX
        return mid_y - block_height / 2

    title_tspans = _build_column_tspans(title_lines, COL_TITLE_CENTER, "name", col_start_y(len(title_lines)))
    tag_tspans = _build_column_tspans(tag_lines, COL_TAG_CENTER, "tag", col_start_y(len(tag_lines)))

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
  <line class="sep" x1="{ICON_TITLE_SEP_X}" y1="4" x2="{ICON_TITLE_SEP_X}" y2="{svg_height - 4}" stroke-width="1" opacity="0.3"/>
  <line class="sep" x1="{sep_x}" y1="4" x2="{sep_x}" y2="{svg_height - 4}" stroke-width="1" opacity="0.3"/>
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


def calculate_sep_x(items: list[tuple[str, str, str, str]]) -> int:
    """Calculate balanced separator x position across all items."""
    max_title_width = max(estimate_width(name, bold=True) for _, _, name, _ in items)
    max_tag_width = max(estimate_width(tag) for _, _, _, tag in items)

    # Widest title's right edge (centered in title column)
    title_right = COL_TITLE_CENTER + max_title_width / 2
    # Widest tagline's left edge (centered in tagline column)
    tag_left = COL_TAG_CENTER - max_tag_width / 2

    # Separator at midpoint between these edges
    return int((title_right + tag_left) / 2)


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

    # Calculate balanced separator position across all items
    sep_x = calculate_sep_x(items)
    print(f"Separator x: {sep_x}")

    if FOCUS_DIR.exists():
        shutil.rmtree(FOCUS_DIR)
    FOCUS_DIR.mkdir(parents=True)

    filenames = []
    for slug, color, name, tagline in items:
        print(f"  Fetching icon: {slug}")
        icon_path_d = fetch_icon_path(slug)

        svg_content = build_svg(name, tagline, color, icon_path_d, sep_x)
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
