import re
import sys
from pathlib import Path

PHASE = 0.72

GRID_COLS = 53
GRID_ROWS = 7
GRID_PITCH = 16
GRID_W = GRID_COLS * GRID_PITCH
GRID_H = GRID_ROWS * GRID_PITCH
SNAKE_SEGMENTS = 4

STOP_X = 624
STOP_Y = 48

SPIT_WINDOWS = [(57.0, 62.0), (62.35, 67.35), (67.7, 72.7)]
EAT_START = 74.5
EAT_END = 95.2
EXIT_END = 99.6
CLEAR_START = 56.4

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


def grid_steps(start, target):
    """Walk between two slots without cutting diagonally across the grid."""
    x, y = start
    tx, ty = target
    steps = []

    while x != tx:
        x += GRID_PITCH if tx > x else -GRID_PITCH
        steps.append((x, y))
    while y != ty:
        y += GRID_PITCH if ty > y else -GRID_PITCH
        steps.append((x, y))

    return steps


def contiguous_route(groups):
    """Eat R -> J -> A while moving exactly one contribution slot per step."""
    route = []
    current = (STOP_X, STOP_Y)

    for group in reversed(groups):
        remaining = {(x - 2, y - 2): idx for idx, x, y in group}

        while remaining:
            target = min(
                remaining,
                key=lambda point: (
                    abs(point[0] - current[0]) + abs(point[1] - current[1]),
                    point[1],
                    point[0],
                ),
            )

            for x, y in grid_steps(current, target):
                eaten = []
                if (x, y) in remaining:
                    eaten.append(remaining.pop((x, y)))
                route.append((eaten, x, y))

            current = target

    return route


def route_timing(route):
    if not route:
        return {}, []

    n = len(route)
    times = {}
    timed_route = []

    for i, (indices, x, y) in enumerate(route):
        pct = EAT_START + (EAT_END - EAT_START) * ((i + 1) / n)
        for idx in indices:
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
        usable = (end_window - start_window) * 0.52

        for local_i, (idx, tx, ty) in enumerate(pts):
            start = start_window + (local_i / n) * usable
            puff = start + .30
            arc = start + 1.10
            arrive = start + 1.95
            settle = min(end_window, start + 2.20)
            eat = eat_times[idx]
            pre_eat = max(settle + .05, eat - .18)
            gone = min(99.8, eat + .20)

            dx = tx - mouth_x
            dy = ty - mouth_y
            puff_dx = -10 - (local_i % 3) * 2
            puff_dy = (-5, -2, 2, 5)[local_i % 4]
            arc_dx = round(dx * .46)
            arc_dy = round(dy * .46 - 8 - (local_i % 3) * 2)

            css.append(
                f".ajr-{idx}{{animation-name:ajr-{idx}}}"
                f"@keyframes ajr-{idx}{{"
                f"0%,{start - .03:.2f}%{{opacity:0;transform:translate(0px,0px) scale(.35)}}"
                f"{start:.2f}%{{opacity:1;transform:translate(-3px,0px) scale(.55);animation-timing-function:cubic-bezier(.2,.75,.3,1)}}"
                f"{puff:.2f}%{{opacity:1;transform:translate({puff_dx}px,{puff_dy}px) scale(.76);animation-timing-function:cubic-bezier(.25,.65,.35,1)}}"
                f"{arc:.2f}%{{opacity:1;transform:translate({arc_dx}px,{arc_dy}px) scale(.92);animation-timing-function:cubic-bezier(.3,.65,.4,1)}}"
                f"{arrive:.2f}%{{opacity:1;transform:translate({dx}px,{dy}px) scale(1.08)}}"
                f"{settle:.2f}%,{pre_eat:.2f}%{{opacity:1;transform:translate({dx}px,{dy}px) scale(1)}}"
                f"{eat:.2f}%{{opacity:1;transform:translate({dx}px,{dy}px) scale(.82)}}"
                f"{gone:.2f}%,100%{{opacity:0;transform:translate({dx}px,{dy}px) scale(.25)}}"
                f"}}"
            )

    return ''.join(css)


def rewrite_snake_keyframes(style, timed_route, latest_consumed):
    stop_positions = [STOP_X + idx * GRID_PITCH for idx in range(SNAKE_SEGMENTS)]
    history = [
        (STOP_X + 3 * GRID_PITCH, STOP_Y),
        (STOP_X + 2 * GRID_PITCH, STOP_Y),
        (STOP_X + GRID_PITCH, STOP_Y),
        (STOP_X, STOP_Y),
    ]

    head_positions = history + [(x, y) for _, x, y in timed_route]
    final_y = head_positions[-1][1] if head_positions else STOP_Y
    final_x = head_positions[-1][0] if head_positions else STOP_X
    exit_positions = grid_steps((final_x, final_y), (-SNAKE_SEGMENTS * GRID_PITCH, final_y))
    exit_start = EAT_END + .20
    exit_timeline = [
        (
            exit_start + (EXIT_END - exit_start) * ((step + 1) / len(exit_positions)),
            x,
            y,
        )
        for step, (x, y) in enumerate(exit_positions)
    ]
    full_timeline = timed_route + exit_timeline
    head_positions += exit_positions
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

        for step, (pct, _, _) in enumerate(full_timeline):
            pos_index = len(history) + step - idx
            if pos_index < 0:
                px, py = history[0]
            elif pos_index < len(head_positions):
                px, py = head_positions[pos_index]
            else:
                px, py = head_positions[-1]
            new_parts.append(f"{pct:.2f}%{{transform:translate({px}px,{py}px)}}")

        final_position = head_positions[-1 - idx]
        new_parts.append(
            f"100%{{transform:translate({final_position[0]}px,{final_position[1]}px)}}"
        )
        style = style[:match.start(1)] + ''.join(new_parts) + style[match.end(1):]

    if max(stop_times) >= SPIT_WINDOWS[0][0]:
        raise RuntimeError("Snake is not fully stopped before the first AJR block is emitted")

    return style


def build_snake_details(ms):
    css = [
        f".snake-detail{{pointer-events:none;animation:none linear {ms}ms infinite}}",
        ".snake-scale,.snake-shine{fill:#fff;opacity:.26}",
        ".snake-eye{fill:#fff;stroke:#1f2328;stroke-width:.55}",
        ".snake-pupil{fill:#1f2328}",
        ".snake-mouth{fill:none;stroke:#1f2328;stroke-width:.7;stroke-linecap:round}",
    ]
    css.extend(
        f".snake-detail-{idx}{{transform:translate({idx * GRID_PITCH}px,-{GRID_PITCH}px);animation-name:s{idx}}}"
        for idx in range(SNAKE_SEGMENTS)
    )
    markup = [
        '<g id="snake-details" pointer-events="none">',
        '<g class="snake-detail snake-detail-0">',
        '<ellipse class="snake-shine" cx="3.6" cy="3.2" rx="1.5" ry=".8"/>',
        '<circle class="snake-eye" cx="5.2" cy="6" r="1.45"/>',
        '<circle class="snake-eye" cx="10.8" cy="6" r="1.45"/>',
        '<circle class="snake-pupil" cx="5.2" cy="6.2" r=".6"/>',
        '<circle class="snake-pupil" cx="10.8" cy="6.2" r=".6"/>',
        '<path class="snake-mouth" d="M6.2 10.1q1.8 1.2 3.6 0"/>',
        '</g>',
    ]

    for idx in range(1, SNAKE_SEGMENTS):
        markup.append(
            f'<g class="snake-detail snake-detail-{idx}">'
            '<ellipse class="snake-scale" cx="6.1" cy="4.4" rx="1.8" ry="1"/>'
            '</g>'
        )

    markup.append('</g>')
    return ''.join(css), ''.join(markup)


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


def clip_snake(svg, details):
    clip = (
        f'<defs><clipPath id="snake-grid-clip">'
        f'<rect x="0" y="0" width="{GRID_W}" height="{GRID_H}"/>'
        f'</clipPath></defs>'
    )
    svg = svg.replace('</desc>', '</desc>' + clip, 1)

    matches = list(re.finditer(r'<rect class="s s\d"[^>]*/>', svg))
    if len(matches) != SNAKE_SEGMENTS:
        raise RuntimeError(
            f"Expected {SNAKE_SEGMENTS} snake segments, found {len(matches)}"
        )

    start = matches[0].start()
    end = matches[-1].end()
    snake_markup = svg[start:end]
    return (
        svg[:start]
        + '<g id="snake-body" clip-path="url(#snake-grid-clip)">'
        + snake_markup
        + details
        + '</g>'
        + svg[end:]
    )


def validate(svg, active_count, groups, route, eat_times):
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
    if 'id="snake-details"' not in svg:
        raise RuntimeError("Snake details were not generated")

    previous = (STOP_X, STOP_Y)
    for _, x, y in route:
        distance = abs(x - previous[0]) + abs(y - previous[1])
        if distance != GRID_PITCH:
            raise RuntimeError("Snake finale contains an off-grid jump")
        previous = (x, y)

    expected_targets = {idx for group in groups for idx, _, _ in group}
    if set(eat_times) != expected_targets:
        raise RuntimeError("Not every AJR block is synchronized with the snake head")

    head_match = re.search(r"@keyframes s0\{(.*?)\}(?=\.s\.s0)", svg)
    if not head_match:
        raise RuntimeError("Snake head animation was not generated")
    head_frames = head_match.group(1)
    for group in groups:
        for idx, x, y in group:
            expected = (
                f"{eat_times[idx]:.2f}%"
                f"{{transform:translate({x - 2}px,{y - 2}px)}}"
            )
            if expected not in head_frames:
                raise RuntimeError(f"AJR block {idx} disappears before the snake reaches it")

    xs = [x for group in groups for _, x, _ in group]
    if abs((min(xs) + max(xs) + 12) / 2 - GRID_W / 2) > GRID_PITCH:
        raise RuntimeError("AJR is not centered in the contribution grid")

    for idx in range(SNAKE_SEGMENTS):
        expected = f"translate({STOP_X + idx * GRID_PITCH}px,{STOP_Y}px)"
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
    route = contiguous_route(groups)
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
    detail_css, detail_markup = build_snake_details(new_ms)
    style += detail_css
    svg = svg[:style_start] + style + svg[style_end:]

    first_cell = svg.find('<rect class="c"')
    if first_cell == -1:
        raise RuntimeError("Could not find contribution grid markup")
    svg = svg[:first_cell] + build_complete_grid() + svg[first_cell:]

    first_snake = svg.find('<rect class="s s0"')
    if first_snake == -1:
        raise RuntimeError("Could not find snake markup")
    svg = svg[:first_snake] + build_final_clear(cells) + svg[first_snake:]

    svg = clip_snake(svg, detail_markup)
    svg = svg.replace('</svg>', build_overlay(groups) + '</svg>')

    validate(svg, len(cells), groups, route, eat_times)
    p.write_text(svg)


for filename in sys.argv[1:]:
    patch(filename)
