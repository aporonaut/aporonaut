"""Build marquee SVGs from full-color icon assets.

Embeds complete icon SVGs (gradients, multi-path, backgrounds) into
animated marquee strips using <symbol> + <use> for efficiency.
Generates separate dark/light theme variants per marquee row.
Handles ID namespacing and CSS-to-inline conversion.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"
OUTPUT_DIR = Path(__file__).parent.parent / "assets" / "marquees"

ICON_SIZE = 44
ICON_SPACING = 56
SVG_HEIGHT = 52
PADDING_Y = (SVG_HEIGHT - ICON_SIZE) // 2

# ── Icon manifest ──────────────────────────────────────────────────────────
# Each entry: (slug, dark_file, light_file)
# Single-file icons use same filename for both. Dark/Light only where content differs.

MARQUEE_AI = [
    ("python",      "Python.svg",            "Python.svg"),
    ("pytorch",     "PyTorch.svg",           "PyTorch.svg"),
    ("tensorflow",  "TensorFlow.svg",        "TensorFlow.svg"),
    ("huggingface", "Huggingface.svg",       "Huggingface.svg"),
    ("numpy",       "Numpy.svg",             "Numpy.svg"),
    ("jupyter",     "Jupyter-Dark.svg",      "Jupyter-Light.svg"),
    ("anaconda",    "Anaconda.svg",          "Anaconda.svg"),
    ("cuda",        "Cuda.svg",              "Cuda.svg"),
]

MARQUEE_INFRA = [
    ("docker",      "Docker.svg",            "Docker.svg"),
    ("linux",       "Linux.svg",             "Linux.svg"),
    ("bash",        "Bash-Dark.svg",         "Bash-Light.svg"),
    ("powershell",  "Powershell.svg",        "Powershell.svg"),
    ("git",         "Git.svg",               "Git.svg"),
    ("github",      "Github-Dark.svg",       "Github-Light.svg"),
    ("postgresql",  "PostgreSQL.svg",        "PostgreSQL.svg"),
    ("django",      "Django.svg",            "Django.svg"),
]

MARQUEE_TOOLS = [
    ("vscode",      "VSCode.svg",            "VSCode.svg"),
    ("uv",          "Uv.svg",               "Uv.svg"),
    ("claude",      "claude.svg",            "claude.svg"),
    ("latex",       "LaTeX-Dark.svg",        "LaTeX-Light.svg"),
    ("matlab",      "Matlab.svg",            "Matlab.svg"),
    ("arch",        "Arch.svg",              "Arch.svg"),
    ("elastic",     "Elasticsearch.svg",     "Elasticsearch.svg"),
    ("qdrant",      "Qdrant.svg",            "Qdrant.svg"),
]


def parse_svg(filepath: Path) -> ET.Element:
    """Parse SVG file, handling namespace declarations."""
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    tree = ET.parse(filepath)
    return tree.getroot()


def get_viewbox(root: ET.Element) -> tuple[float, float, float, float]:
    """Extract viewBox as (x, y, w, h)."""
    vb = root.get("viewBox", "")
    if vb:
        parts = vb.split()
        return tuple(float(p) for p in parts)
    w = float(root.get("width", "256").replace("px", ""))
    h = float(root.get("height", "256").replace("px", ""))
    return (0, 0, w, h)


def namespace_ids(content: str, prefix: str) -> str:
    """Prefix all id definitions and references to avoid collisions."""
    ids_found = re.findall(r'id="([^"]+)"', content)
    for old_id in set(ids_found):
        new_id = f"{prefix}-{old_id}"
        content = content.replace(f'id="{old_id}"', f'id="{new_id}"')
        content = content.replace(f"url(#{old_id})", f"url(#{new_id})")
        content = content.replace(f'href="#{old_id}"', f'href="#{new_id}"')
        content = content.replace(
            f'xlink:href="#{old_id}"', f'xlink:href="#{new_id}"'
        )
    return content


def inline_css_classes(content: str, prefix: str) -> str:
    """Convert <style> class-based fills to inline fill attributes."""
    style_match = re.search(r"<style[^>]*>(.*?)</style>", content, re.DOTALL)
    if not style_match:
        return content

    style_text = style_match.group(1)
    class_fills = {}
    for m in re.finditer(r"\.(\w[\w-]*)\s*\{[^}]*fill:\s*([^;}\s]+)", style_text):
        class_fills[m.group(1)] = m.group(2)

    content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)

    for cls_name, fill_val in class_fills.items():
        content = re.sub(
            rf'class="{cls_name}"',
            f'fill="{fill_val}"',
            content,
        )

    return content


def inline_style_attrs(content: str) -> str:
    """Convert style="fill:..." to fill="..." attributes."""
    def replace_style(m):
        style_val = m.group(1)
        fill_match = re.search(r"fill:\s*([^;\"]+)", style_val)
        if fill_match:
            return f'fill="{fill_match.group(1).strip()}"'
        return m.group(0)

    return re.sub(r'style="([^"]*)"', replace_style, content)


def extract_inner_content(svg_text: str) -> str:
    """Extract everything between the root <svg> tags."""
    svg_text = re.sub(r"<\?xml[^?]*\?>", "", svg_text).strip()
    svg_text = re.sub(r"<!--.*?-->", "", svg_text, flags=re.DOTALL).strip()
    match = re.search(r"<svg[^>]*>(.*)</svg>", svg_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return svg_text


def process_icon(filepath: Path, slug: str, theme: str) -> tuple[str, str]:
    """Process a single icon SVG file.

    Returns (defs_content, symbol_content) where:
    - defs_content: extracted gradient/clipPath definitions (namespaced)
    - symbol_content: the full <symbol> element
    """
    prefix = f"{slug}-{theme}"
    svg_text = filepath.read_text(encoding="utf-8")

    root = parse_svg(filepath)
    vb = get_viewbox(root)

    inner = extract_inner_content(svg_text)
    inner = inline_css_classes(inner, prefix)
    inner = inline_style_attrs(inner)
    inner = namespace_ids(inner, prefix)

    # Separate <defs> content from the rest
    defs_parts = []
    def extract_defs(m):
        defs_parts.append(m.group(1))
        return ""

    inner = re.sub(r"<defs>(.*?)</defs>", extract_defs, inner, flags=re.DOTALL)
    defs_content = "\n".join(defs_parts)

    # Remove any title elements
    inner = re.sub(r"<title>[^<]*</title>", "", inner)

    symbol = (
        f'  <symbol id="ico-{prefix}" viewBox="0 0 {vb[2]:.0f} {vb[3]:.0f}">\n'
        f"    {inner}\n"
        f"  </symbol>"
    )

    return defs_content, symbol


def build_marquee(
    icons: list[tuple[str, str, str]],
    theme: str,
    animation_name: str,
    direction: str,
    duration: int,
    output_path: Path,
):
    """Build a single-theme marquee SVG from the icon manifest."""
    num_icons = len(icons)
    set_width = num_icons * ICON_SPACING

    all_defs = []
    all_symbols = []

    for slug, dark_file, light_file in icons:
        filepath = ICONS_DIR / (dark_file if theme == "dark" else light_file)

        if filepath.exists():
            defs, symbol = process_icon(filepath, slug, theme)
            all_defs.append(defs)
            all_symbols.append(symbol)

    # Build animation CSS
    if direction == "left":
        anim_from = "0"
        anim_to = f"-{set_width}"
    else:
        anim_from = f"-{set_width}"
        anim_to = "0"

    css = f"""    @keyframes {animation_name} {{
      from {{ transform: translateX({anim_from}px); }}
      to {{ transform: translateX({anim_to}px); }}
    }}
    .marquee {{
      animation: {animation_name} {duration}s linear infinite;
    }}"""

    # Build icon placement — two copies for seamless loop
    placements = []
    for set_idx in [0, set_width]:
        for i, (slug, _dark_file, _light_file) in enumerate(icons):
            x = PADDING_Y + i * ICON_SPACING + set_idx
            icon_id = f"ico-{slug}-{theme}"
            placements.append(
                f'    <use href="#{icon_id}" x="{x}" y="{PADDING_Y}" '
                f'width="{ICON_SIZE}" height="{ICON_SIZE}"/>'
            )

    # Assemble the final SVG
    defs_block = "\n".join(d for d in all_defs if d.strip())
    symbols_block = "\n".join(all_symbols)
    placements_block = "\n".join(placements)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {set_width} {SVG_HEIGHT}" fill="none">
  <style>
{css}
  </style>

  <defs>
{defs_block}
{symbols_block}
  </defs>

  <g class="marquee">
{placements_block}
  </g>
</svg>
"""

    output_path.write_text(svg, encoding="utf-8")
    size_kb = output_path.stat().st_size / 1024
    print(f"  {output_path.name}: {num_icons} icons, {size_kb:.1f} KB")


def main():
    """Build all marquee SVGs."""
    print("Building marquee SVGs...")
    print()

    rows = [
        (MARQUEE_AI, "scroll-left", "left", 30, "marquee-ai"),
        (MARQUEE_INFRA, "scroll-right", "right", 35, "marquee-infra"),
        (MARQUEE_TOOLS, "scroll-left-tools", "left", 28, "marquee-tools"),
    ]

    for icons, anim_name, direction, duration, basename in rows:
        for theme in ("dark", "light"):
            build_marquee(
                icons,
                theme=theme,
                animation_name=anim_name,
                direction=direction,
                duration=duration,
                output_path=OUTPUT_DIR / f"{basename}-{theme}.svg",
            )

    print()
    print("Done.")


if __name__ == "__main__":
    main()
