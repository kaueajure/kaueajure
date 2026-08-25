import re
import sys
from pathlib import Path

# Keep the original contribution animation in the first part of the loop.
PHASE = 0.74
STOP_X = 520
GRID_W = 848
GRID_H = 112
FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "J": ["11111", "00100", "00100", "00100", "00100", "10100", "01100"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
}


def letter_targets():
    """Return targets grouped by letter, positioned to the left of the stopped snake."""
    pitch = 11
    size = 9
    gap = 2
    x0 = 250
    y0 = 12
    groups = []
    offset = 0

    for ch in "AJR":
        pts = []
        for row, line in enumerate(FONT[ch]):
            for col, bit in enumerate(line):
                if bit == "1":
                    pts.append((x0 + (offset + col) * pitch, y0 + row * pitch))
        groups.append(pts)
        offset += 5 + gap

    return groups, size


def stop_snake_keyframes(style):
    """Freeze each snake segment while it is returning from right to left, before center."""
    stops = [STOP_X, STOP_X + 16, STOP_X + 32, STOP_X + 48]

    for idx, stop_x in enumerate(stops):
        pattern = re.compile(rf"@keyframes s{idx}\{{(.*?)\}}(?=\.s\.s{idx})")
        match = pattern.search(style)
        if not match:
            continue

        body = match.group(1)
        frames = []
        for fm in re.finditer(r"([\d.,%]+)\{transform:translate\((-?\d+(?:\.\d+)?)px,(-?\d+(?:\.\d+)?)px\)\}", body):
            percentages = [float(p.replace('%', '')) for p in fm.group(1).split(',')]
            frames.append((percentages, float(fm.group(2)), float(fm.group(3)), fm.group(0)))

        # Find the long return section after the snake has reached the far-right side.
        crossing = None
        seen_right = False
        prev = None
        for percentages, x, y, raw in frames:
            p = max(percentages)
            if x >= 780:
                seen_right = True
            if seen_right and prev is not None:
                pp, px, py = prev
                if px > stop_x >= x and x < px:
                    ratio = (px - stop_x) / (px - x)
                    cp = pp + (p - pp) * ratio
                    cy = py + (y - py) * ratio
                    crossing = (cp, cy)
                    break
            prev = (p, x, y)

        if crossing is None:
            continue

        cp, cy = crossing
        new_parts = []
        for percentages, x, y, raw in frames:
            if max(percentages) < cp:
                new_parts.append(raw)

        # Hold the segment at the stop point through the custom finale.
        new_parts.append(f"{cp:.2f}%{{transform:translate({stop_x}px,{cy:.1f}px)}}")
        new_parts.append(f"100%{{transform:translate({stop_x}px,{cy:.1f}px)}}")
        new_body = ''.join(new_parts)
        style = style[:match.start(1)] + new_body + style[match.end(1):]

    return style


def build_css(ms, groups):
    css = [
        f".ajr-dot{{opacity:0;fill:var(--cs);animation-duration:{ms}ms;animation-timing-function:cubic-bezier(.22,.75,.3,1);animation-iteration-count:infinite;transform-box:fill-box;transform-origin:center}}",
    ]

    # A, then J, then R. Each letter gets its own time window.
    windows = [(75.2, 81.0), (82.0, 87.8), (88.8, 94.6)]
    mouth_x, mouth_y = STOP_X - 4, 40

    counter = 0
    for letter_index, pts in enumerate(groups):
        start_window, end_window = windows[letter_index]
        n = max(1, len(pts))
        span = end_window - start_window

        for local_i, (tx, ty) in enumerate(pts):
            start = start_window + (local_i / n) * (span * 0.72)
            arc = start + 0.65
            arrive = min(end_window, start + 1.75)
            hold = 97.0
            fade = 99.0

            # All dots leave from the mouth toward the left, with a small upward/downward arc.
            arc_dx = -28 - (local_i % 3) * 5
            arc_dy = (-10, -3, 5, 10)[local_i % 4]
            dx = tx - mouth_x
            dy = ty - mouth_y

            css.append(
                f".ajr-{counter}{{animation-name:ajr-{counter}}}"
                f"@keyframes ajr-{counter}{{"
                f"0%,{start - 0.04:.2f}%{{opacity:0;transform:translate(0px,0px) scale(.45)}}"
                f"{start:.2f}%{{opacity:1;transform:translate(-3px,0px) scale(.65)}}"
                f"{arc:.2f}%{{opacity:1;transform:translate({arc_dx}px,{arc_dy}px) scale(.9)}}"
                f"{arrive:.2f}%,{hold:.2f}%{{opacity:1;transform:translate({dx}px,{dy}px) scale(1)}}"
                f"{fade:.2f}%,100%{{opacity:0;transform:translate({dx}px,{dy}px) scale(.85)}}"
                f"}}"
            )
            counter += 1

    return ''.join(css)


def build_overlay(groups, size):
    mouth_x, mouth_y = STOP_X - 4, 40
    parts = ['<g id="ajr-finale" pointer-events="none">']
    counter = 0
    for pts in groups:
        for _ in pts:
            parts.append(
                f'<rect class="ajr-dot ajr-{counter}" x="{mouth_x}" y="{mouth_y}" width="{size}" height="{size}" rx="2"/>'
            )
            counter += 1
    parts.append('</g>')
    return ''.join(parts)


def clip_snake(svg):
    """Keep the snake visually inside the contribution grid."""
    clip = f'<defs><clipPath id="snake-grid-clip"><rect x="0" y="0" width="{GRID_W}" height="{GRID_H}"/></clipPath></defs>'
    svg = svg.replace('</desc>', '</desc>' + clip, 1)

    matches = list(re.finditer(r'<rect class="s s\d"[^>]*/>', svg))
    if matches:
        start = matches[0].start()
        end = matches[-1].end()
        snake_markup = svg[start:end]
        svg = svg[:start] + '<g clip-path="url(#snake-grid-clip)">' + snake_markup + '</g>' + svg[end:]
    return svg


def patch(path):
    p = Path(path)
    svg = p.read_text()

    match = re.search(r"animation:none\s+(\d+)ms", svg)
    if not match:
        raise RuntimeError(f"Could not find snk animation duration in {path}")

    old = int(match.group(1))
    new = round(old / PHASE)
    groups, size = letter_targets()

    style_start = svg.index('<style>') + len('<style>')
    style_end = svg.index('</style>')
    style = svg[style_start:style_end].replace(f'{old}ms', f'{new}ms')

    # Compress original snk timing to make room for the custom finale.
    def scale_percent(match):
        value = float(match.group(1))
        if value >= 99.999:
            return '100%'
        scaled = value * PHASE
        return f'{scaled:.2f}'.rstrip('0').rstrip('.') + '%'

    style = re.sub(r"(?<![\w.-])(\d+(?:\.\d+)?)%", scale_percent, style)
    style = stop_snake_keyframes(style)
    style += build_css(new, groups)

    svg = svg[:style_start] + style + svg[style_end:]
    svg = clip_snake(svg)
    svg = svg.replace('</svg>', build_overlay(groups, size) + '</svg>')
    p.write_text(svg)


for filename in sys.argv[1:]:
    patch(filename)
