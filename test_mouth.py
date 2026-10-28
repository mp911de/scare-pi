import unittest

import eyes
import mouth


class FakeSpi:
    def __init__(self):
        self.sent = None

    def writebytes2(self, data):
        self.sent = bytes(data)

    def close(self):
        pass


class StripTest(unittest.TestCase):
    def strip(self, order='GRBW'):
        strip = mouth.Strip.__new__(mouth.Strip)
        strip.count, strip.min, strip.max, strip.order = 1, 0.0, 1.0, ['RGBW'.index(c) for c in order]
        strip.spi = FakeSpi()
        return strip

    def test_bits_encode_as_1000_and_1100(self):
        self.assertEqual(mouth.ENCODE[0x00], bytes([0x88, 0x88, 0x88, 0x88]))
        self.assertEqual(mouth.ENCODE[0xFF], bytes([0xCC, 0xCC, 0xCC, 0xCC]))
        self.assertEqual(mouth.ENCODE[0x80], bytes([0xC8, 0x88, 0x88, 0x88]))

    def test_channel_order_and_reset(self):
        strip = self.strip('GRBW')
        strip.show([(1.0, 0.0, 0.0, 0.0)])
        self.assertEqual(strip.spi.sent[:16], mouth.ENCODE[0] + mouth.ENCODE[255] + mouth.ENCODE[0] * 2)
        self.assertEqual(strip.spi.sent[16:], mouth.RESET)

    def test_brightness_window_lifts_dim_pixels(self):
        strip = self.strip()
        strip.min, strip.max = 0.2, 0.6
        self.assertEqual(strip.window((0.0, 0.0, 0.0, 0.0)), (0.0, 0.0, 0.0, 0.0))
        self.assertAlmostEqual(strip.window((0.5, 0.25, 0.0, 0.0))[0], 0.4)
        self.assertAlmostEqual(strip.window((0.5, 0.25, 0.0, 0.0))[1], 0.2)
        self.assertAlmostEqual(strip.window((1.0, 0.0, 0.0, 0.0))[0], 0.6)


class FrameTest(unittest.TestCase):
    def test_every_scene_yields_valid_pixels(self):
        for scene in eyes.SCENES:
            pixels = mouth.frame(scene, [eyes.E(1), eyes.E(1)], 0.5, 10)
            self.assertEqual(len(pixels), 10, scene)
            for p in pixels:
                self.assertTrue(all(0.0 <= c <= 1.0 for c in p), scene)

    def test_eye_brightness_dims_the_mouth(self):
        dim = mouth.frame('lurk', [eyes.E(1, bright=0.25)] * 2, 1.0, 4)
        full = mouth.frame('lurk', [eyes.E(1, bright=1.0)] * 2, 1.0, 4)
        self.assertAlmostEqual(dim[0][0], full[0][0] * 0.25)

    def test_only_crazy_leaves_pumpkin_colours(self):
        for scene in eyes.SCENES:
            for p in mouth.frame(scene, [eyes.E(1, 0.5, 0.5, 5)] * 2, 0.3, 10):
                if scene not in ('crazy', 'kitt'):
                    self.assertGreaterEqual(p[0], p[1], scene)
                    self.assertEqual(p[2], 0.0, scene)


if __name__ == '__main__':
    unittest.main()
