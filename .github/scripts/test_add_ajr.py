import importlib.util
import re
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("add-ajr.py")
SPEC = importlib.util.spec_from_file_location("add_ajr", SCRIPT)
add_ajr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = add_ajr
SPEC.loader.exec_module(add_ajr)


def generated_fixture() -> str:
    missing = {(52, 3), (52, 4), (52, 5), (52, 6)}
    active = {(36, 4): ("c0", "c3"), (52, 2): ("c1", "c4")}
    style = (
        ":root{--cb:#0000000a;--cs:#2da44e;--ce:#ebedf0;"
        "--c0:#ebedf0;--c1:#9be9a8;--c2:#40c463;--c3:#30a14e;--c4:#216e39}"
        ".c.c0{fill:var(--c3);animation-name:c0}"
        ".c.c1{fill:var(--c4);animation-name:c1}"
    )
    cells = []
    for col in range(add_ajr.GRID_COLS):
        for row in range(add_ajr.GRID_ROWS):
            if (col, row) in missing:
                continue
            token = active.get((col, row), (None, None))[0]
            class_name = f"c {token}" if token else "c"
            cells.append(
                f'<rect class="{class_name}" x="{2 + col * 16}" '
                f'y="{2 + row * 16}" rx="2" ry="2"/>'
            )
    return f'<svg><style>{style}</style>{"".join(cells)}</svg>'


class SnakeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.source = generated_fixture()
        self.style = re.search(r"<style>(.*?)</style>", self.source).group(1)
        self.cells = add_ajr.parse_cells(self.source, self.style)
        self.valid = {(cell.col, cell.row) for cell in self.cells}

    def test_partial_week_is_preserved(self):
        output = add_ajr.render(self.source)

        self.assertEqual(367, output.count('class="cell'))
        self.assertNotIn('<rect class="cell" x="834" y="50"', output)
        self.assertNotIn('class="grid-slot"', output)
        self.assertNotIn('class="final-clear"', output)
        self.assertNotIn("clip-path=", output)

    def test_every_route_step_uses_a_real_adjacent_slot(self):
        active = [cell for cell in self.cells if cell.color]
        origin = add_ajr.top_left_origin(self.valid)
        real_route, _ = add_ajr.build_real_route(self.cells, active, origin)
        letter_route, _ = add_ajr.build_letter_route(self.valid, origin)

        add_ajr.assert_valid_route(real_route, "test route", self.valid)
        add_ajr.assert_valid_route(letter_route, "test AJR route", self.valid)
        self.assertEqual((0, 0), real_route[0])
        self.assertEqual(real_route[0], letter_route[-1])
        self.assertNotIn((52, 3), real_route)
        self.assertNotIn((52, 4), real_route)

    def test_loop_returns_the_whole_snake_to_its_origin(self):
        active = [cell for cell in self.cells if cell.color]
        origin = add_ajr.top_left_origin(self.valid)
        real_route, _ = add_ajr.build_real_route(self.cells, active, origin)
        finale_route, _ = add_ajr.build_letter_route(self.valid, origin)

        self.assertEqual(origin, real_route[0])
        self.assertEqual(
            [origin] * add_ajr.SNAKE_SEGMENTS,
            finale_route[-add_ajr.SNAKE_SEGMENTS :],
        )

    def test_spit_is_deliberately_slow(self):
        pixel_count = len(add_ajr.letter_cells())
        spit_duration = (
            (pixel_count - 1) * add_ajr.SPIT_STAGGER_SECONDS
            + add_ajr.SPIT_FLIGHT_SECONDS
        )

        self.assertGreaterEqual(spit_duration, 12)
        self.assertGreaterEqual(add_ajr.SPIT_FLIGHT_SECONDS, 1.5)

    def test_output_is_cropped_to_the_calendar(self):
        output = add_ajr.render(self.source)

        self.assertIn('viewBox="0 0 848 112"', output)
        self.assertNotIn('viewBox="-16 -32 880 192"', output)
        self.assertEqual(add_ajr.SNAKE_SEGMENTS, output.count('class="snake-segment'))


if __name__ == "__main__":
    unittest.main()
