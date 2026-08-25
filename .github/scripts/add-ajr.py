import re
import sys
from pathlib import Path

PHASE = 0.55

GRID_COLS = 53
GRID_ROWS = 7
GRID_PITCH = 16
GRID_W = GRID_COLS * GRID_PITCH
GRID_H = GRID_ROWS * GRID_PITCH

STOP_X = 624
STOP_Y = 48

SPIT_WINDOWS = [(58.0, 64.0), (65.0, 71.0), (72.0, 78.0)]
HOLD_END = 82.0
EAT_START = 82.5
EAT_END = 96.0
EXIT_END = 99.4
CLEAR_START = 57.4

FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "J": ["11111", "00100", "00100", "00100", "00100", "10100", "01100"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
}


def letter_targets():
    """AJR aligned to GitHub's 16px grid and centered in the calendar."""
    letter_cols = 5
    gap_cols = 2
    total_cols = letter_cols * 3 + gap_cols * 2
    start_col = (GRID_COLS - total_cols) // 2

    groups = []
    global_index = 0
    offset = 0

    for ch in "AJR":
        pts = []
        for row, line in enumerate(FONT[ch]):
            for col, bit in enumerate(line):
                if bit != "1":
                    continue
                grid_col = start_col + offset + col
                x = 2 + grid_col * GRID_PITCH
                y = 2 + row * GRID_PITCH
                pts.append((global_index, x, y))
                global_index += 1
        groups.append(pts)
        offset += letter_cols + gap_cols

    return groups


def active_cells(svg):
    cells = []
    pattern = re.compile(
        r'<rect class="c ([^"]+)" x="(\d+(?:\.\d+)?)" y="(\d+(?:\.\d+)?)" rx="2" ry="2"/>'
    )
    for match in pattern.finditer(svg):
        cells.append((float(match.group(2)), float(match.group(3))))
    return cells


def build_complete_grid():
    parts = ['<g id="complete-grid" pointer-events="none">']
    for col in range(GRID_COLS):
        for row in range(GRID_ROWS):
            x = 2 + col * GRID_PITCH
            y = 2 + row * GRID_PITCH
            parts.append(
                f'<rect class="grid-slot" x="{x}" y="{y}" width="12" height="12" rx="2" ry="2"/>'
            )
    parts.append('</g>')
    return ''.join(parts)


def build_final_clear(cells):
    parts = ['<g id="final-consumption-check" pointer-events="none">']
    for x, y in cells:
        parts.append(
            f'<rect class="final-clear" x="{x:g}" y="{y:g}" width="12" height="12" rx="2" ry="2"/>'
        )
    parts.append('</g>')
    return ''.join(parts)


def latest_contribution_consumption(style):
    values = []
    for match in re.finditer(
        r'@keyframes c[\w]+\{.*?(\d+(?:\.\d+)?)%,100%\{fill:var\(--ce\)\}\}',
        style,
    ):
        values.append(float(match.group(1)))
    return max(values) if values else 0.0


def parse_snake_frames(body):
    frames = []
    for fm in re.finditer(
        r'([\d.,%]+)\{transform:translate\((-?\d+(?:\.\d+)?)px,(-?\d+(?:\.\d+)?)px\)\}',
        body,
    ):
        percentages = [float(p.replace('%', '')) for p in fm.group(1).split(',')]
        frames.append((percentages, float(fm.group(2)), float(fm.group(3)), fm.group(0)))
    return frames


def find_return_crossing(frames, stop_x, min_pct):
    """Find a right-to-left crossing only after every real contribution is gone."""
    seen_right = False
    prev = None
    candidates = []

    for percentages, x, y, _ in frames:
        p = max(percentages)
        if x >= 780:
            seen_right = True

        if seen_right and prev is not None:
            pp, px, py = prev
            if px > stop_x >= x and x < px:
                ratio = (px - stop_x) / (px - x)
                cp = pp + (p - pp) * ratio
                cy = py + (y - py) * ratio
                candidates.append((cp, cy))

        prev = (p, x, y)

    for cp, cy in candidates:
        if cp > min_pct:
            return cp, cy

    raise RuntimeError(
        f"Could not find a return crossing at x={stop_x} after {min_pct:.2f}% "
        f"(candidates: {[round(c[0], 2) for c in candidates]})"
    )


def nearest_route(groups):
    """Eat R -> J -> A with a compact route so the snake itself removes each block."""
    route = []
    current = (STOP_X, STOP_Y)

    for group in reversed(groups):
        remaining = list(group)
        while remaining:
            def distance(item):
                _, x, y = item
                tx, ty = x - 2, y - 2
                return abs(tx - current[0]) + abs(ty - current[1])

            item = min(remaining, key=distance)
            remaining.remove(item)
            idx, x, y = item
            tx, ty = x - 2, y - 2
            route.append((idx, tx, ty))
            current = (tx, ty)

    return route


def route_timing(route):
    if not route:
        return {}, []

    n = len(route)
    times = {}
    timed_route = []

    for i, (idx, x, y) in enumerate(route):
        pct = EAT_START if n == 1 else EAT_START + (EAT_END - EAT_START) * (i / (n - 1))
        times[idx] = pct
        timed_route.append((pct, x, y))

    return times, timed_route


def build_dot_css(ms, groups, eat_times):
    mouth_x = STOP_X + 2
    mouth_y = STOP_Y + 2
    css = [
        ".grid-slot{shape-rendering:geometricPrecision;fill:var(--ce);stroke-width:1px;stroke:var(--cb)}",
        f".final-clear{{shape-rendering:geometricPrecision;fill:var(--ce);stroke-width:1px;stroke:var(--cb);opacity:0;animation:final-clear {ms}ms linear infinite}}",
        f"@keyframes final-clear{{0%,{CLEAR_START - .1:.2f}%{{opacity:0}}{CLEAR_START:.2f}%,99.75%{{opacity:1}}100%{{opacity:0}}}}",
        f".ajr-dot{{opacity:0;fill:var(--cs);animation-duration:{ms}ms;animation-timing-function:linear;animation-iteration-count:infinite;transform-box:fill-box;transform-origin:center}}",
    ]

    for letter_index, pts in enumerate(groups):
        start_window, end_window = SPIT_WINDOWS[letter_index]
        n = max(1, len(pts))
        usable = (end_window - start_window) * 0.70

        for local_i, (idx, tx, ty) in enumerate(pts):
            start = start_window + (local_i / n) * usable
            puff = start + 0.34
            arrive = min(end_window, start + 1.20)
            eat = eat_times[idx]
            pre_eat = max(arrive + .05, eat - .16)
            gone = min(99.6, eat + .12)

            puff_dx = -16 - (local_i % 2) * 3
            puff_dy = (-4, -1, 2, 4)[local_i % 4]
            dx = tx - mouth_x
            dy = ty - mouth_y

            css.append(
                f".ajr-{idx}{{animation-name:ajr-{idx}}}"
                f"@keyframes ajr-{idx}{{"
                f"0%,{start - .03:.2f}%{{opacity:0;transform:translate(0px,0px) scale(.45)}}"
                f"{start:.2f}%{{opacity:1;transform:translate(-2px,0px) scale(.65)}}"
                f"{puff:.2f}%{{opacity:1;transform:translate({puff_dx}px,{puff_dy}px) scale(.86)}}"
                f"{arrive:.2f}%,{pre_eat:.2f}%{{opacity:1;transform:translate({dx}px,{dy}px) scale(1)}}"
                f"{eat:.2f}%{{opacity:1;transform:translate({dx}px,{dy}px) scale(.82)}}"
                f"{gone:.2f}%,100%{{opacity:0;transform:translate({dx}px,{dy}px) scale(.25)}}"
                f"}}"
            )

    return ''.join(css)


def rewrite_snake_keyframes(style, timed_route, latest_consumed):
    stop_positions = [STOP_X, STOP_X + 16, STOP_X + 32, STOP_X + 48]
    history = [
        (STOP_X + 48, STOP_Y),
        (STOP_X + 32, STOP_Y),
        (STOP_X + 16, STOP_Y),
        (STOP_X, STOP_Y),
    ]

    head_positions = history + [(x, y) for _, x, y in timed_route]
    final_y = head_positions[-1][1] if head_positions else STOP_Y
    exit_points = [(240, final_y), (160, final_y), (80, final_y), (0, final_y), (-64, final_y)]
    stop_times = []

    for idx, stop_x in enumerate(stop_positions):
        pattern = re.compile(rf"@keyframes s{idx}\{{(.*?)\}}(?=\.s\.s{idx})")
        match = pattern.search(style)
        if not match:
            raise RuntimeError(f"Could not find snake segment s{idx}")

        frames = parse_snake_frames(match.group(1))
        crossing, _ = find_return_crossing(frames, stop_x, latest_consumed + .15)
        stop_times.append(crossing)

        if crossing >= SPIT_WINDOWS[0][0] - 1:
            raise RuntimeError(
                f"Snake segment s{idx} reaches stop too late ({crossing:.2f}%) for the finale"
            )

        new_parts = []
        for percentages, _, _, raw in frames:
            if max(percentages) < crossing:
                new_parts.append(raw)

        new_parts.append(f"{crossing:.2f}%{{transform:translate({stop_x}px,{STOP_Y}px)}}")
        new_parts.append(f"{EAT_START:.2f}%{{transform:translate({stop_x}px,{STOP_Y}px)}}")

        for step, (pct, _, _) in enumerate(timed_route):
            pos_index = 3 + step - idx
            if pos_index < 0:
                px, py = history[0]
            elif pos_index < len(head_positions):
                px, py = head_positions[pos_index]
            else:
                px, py = head_positions[-1]
            new_parts.append(f"{pct:.2f}%{{transform:translate({px}px,{py}px)}}")

        exit_start = EAT_END + .20
        exit_span = EXIT_END - exit_start
        for j, (px, py) in enumerate(exit_points):
            pct = exit_start + exit_span * ((j + 1) / len(exit_points))
            new_parts.append(f"{pct:.2f}%{{transform:translate({px + idx * 16}px,{py}px)}}")

        new_parts.append(f"100%{{transform:translate({-64 + idx * 16}px,{final_y}px)}}")
        style = style[:match.start(1)] + ''.join(new_parts) + style[match.end(1):]

    if max(stop_times) >= SPIT_WINDOWS[0][0]:
        raise RuntimeError("Snake is not fully stopped before the first AJR block is emitted")

    return style


def build_overlay(groups):
    mouth_x = STOP_X + 2
    mouth_y = STOP_Y + 2
    parts = ['<g id="ajr-finale" pointer-events="none">']
    for pts in groups:
        for idx, _, _ in pts:
            parts.append(
                f'<rect class="ajr-dot ajr-{idx}" x="{mouth_x}" y="{mouth_y}" width="12" height="12" rx="2" ry="2"/>'
            )
    parts.append('</g>')
    return ''.join(parts)


def clip_snake(svg):
    clip = (
        f'<defs><clipPath id="snake-grid-clip">'
        f'<rect x="0" y="0" width="{GRID_W}" height="{GRID_H}"/>'
        f'</clipPath></defs>'
    )
    svg = svg.replace('</desc>', '</desc>' + clip, 1)

    matches = list(re.finditer(r'<rect class="s s\d"[^>]*/>', svg))
    if len(matches) != 4:
        raise RuntimeError(f"Expected 4 snake segments, found {len(matches)}")

    start = matches[0].start()
    end = matches[-1].end()
    snake_markup = svg[start:end]
    return svg[:start] + '<g id="snake-body" clip-path="url(#snake-grid-clip)">' + snake_markup + '</g>' + svg[end:]


def validate(svg, active_count, groups):
    expected_slots = GRID_COLS * GRID_ROWS
    expected_ajr = sum(len(group) for group in groups)

    if svg.count('class="grid-slot"') != expected_slots:
        raise RuntimeError("Complete 53x7 gray grid was not generated correctly")
    if svg.count('class="final-clear"') != active_count:
        raise RuntimeError("Not every real contribution has a forced consumed state")
    if svg.count('class="ajr-dot ajr-') != expected_ajr:
        raise RuntimeError("AJR block count is inconsistent")
    if 'id="snake-grid-clip"' not in svg or 'id="snake-body"' not in svg:
        raise RuntimeError("Snake clipping was not applied")

    xs = [x for group in groups for _, x, _ in group]
    if abs((min(xs) + max(xs) + 12) / 2 - GRID_W / 2) > GRID_PITCH:
        raise RuntimeError("AJR is not centered in the contribution grid")

    for idx in range(4):
        expected = f"translate({STOP_X + idx * 16}px,{STOP_Y}px)"
        if expected not in svg:
            raise RuntimeError(f"Snake segment s{idx} has no deterministic stop")


def patch(path):
    p = Path(path)
    svg = p.read_text()
    cells = active_cells(svg)

    duration_match = re.search(r"animation:none\s+(\d+)ms", svg)
    if not duration_match:
        raise RuntimeError(f"Could not find snk animation duration in {path}")

    old_ms = int(duration_match.group(1))
    new_ms = round(old_ms / PHASE)
    groups = letter_targets()
    route = nearest_route(groups)
    eat_times, timed_route = route_timing(route)

    style_start = svg.index('<style>') + len('<style>')
    style_end = svg.index('</style>')
    style = svg[style_start:style_end].replace(f'{old_ms}ms', f'{new_ms}ms')

    def scale_percent(match):
        value = float(match.group(1))
        if value >= 99.999:
            return '100%'
        return f'{value * PHASE:.2f}'.rstrip('0').rstrip('.') + '%'

    style = re.sub(r"(?<![\w.-])(\d+(?:\.\d+)?)%", scale_percent, style)
    latest_consumed = latest_contribution_consumption(style)

    style = rewrite_snake_keyframes(style, timed_route, latest_consumed)
    style += build_dot_css(new_ms, groups, eat_times)
    svg = svg[:style_start] + style + svg[style_end:]

    first_cell = svg.find('<rect class="c"')
    if first_cell == -1:
        raise RuntimeError("Could not find contribution grid markup")
    svg = svg[:first_cell] + build_complete_grid() + svg[first_cell:]

    first_snake = svg.find('<rect class="s s0"')
    if first_snake == -1:
        raise RuntimeError("Could not find snake markup")
    svg = svg[:first_snake] + build_final_clear(cells) + svg[first_snake:]

    svg = clip_snake(svg)
    svg = svg.replace('</svg>', build_overlay(groups) + '</svg>')

    validate(svg, len(cells), groups)
    p.write_text(svg)


for filename in sys.argv[1:]:
    patch(filename)
