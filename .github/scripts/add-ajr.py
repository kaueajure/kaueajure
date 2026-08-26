"""Build a deterministic contribution snake with a slow AJR finale.

Platane/snk supplies the base grid. GitHub's GraphQL calendar is the source of
truth for dates, daily counts, intensity levels and the rolling yearly total.
The original route and rendering are discarded so the custom animation stays
inside real slots while preserving and validating the underlying data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen


GRID_COLS = 53
GRID_ROWS = 7
GRID_PITCH = 16
CELL_SIZE = 12
GRID_WIDTH = GRID_COLS * GRID_PITCH
GRID_HEIGHT = GRID_ROWS * GRID_PITCH
OUTPUT_HEIGHT = GRID_HEIGHT + 24

STOP = (39, 3)
SNAKE_SEGMENTS = 6

INTRO_SECONDS = 0.8
GRID_STEP_SECONDS = 0.13
SPIT_STAGGER_SECONDS = 0.22
SPIT_FLIGHT_SECONDS = 1.8
LETTER_HOLD_SECONDS = 1.4
LETTER_STEP_SECONDS = 0.12
FINAL_HOLD_SECONDS = 0.35
FADE_SECONDS = 1.0

FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "J": ["11111", "00100", "00100", "00100", "00100", "10100", "01100"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
}


@dataclass(frozen=True)
class Cell:
    col: int
    row: int
    color: str | None


@dataclass(frozen=True)
class ContributionDay:
    date: str
    count: int
    level: str


@dataclass(frozen=True)
class ContributionCalendar:
    total: int
    days: dict[tuple[int, int], ContributionDay]


LEVEL_COLORS = {
    "NONE": None,
    "FIRST_QUARTILE": "c1",
    "SECOND_QUARTILE": "c2",
    "THIRD_QUARTILE": "c3",
    "FOURTH_QUARTILE": "c4",
}


def fetch_contribution_calendar(username: str, token: str) -> ContributionCalendar:
    """Fetch the same rolling contribution calendar displayed by GitHub."""
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                weekday
                contributionCount
                contributionLevel
              }
            }
          }
        }
      }
    }
    """
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"login": username}}).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "kaueajure-contribution-snake",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except Exception as error:
        raise RuntimeError(
            f"Could not fetch the GitHub contribution calendar: {error}"
        ) from error

    if payload.get("errors"):
        raise RuntimeError(f"GitHub contribution query failed: {payload['errors']}")

    try:
        source = payload["data"]["user"]["contributionsCollection"]
        calendar = source["contributionCalendar"]
        days = {
            (col, day["weekday"]): ContributionDay(
                day["date"], day["contributionCount"], day["contributionLevel"]
            )
            for col, week in enumerate(calendar["weeks"])
            for day in week["contributionDays"]
        }
        result = ContributionCalendar(calendar["totalContributions"], days)
    except (KeyError, TypeError) as error:
        raise RuntimeError("GitHub returned an incomplete contribution calendar") from error

    if result.total != sum(day.count for day in result.days.values()):
        raise RuntimeError("GitHub contribution total does not match its daily counts")
    return result


def validate_calendar(cells: list[Cell], calendar: ContributionCalendar) -> None:
    source_slots = {(cell.col, cell.row) for cell in cells}
    if source_slots != set(calendar.days):
        raise RuntimeError("Platane/snk grid does not match GitHub's real calendar dates")

    for cell in cells:
        day = calendar.days[(cell.col, cell.row)]
        expected_color = LEVEL_COLORS.get(day.level)
        if day.level not in LEVEL_COLORS:
            raise RuntimeError(f"Unknown GitHub contribution level: {day.level}")
        if cell.color != expected_color:
            raise RuntimeError(
                f"Contribution mismatch on {day.date}: SVG={cell.color}, GitHub={day.level}"
            )


def pct(seconds: float, duration: float) -> str:
    return f"{100 * seconds / duration:.3f}".rstrip("0").rstrip(".") + "%"


def parse_palette(style: str) -> dict[str, str]:
    palette = dict(re.findall(r"--(c[bes]|c[0-4]):([^;}]+)", style))
    required = {"cb", "cs", "ce", "c0", "c1", "c2", "c3", "c4"}
    missing = required - palette.keys()
    if missing:
        raise RuntimeError(f"Missing color variables in generated SVG: {sorted(missing)}")
    return palette


def parse_cells(svg: str, style: str) -> list[Cell]:
    pattern = re.compile(
        r'<rect class="c(?: ([^"]+))?" x="(\d+(?:\.\d+)?)" '
        r'y="(\d+(?:\.\d+)?)" rx="2" ry="2"/>'
    )
    cells: list[Cell] = []

    for match in pattern.finditer(svg):
        token, raw_x, raw_y = match.groups()
        x, y = float(raw_x), float(raw_y)
        col = round((x - 2) / GRID_PITCH)
        row = round((y - 2) / GRID_PITCH)

        if x != 2 + col * GRID_PITCH or y != 2 + row * GRID_PITCH:
            raise RuntimeError(f"Contribution cell is off-grid: ({x:g}, {y:g})")

        color = None
        if token:
            color_match = re.search(
                rf"\.c\.{re.escape(token)}\{{fill:var\(--(c[1-4])\)", style
            )
            if not color_match:
                raise RuntimeError(f"Could not resolve contribution color for {token}")
            color = color_match.group(1)

        cells.append(Cell(col, row, color))

    actual = {(cell.col, cell.row) for cell in cells}
    if len(cells) != len(actual):
        raise RuntimeError("Platane/snk provided duplicate calendar slots")
    if not cells or any(
        not (0 <= cell.col < GRID_COLS and 0 <= cell.row < GRID_ROWS)
        for cell in cells
    ):
        raise RuntimeError("Platane/snk provided an invalid calendar slot")

    return cells


def letter_cells() -> list[tuple[int, int, int]]:
    """Return (id, column, row) for centered AJR pixels."""
    letter_width = 5
    gap = 2
    total_width = letter_width * 3 + gap * 2
    start_col = (GRID_COLS - total_width) // 2
    result = []
    index = 0

    for letter_index, letter in enumerate("AJR"):
        offset = letter_index * (letter_width + gap)
        for row, bits in enumerate(FONT[letter]):
            for local_col, bit in enumerate(bits):
                if bit == "1":
                    result.append((index, start_col + offset + local_col, row))
                    index += 1

    return result


def ordered_column_sweep(
    points: set[tuple[int, int]],
    *,
    ascending: bool,
    start: tuple[int, int] | None = None,
    finish: tuple[int, int] | None = None,
) -> list[tuple[int, int]]:
    """Visit columns once and choose the cheapest vertical sweep per column."""
    if not points:
        return []

    columns = sorted({col for col, _ in points}, reverse=not ascending)
    # State value: (cost, ordered target list), keyed by the current ending row.
    states: dict[int, tuple[int, list[tuple[int, int]]]] = {}

    for column_index, col in enumerate(columns):
        rows = sorted(row for point_col, row in points if point_col == col)
        low, high = rows[0], rows[-1]
        vertical_span = high - low
        sweeps = ((low, high, rows), (high, low, list(reversed(rows))))
        next_states: dict[int, tuple[int, list[tuple[int, int]]]] = {}

        for entry, end, ordered_rows in sweeps:
            column_targets = [(col, row) for row in ordered_rows]
            if column_index == 0:
                cost = vertical_span
                if start is not None:
                    cost += abs(start[0] - col) + abs(start[1] - entry)
                current = next_states.get(end)
                candidate = (cost, column_targets)
                if current is None or candidate[0] < current[0]:
                    next_states[end] = candidate
                continue

            for previous_row, (previous_cost, previous_targets) in states.items():
                previous_col = columns[column_index - 1]
                cost = (
                    previous_cost
                    + abs(previous_col - col)
                    + abs(previous_row - entry)
                    + vertical_span
                )
                candidate = (cost, previous_targets + column_targets)
                current = next_states.get(end)
                if current is None or candidate[0] < current[0]:
                    next_states[end] = candidate

        states = next_states

    last_col = columns[-1]

    def final_cost(item: tuple[int, tuple[int, list[tuple[int, int]]]]) -> int:
        end_row, (cost, _) = item
        if finish is None:
            return cost
        return cost + abs(last_col - finish[0]) + abs(end_row - finish[1])

    return min(states.items(), key=final_cost)[1][1]


def shortest_valid_path(
    start: tuple[int, int],
    target: tuple[int, int],
    valid_slots: set[tuple[int, int]],
    blocked: set[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Find a shortest path that uses only slots emitted by GitHub."""
    if start == target:
        return [start]

    blocked = (blocked or set()) - {start, target}
    queue = deque([start])
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}

    while queue:
        col, row = queue.popleft()
        # Prefer vertical alignment, then progress toward the target. BFS still
        # guarantees the globally shortest valid path.
        neighbors = [(col, row - 1), (col, row + 1), (col - 1, row), (col + 1, row)]
        neighbors.sort(
            key=lambda point: (
                abs(point[0] - target[0]) + abs(point[1] - target[1]),
                abs(point[0] - target[0]),
                point[1],
                point[0],
            )
        )
        for neighbor in neighbors:
            if (
                neighbor not in valid_slots
                or neighbor in blocked
                or neighbor in previous
            ):
                continue
            previous[neighbor] = (col, row)
            if neighbor == target:
                path = [target]
                cursor = (col, row)
                while cursor != start:
                    path.append(cursor)
                    parent = previous[cursor]
                    if parent is None:
                        break
                    cursor = parent
                path.append(start)
                return list(reversed(path))
            queue.append(neighbor)

    raise RuntimeError(f"No valid calendar path from {start} to {target}")


def append_shortest_path(
    route: list[tuple[int, int]],
    target: tuple[int, int],
    valid_slots: set[tuple[int, int]],
    *,
    blocked: set[tuple[int, int]] | None = None,
) -> None:
    if not route:
        if target not in valid_slots:
            raise RuntimeError(f"Target is not a real calendar slot: {target}")
        route.append(target)
        return
    route.extend(shortest_valid_path(route[-1], target, valid_slots, blocked)[1:])


def expand_targets(
    targets: list[tuple[int, int]],
    valid_slots: set[tuple[int, int]],
    start: tuple[int, int] | None = None,
) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    route = [start] if start is not None else []
    arrival: dict[tuple[int, int], int] = {}

    for index, target in enumerate(targets):
        # Do not cross a future contribution and leave it inexplicably uneaten.
        blocked = set(targets[index + 1 :])
        append_shortest_path(route, target, valid_slots, blocked=blocked)
        arrival.setdefault(target, len(route) - 1)

    return route, arrival


def top_left_origin(valid_slots: set[tuple[int, int]]) -> tuple[int, int]:
    if not valid_slots:
        raise RuntimeError("The contribution calendar has no valid origin")
    return min(valid_slots, key=lambda point: (point[0], point[1]))


def build_real_route(
    cells: list[Cell], active: list[Cell], origin: tuple[int, int]
) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    valid_slots = {(cell.col, cell.row) for cell in cells}
    points = {(cell.col, cell.row) for cell in active}
    targets = ordered_column_sweep(
        points, ascending=True, start=origin, finish=STOP
    )
    route, arrival = expand_targets(targets, valid_slots, start=origin)

    if not active:
        if STOP not in valid_slots:
            raise RuntimeError("The AJR staging slot does not exist in this calendar")
        route = [origin]

    # Enter the final pose from the nearest side. All positions are real
    # calendar slots; no clipping is needed to hide invalid movement.
    last_col, _ = route[-1]
    if last_col >= STOP[0]:
        staging_edge = (min(GRID_COLS - 1, STOP[0] + SNAKE_SEGMENTS), STOP[1])
    else:
        staging_edge = (max(0, STOP[0] - SNAKE_SEGMENTS), STOP[1])

    append_shortest_path(route, staging_edge, valid_slots)
    append_shortest_path(route, STOP, valid_slots)
    return route, arrival


def build_letter_route(
    valid_slots: set[tuple[int, int]], return_to: tuple[int, int]
) -> tuple[list[tuple[int, int]], dict[int, int]]:
    letters = letter_cells()
    by_position = {(col, row): index for index, col, row in letters}
    targets = ordered_column_sweep(set(by_position), ascending=False, start=STOP)
    missing = set(by_position) - valid_slots
    if missing:
        raise RuntimeError(f"AJR overlaps missing calendar slots: {sorted(missing)}")
    route, arrivals_by_position = expand_targets(targets, valid_slots, start=STOP)
    arrivals = {by_position[position]: step for position, step in arrivals_by_position.items()}
    append_shortest_path(route, return_to, valid_slots)
    # Let the body retract into the origin before the invisible animation reset.
    route.extend([return_to] * (SNAKE_SEGMENTS - 1))
    return route, arrivals


def assert_valid_route(
    route: list[tuple[int, int]], name: str, valid_slots: set[tuple[int, int]]
) -> None:
    for col, row in route:
        if (col, row) not in valid_slots:
            raise RuntimeError(f"{name} uses a nonexistent calendar slot at ({col}, {row})")

    for previous, current in zip(route, route[1:]):
        distance = abs(previous[0] - current[0]) + abs(previous[1] - current[1])
        if distance not in (0, 1):
            raise RuntimeError(f"{name} jumps from {previous} to {current}")


def cell_transform(point: tuple[int, int]) -> str:
    return f"translate({point[0] * GRID_PITCH}px,{point[1] * GRID_PITCH}px)"


def build_segment_keyframes(
    segment: int,
    real_route: list[tuple[int, int]],
    letter_route: list[tuple[int, int]],
    movement_start: float,
    spit_end: float,
    eat_start: float,
    duration: float,
    fade_start: float,
) -> str:
    frames: list[tuple[float, tuple[int, int], float]] = []
    combined = real_route + letter_route[1:]

    def add(time: float, combined_index: int, opacity: float = 1) -> None:
        point = combined[max(0, combined_index - segment)]
        frame = (time, point, opacity)
        if not frames or frame != frames[-1]:
            frames.append(frame)

    frames.append((0, real_route[0], 0))
    frames.append((movement_start, real_route[0], 1))
    for index in range(1, len(real_route)):
        add(movement_start + index * GRID_STEP_SECONDS, index)

    last_real_index = len(real_route) - 1
    add(spit_end, last_real_index)
    add(eat_start, last_real_index)

    for index in range(1, len(letter_route)):
        add(eat_start + index * LETTER_STEP_SECONDS, last_real_index + index)

    last_index = last_real_index + len(letter_route) - 1
    add(fade_start, last_index)
    add(duration, last_index, 0)

    body = "".join(
        f"{pct(time, duration)}{{opacity:{opacity:g};transform:{cell_transform(point)}}}"
        for time, point, opacity in frames
    )
    return f"@keyframes snake-{segment}{{{body}}}"


def build_spit_keyframes(
    index: int,
    target: tuple[int, int],
    launch: float,
    consume: float,
    duration: float,
) -> str:
    target_x = 2 + target[0] * GRID_PITCH
    target_y = 2 + target[1] * GRID_PITCH
    mouth_x = 2 + STOP[0] * GRID_PITCH
    mouth_y = 2 + STOP[1] * GRID_PITCH
    dx, dy = target_x - mouth_x, target_y - mouth_y
    middle = launch + SPIT_FLIGHT_SECONDS * 0.52
    arrive = launch + SPIT_FLIGHT_SECONDS
    arc_x = round(dx * 0.48)
    arc_y = round(dy * 0.48 - 15 - (index % 3) * 3)
    shrink = min(duration - 0.05, consume + 0.24)

    body = (
        f"0%,{pct(launch, duration)}{{opacity:0;transform:translate(0,0) scale(.35)}}"
        f"{pct(launch + 0.02, duration)}{{opacity:1;transform:translate(-4px,0) scale(.55)}}"
        f"{pct(middle, duration)}{{opacity:1;transform:translate({arc_x}px,{arc_y}px) scale(.82);"
        "animation-timing-function:cubic-bezier(.2,.75,.3,1)}"
        f"{pct(arrive, duration)}{{opacity:1;transform:translate({dx}px,{dy}px) scale(1.08)}}"
        f"{pct(arrive + 0.2, duration)},{pct(max(arrive + 0.2, consume - 0.04), duration)}"
        f"{{opacity:1;transform:translate({dx}px,{dy}px) scale(1)}}"
        f"{pct(shrink, duration)},100%{{opacity:0;transform:translate({dx}px,{dy}px) scale(.2)}}"
    )
    return f"@keyframes spit-{index}{{{body}}}"


def render(svg: str, calendar: ContributionCalendar) -> str:
    style_match = re.search(r"<style>(.*?)</style>", svg, re.DOTALL)
    if not style_match:
        raise RuntimeError("Generated SVG has no style block")

    source_style = style_match.group(1)
    palette = parse_palette(source_style)
    cells = parse_cells(svg, source_style)
    validate_calendar(cells, calendar)
    valid_slots = {(cell.col, cell.row) for cell in cells}
    origin = top_left_origin(valid_slots)
    active = [cell for cell in cells if cell.color]
    real_route, real_arrivals = build_real_route(cells, active, origin)
    letter_route, letter_arrivals = build_letter_route(valid_slots, origin)
    assert_valid_route(real_route, "Contribution route", valid_slots)
    assert_valid_route(letter_route, "AJR route", valid_slots)

    movement_start = INTRO_SECONDS
    movement_end = movement_start + (len(real_route) - 1) * GRID_STEP_SECONDS
    spit_start = movement_end + 0.45
    letters = letter_cells()
    last_launch = spit_start + (len(letters) - 1) * SPIT_STAGGER_SECONDS
    spit_end = last_launch + SPIT_FLIGHT_SECONDS
    eat_start = spit_end + LETTER_HOLD_SECONDS
    eat_end = eat_start + (len(letter_route) - 1) * LETTER_STEP_SECONDS
    fade_start = eat_end + FINAL_HOLD_SECONDS
    duration = fade_start + FADE_SECONDS

    styles = [
        ":root{" + "".join(f"--{name}:{value};" for name, value in palette.items()) + "}",
        ".cell{shape-rendering:geometricPrecision;fill:var(--ce)}",
        f".contribution{{animation-duration:{duration:.3f}s;animation-timing-function:linear;"
        "animation-iteration-count:infinite}",
        f".snake-segment,.snake-detail{{animation-duration:{duration:.3f}s;"
        "animation-timing-function:linear;animation-iteration-count:infinite;pointer-events:none}",
        ".snake-segment{fill:var(--cs)}",
        ".snake-eye{fill:#fff;stroke:#1f2328;stroke-width:.55}",
        ".snake-pupil{fill:#1f2328}",
        ".snake-shine{fill:#fff;opacity:.28}",
        ".snake-mouth{fill:none;stroke:#1f2328;stroke-width:.75;stroke-linecap:round}",
        ".total-label{fill:var(--ct);font:600 11px -apple-system,BlinkMacSystemFont,"
        '"Segoe UI",sans-serif;text-anchor:middle}',
        f".spit{{fill:var(--cs);opacity:0;animation-duration:{duration:.3f}s;"
        "animation-timing-function:linear;animation-iteration-count:infinite;"
        "transform-box:fill-box;transform-origin:center}",
    ]

    active_index: dict[tuple[int, int], int] = {}
    for index, cell in enumerate(active):
        active_index[(cell.col, cell.row)] = index
        consume_time = movement_start + real_arrivals[(cell.col, cell.row)] * GRID_STEP_SECONDS
        before = max(0, consume_time - 0.02)
        styles.append(
            f".contribution-{index}{{fill:var(--{cell.color});animation-name:consume-{index}}}"
            f"@keyframes consume-{index}{{0%,{pct(before, duration)}{{fill:var(--{cell.color})}}"
            f"{pct(consume_time, duration)},100%{{fill:var(--ce)}}}}"
        )

    for segment in range(SNAKE_SEGMENTS):
        styles.append(
            f".snake-{segment}{{animation-name:snake-{segment}}}"
            + build_segment_keyframes(
                segment,
                real_route,
                letter_route,
                movement_start,
                spit_end,
                eat_start,
                duration,
                fade_start,
            )
        )

    for index, col, row in letters:
        launch = spit_start + index * SPIT_STAGGER_SECONDS
        consume = eat_start + letter_arrivals[index] * LETTER_STEP_SECONDS
        styles.append(
            f".spit-{index}{{animation-name:spit-{index}}}"
            + build_spit_keyframes(index, (col, row), launch, consume, duration)
        )

    grid_markup = []
    for cell in cells:
        classes = ["cell"]
        index = active_index.get((cell.col, cell.row))
        if index is not None:
            classes.extend(("contribution", f"contribution-{index}"))
        x = 2 + cell.col * GRID_PITCH
        y = 2 + cell.row * GRID_PITCH
        day = calendar.days[(cell.col, cell.row)]
        contribution_word = "contribuição" if day.count == 1 else "contribuições"
        grid_markup.append(
            f'<rect class="{" ".join(classes)}" x="{x}" y="{y}" '
            f'width="{CELL_SIZE}" height="{CELL_SIZE}" rx="2" ry="2">'
            f'<title>{day.date}: {day.count} {contribution_word}</title></rect>'
        )

    snake_markup = ['<g id="snake" pointer-events="none">']
    for segment in reversed(range(SNAKE_SEGMENTS)):
        inset = min(3.2, 0.7 + segment * 0.45)
        size = 16 - inset * 2
        radius = max(3, 4.8 - segment * 0.25)
        snake_markup.append(
            f'<rect class="snake-segment snake-{segment}" x="{inset:g}" y="{inset:g}" '
            f'width="{size:g}" height="{size:g}" rx="{radius:g}" ry="{radius:g}"/>'
        )

    snake_markup.extend(
        (
            '<g class="snake-detail snake-0">',
            '<ellipse class="snake-shine" cx="4.1" cy="3.4" rx="1.7" ry=".85"/>',
            '<circle class="snake-eye" cx="5.2" cy="6.1" r="1.5"/>',
            '<circle class="snake-eye" cx="10.8" cy="6.1" r="1.5"/>',
            '<circle class="snake-pupil" cx="5.2" cy="6.25" r=".62"/>',
            '<circle class="snake-pupil" cx="10.8" cy="6.25" r=".62"/>',
            '<path class="snake-mouth" d="M6.1 10.25q1.9 1.25 3.8 0"/>',
            "</g>",
            "</g>",
        )
    )

    mouth_x = 2 + STOP[0] * GRID_PITCH
    mouth_y = 2 + STOP[1] * GRID_PITCH
    spit_markup = ['<g id="ajr-finale" pointer-events="none">']
    for index, _, _ in letters:
        spit_markup.append(
            f'<rect class="spit spit-{index}" x="{mouth_x}" y="{mouth_y}" '
            f'width="{CELL_SIZE}" height="{CELL_SIZE}" rx="2" ry="2"/>'
        )
    spit_markup.append("</g>")

    empty_color = palette["ce"].lstrip("#")
    empty_rgb = tuple(int(empty_color[index : index + 2], 16) for index in (0, 2, 4))
    label_color = "#8b949e" if sum(empty_rgb) < 384 else "#57606a"
    styles[0] = styles[0][:-1] + f"--ct:{label_color};}}"

    total_label = f"{calendar.total:,}".replace(",", ".")
    output = (
        f'<svg viewBox="0 0 {GRID_WIDTH} {OUTPUT_HEIGHT}" width="{GRID_WIDTH}" '
        f'height="{OUTPUT_HEIGHT}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{total_label} contribuições de Kauê Ajure no último ano">'
        f'<desc>Calendário real com {total_label} contribuições. '
        'A cobra sai do canto superior esquerdo, percorre as contribuições, '
        'forma e recolhe AJR e retorna à origem.</desc>'
        f'<style>{"".join(styles)}</style>'
        '<g id="contribution-grid">'
        f'{"".join(grid_markup)}</g>'
        f'{"".join(snake_markup)}'
        f'{"".join(spit_markup)}'
        f'<text class="total-label" x="{GRID_WIDTH / 2:g}" y="129">'
        f'{total_label} contribuições no último ano · dados reais do GitHub</text>'
        "</svg>"
    )

    validate_output(
        output,
        len(cells),
        len(active),
        len(letters),
        real_route,
        letter_route,
        valid_slots,
        calendar,
    )
    return output


def validate_output(
    svg: str,
    cell_count: int,
    active_count: int,
    letter_count: int,
    real_route: list[tuple[int, int]],
    letter_route: list[tuple[int, int]],
    valid_slots: set[tuple[int, int]],
    calendar: ContributionCalendar,
) -> None:
    if svg.count('class="cell') != cell_count:
        raise RuntimeError("Output does not contain exactly one rectangle per grid slot")
    if svg.count('class="cell contribution') != active_count:
        raise RuntimeError("Output contribution count changed")
    if svg.count('class="spit spit-') != letter_count:
        raise RuntimeError("AJR pixel count changed")
    if svg.count('class="snake-segment') != SNAKE_SEGMENTS:
        raise RuntimeError("Snake segment count changed")
    if 'clip-path=' in svg or 'class="grid-slot"' in svg or 'class="final-clear"' in svg:
        raise RuntimeError("Legacy clipping or duplicate-grid markup survived the refactor")
    if f'viewBox="0 0 {GRID_WIDTH} {OUTPUT_HEIGHT}"' not in svg:
        raise RuntimeError("SVG viewport does not fit the real calendar and its total")
    if svg.count("<title>") != cell_count:
        raise RuntimeError("Not every calendar slot contains its exact daily count")
    total_label = f"{calendar.total:,}".replace(",", ".")
    if f"{total_label} contribuições no último ano" not in svg:
        raise RuntimeError("Exact GitHub contribution total is missing")
    assert_valid_route(real_route, "Contribution route", valid_slots)
    assert_valid_route(letter_route, "AJR route", valid_slots)


def patch(path: str, calendar: ContributionCalendar) -> None:
    source = Path(path)
    source.write_text(
        render(source.read_text(encoding="utf-8"), calendar), encoding="utf-8"
    )


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-user", required=True)
    parser.add_argument("svg", nargs="+")
    options = parser.parse_args(arguments)

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        parser.error("GITHUB_TOKEN is required to validate the real contribution data")

    calendar = fetch_contribution_calendar(options.github_user, token)
    print(
        f"Validated {calendar.total} real GitHub contributions across "
        f"{sum(day.count > 0 for day in calendar.days.values())} active days"
    )
    for filename in options.svg:
        patch(filename, calendar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
