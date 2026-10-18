import unittest

import eyes
from eyes import E


def rows(grid):
    return [''.join('#' if v else '.' for v in row) for row in grid]


class EyeModelTest(unittest.TestCase):
    def test_open_eye_has_pupil_hole(self):
        self.assertEqual(rows(E(1).render())[3], '###..###')

    def test_closed_eye_is_a_slit(self):
        self.assertEqual(rows(E(0).render()), ['........'] * 3 + ['########'] + ['........'] * 4)

    def test_inverted_eye_shows_only_the_pupil(self):
        self.assertEqual(rows(E(1, pupil=2, invert=True).render())[2:5], ['........', '...##...', '...##...'])
        self.assertTrue(all(all(row) for row in E(1, pupil=9, invert=True).render()))

    def test_scroll_wraps_rows(self):
        self.assertEqual(E(1, scroll=1).render()[1:], E(1).render()[:-1])

    def test_every_scene_is_monotonic_and_renders(self):
        for name, scene in eyes.SCENES.items():
            for clip in scene(1.0):
                frames = eyes.resolve(clip, E())
                times = [t for t, _ in frames]
                self.assertEqual(times, sorted(times), name)
                for t in (0, times[-1] / 2, times[-1]):
                    eyes.sample(frames, t).render()
            self.assertIn(name, eyes.LAYERS)

    def test_heartbeat_stays_in_range(self):
        values = [eyes.heartbeat(i / 100, 0.7) for i in range(200)]
        self.assertAlmostEqual(max(values), 1.0, places=2)
        self.assertAlmostEqual(min(values), 0.3, places=2)


if __name__ == '__main__':
    unittest.main()
