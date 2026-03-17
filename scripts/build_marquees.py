"""Build marquee SVGs from config in README.md.

Reads MARQUEE:CONFIG comment block from README, resolves icon files
from assets/icons/ using case-insensitive fuzzy matching, generates
animated marquee strips with dark/light theme variants, and updates
the README with <picture> tags pointing to the generated files.
"""

import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"
ICONS_DIR = ROOT / "assets" / "icons"
OUTPUT_DIR = ROOT / "assets" / "marquees"

ICON_SIZE = 44
ICON_SPACING = 56
SVG_HEIGHT = 52
PADDING_Y = (SVG_HEIGHT - ICON_SIZE) // 2


# ── Icon index ────────────────────────────────────────────────────────────


def build_icon_index(icons_dir: Path) -> dict[str, tuple[str, str]]:
    """Build case-insensitive lookup from slug to (dark_file, light_file).

    Scans the icons directory and groups files by base name (stripping
    -Dark/-Light suffixes). Single-file icons map to the same filename
    for both themes. When both a single file and dark/light variants
    exist, the variants take precedence.
    """
    singles: dict[str, str] = {}
    darks: dict[str, str] = {}
    lights: dict[str, str] = {}

    for f in sorted(icons_dir.glob("*.svg")):
        name = f.stem  # e.g. "Bash-Dark", "Python", "microsoft-outlook"

        if name.endswith("-Dark"):
            base = name[:-5]  # strip "-Dark"
            darks[base.lower()] = f.name
        elif name.endswith("-Light"):
            base = name[:-6]  # strip "-Light"
            lights[base.lower()] = f.name
        else:
            singles[name.lower()] = f.name

    index: dict[str, tuple[str, str]] = {}

    # Add single-file icons (same file for both themes)
    for key, filename in singles.items():
        index[key] = (filename, filename)

    # Override with dark/light variants where both exist
    all_variant_keys = set(darks.keys()) | set(lights.keys())
    for key in all_variant_keys:
        dark = darks.get(key)
        light = lights.get(key)
        if dark and light:
            index[key] = (dark, light)
        elif dark:
            # Only dark variant exists, use it for both
            index[key] = (dark, dark)
        elif light:
            # Only light variant exists, use it for both
            index[key] = (light, light)

    return index


# ── Config parsing ────────────────────────────────────────────────────────


def parse_config(readme_text: str) -> list[tuple[str, str, list[str]]]:
    """Parse MARQUEE:CONFIG block from README.

    Returns list of (title, alt_text, icon_slugs) tuples.
    """
    match = re.search(
        r"<!-- MARQUEE:CONFIG\s*\n(.*?)\n\s*MARQUEE:CONFIG -->",
        readme_text,
        re.DOTALL,
    )
    if not match:
        print("ERROR: No MARQUEE:CONFIG block found in README.md")
        sys.exit(1)

    rows = []
    for line in match.group(1).strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            raise ValueError(
                f"Invalid config line (need title,alt_text,icon1,...): {line}"
            )
        title, alt_text = parts[0], parts[1]
        icon_slugs = parts[2:]
        rows.append((title, alt_text, icon_slugs))

    return rows


def resolve_icons(
    icon_slugs: list[str], icon_index: dict[str, tuple[str, str]]
) -> list[tuple[str, str, str]]:
    """Resolve icon slugs to (slug, dark_file, light_file) tuples."""
    resolved = []
    errors = []

    for slug in icon_slugs:
        key = slug.lower()
        if key in icon_index:
            dark, light = icon_index[key]
            resolved.append((slug, dark, light))
        else:
            errors.append(slug)

    if errors:
        available = sorted(icon_index.keys())
        print(f"ERROR: Unresolved icons: {', '.join(errors)}")
        print(f"Available: {', '.join(available)}")
        sys.exit(1)

    return resolved


# ── SVG processing (unchanged) ───────────────────────────────────────────


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


# ── README updating ──────────────────────────────────────────────────────


def build_readme_block(
    rows: list[tuple[str, str, list[str]]],
) -> str:
    """Generate the MARQUEE:START/END block with <picture> elements."""
    parts = []
    for title, alt_text, _icons in rows:
        parts.append(
            f"  <picture>\n"
            f'    <source media="(prefers-color-scheme: dark)" '
            f'srcset="assets/marquees/marquee-{title}-dark.svg" />\n'
            f'    <img src="assets/marquees/marquee-{title}-light.svg" '
            f'width="100%" alt="{alt_text}" />\n'
            f"  </picture>"
        )
    inner = "\n  <br />\n".join(parts)
    return f"<!-- MARQUEE:START -->\n{inner}\n<!-- MARQUEE:END -->"


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    """Build all marquee SVGs from README config."""
    print("Building marquee SVGs...")
    print()

    readme_text = README.read_text(encoding="utf-8")
    rows = parse_config(readme_text)
    icon_index = build_icon_index(ICONS_DIR)

    # Clean output directory
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    for i, (title, _alt_text, icon_slugs) in enumerate(rows):
        icons = resolve_icons(icon_slugs, icon_index)
        direction = "left" if i % 2 == 0 else "right"
        duration = int(len(icons) * 3.5)
        anim_name = f"scroll-{title}"

        for theme in ("dark", "light"):
            build_marquee(
                icons,
                theme=theme,
                animation_name=anim_name,
                direction=direction,
                duration=duration,
                output_path=OUTPUT_DIR / f"marquee-{title}-{theme}.svg",
            )

    # Update README
    new_block = build_readme_block(rows)
    updated = re.sub(
        r"<!-- MARQUEE:START -->.*?<!-- MARQUEE:END -->",
        new_block,
        readme_text,
        flags=re.DOTALL,
    )
    README.write_text(updated, encoding="utf-8")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
