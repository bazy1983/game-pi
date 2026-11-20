import unittest

from ledgames.layout import Grid, Layout, from_settings

W = 3 * 2  # the canvas pixel the dark LEDs get, on a 3 × 2 grid


def chain(**kw) -> list[int]:
    return Grid(width=3, height=2, **kw).order()


class GridOrderTest(unittest.TestCase):
    # Canvas pixels, by row from the top left:
    #   0 1 2
    #   3 4 5

    def test_columns_zigzag_from_the_top_left(self):
        self.assertEqual(chain(), [0, 3, 4, 1, 2, 5])  # down, up, down

    def test_columns_from_each_corner(self):
        self.assertEqual(chain(start="top-right"), [2, 5, 4, 1, 0, 3])
        self.assertEqual(chain(start="bottom-left"), [3, 0, 1, 4, 5, 2])
        self.assertEqual(chain(start="bottom-right"), [5, 2, 1, 4, 3, 0])

    def test_columns_all_the_same_way(self):
        self.assertEqual(chain(zigzag=False), [0, 3, 1, 4, 2, 5])

    def test_rows(self):
        self.assertEqual(chain(runs="rows"), [0, 1, 2, 5, 4, 3])
        self.assertEqual(chain(runs="rows", start="bottom-right"), [5, 4, 3, 0, 1, 2])
        self.assertEqual(chain(runs="rows", zigzag=False), [0, 1, 2, 3, 4, 5])

    def test_dark_leds_between_strips(self):
        self.assertEqual(chain(skip=2), [0, 3, W, W, 4, 1, W, W, 2, 5])
        self.assertEqual(Grid(width=3, height=2, skip=2).num_leds, 10)

    def test_every_pixel_once(self):
        grid = Grid(width=32, height=16, start="bottom-right", skip=1)
        lit = [i for i in grid.order() if i != 32 * 16]
        self.assertEqual(sorted(lit), list(range(32 * 16)))


class ParseTest(unittest.TestCase):
    def test_defaults_fill_in(self):
        grid, error = Grid.parse({"width": 32}, 1000)
        self.assertIsNone(error)
        self.assertEqual(grid, Grid(width=32, height=16))

    def test_bad_values(self):
        for bad in ({"width": 1}, {"height": 65}, {"width": "8"}, {"width": True}, {"runs": "diagonal"},
                    {"start": "middle"}, {"zigzag": 1}, {"skip": -1}, {"skip": 11}, [], None):
            grid, error = Grid.parse(bad, 1000)
            self.assertIsNone(grid, bad)
            self.assertTrue(error, bad)

    def test_too_many_leds(self):
        grid, error = Grid.parse({"width": 32, "height": 32}, 1000)
        self.assertEqual(error, "That's 1024 LEDs; the most is 1000.")


class LayoutTest(unittest.TestCase):
    def test_a_strip_is_its_own_chain(self):
        layout = Layout.strip(4)
        pixels = [(1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0)]
        self.assertIs(layout.to_chain(pixels), pixels)
        self.assertEqual((layout.size, layout.num_leds), (4, 4))

    def test_a_grid_maps_to_the_chain(self):
        layout = Layout.of_grid(Grid(width=2, height=2, skip=1))
        pixels = [(1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0)]
        self.assertEqual(layout.to_chain(pixels), [(1, 0, 0), (3, 0, 0), (0, 0, 0), (4, 0, 0), (2, 0, 0)])
        self.assertEqual(layout.positions(), [0, 2, -1, 3, 1])
        self.assertEqual(layout.describe(), {"kind": "grid", "width": 2, "height": 2})

    def test_from_settings(self):
        self.assertEqual(from_settings({}, 120, 1000).describe(), {"kind": "strip", "leds": 120})
        grid = from_settings({"layout": "grid", "grid": {"width": 8, "height": 4}}, 120, 1000)
        self.assertEqual(grid.describe(), {"kind": "grid", "width": 8, "height": 4})
        bad = from_settings({"layout": "grid", "grid": {"width": 0}}, 120, 1000)
        self.assertEqual(bad.kind, "strip")


if __name__ == "__main__":
    unittest.main()
