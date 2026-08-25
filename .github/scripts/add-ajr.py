import re
import sys
from pathlib import Path

# Reserve the last ~26% of the loop for the custom AJR finale.
PHASE = 0.74
FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "J": ["11111", "00100", "00100", "00100", "00100", "10100", "01100"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
}


def targets():
    out = []
    pitch, size, gap = 13, 10, 2
    cols = 19
    x0 = round((848 - ((cols - 1) * pitch + size)) / 2)
    y0 = 10
    offset = 0

    for ch in "AJR":
        for row, line in enumerate(FONT[ch]):
            for col, bit in enumerate(line):
                if bit == "1":
                    out.append((x0 + (offset + col) * pitch, y0 + row * pitch))
        offset += 5 + gap

    return out


def build_css(ms, pts):
    ox, oy = 76, 48
    css = [
        f".ajr-head{{opacity:0;animation:ajr-head {ms}ms linear infinite}}",
        "@keyframes ajr-head{0%,73.5%{opacity:0}74.5%,81.5%{opacity:1}83%,100%{opacity:0}}",
        f".ajr-dot{{opacity:0;fill:var(--cs);animation-duration:{ms}ms;animation-timing-function:linear;animation-iteration-count:infinite}}",
    ]

    for i, (tx, ty) in enumerate(pts):
        # Slight stagger makes the blocks look like they are being spat out one after another.
        start = 75.0 + (i % 12) * 0.28
        spray = start + 2.2
        arrive = min(89.5, 84.0 + (i / max(1, len(pts) - 1)) * 5.5)
        hold = 96.0
        fade = 98.0

        # Fan the blocks out before they settle into the letters.
        mx = 70 + (i % 9) * 16
        my = -44 + (i % 8) * 13
        dx = tx - ox
        dy = ty - oy
        angle = -22 + (i % 9) * 5

        css.append(
            f".ajr-{i}{{animation-name:ajr-{i}}}"
            f"@keyframes ajr-{i}{{"
            f"0%,{start - 0.05:.2f}%{{opacity:0;transform:translate(0px,0px) scale(.35)}}"
            f"{start:.2f}%{{opacity:1;transform:translate(0px,0px) scale(.55)}}"
            f"{spray:.2f}%{{opacity:1;transform:translate({mx}px,{my}px) rotate({angle}deg) scale(.85)}}"
            f"{arrive:.2f}%,{hold:.2f}%{{opacity:1;transform:translate({dx}px,{dy}px) rotate(0deg) scale(1)}}"
            f"{fade:.2f}%,100%{{opacity:0;transform:translate({dx}px,{dy}px) scale(.75)}}"
            f"}}"
        )

    return "".join(css)


def build_overlay(pts):
    ox, oy = 76, 48
    parts = [
        '<g id="ajr-finale" pointer-events="none">',
        f'<g class="ajr-head" transform="translate({ox} {oy})">',
        '<circle r="10" fill="var(--cs)"/>',
        '<circle cx="3" cy="-3" r="2" fill="#fff"/>',
        '<circle cx="3.6" cy="-3" r=".8" fill="#1f2328"/>',
        '</g>',
    ]

    for i, _ in enumerate(pts):
        parts.append(
            f'<rect class="ajr-dot ajr-{i}" x="{ox}" y="{oy}" width="10" height="10" rx="2"/>'
        )

    parts.append('</g>')
    return "".join(parts)


def patch(path):
    p = Path(path)
    svg = p.read_text()

    match = re.search(r"animation:none\s+(\d+)ms", svg)
    if not match:
        raise RuntimeError(f"Could not find snk animation duration in {path}")

    old = int(match.group(1))
    new = round(old / PHASE)
    pts = targets()

    style_start = svg.index("<style>") + len("<style>")
    style_end = svg.index("</style>")
    style = svg[style_start:style_end].replace(f"{old}ms", f"{new}ms")

    # Compress all original snk keyframes into the first 74% of the new loop.
    def scale_percent(match):
        value = float(match.group(1))
        if value >= 99.999:
            return "100%"
        scaled = value * PHASE
        return f"{scaled:.2f}".rstrip("0").rstrip(".") + "%"

    style = re.sub(r"(?<![\w.-])(\d+(?:\.\d+)?)%", scale_percent, style)
    style += build_css(new, pts)

    svg = svg[:style_start] + style + svg[style_end:]
    svg = svg.replace("</svg>", build_overlay(pts) + "</svg>")
    p.write_text(svg)


for filename in sys.argv[1:]:
    patch(filename)
