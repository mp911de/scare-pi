#!/usr/bin/env python3
"""A pumpkin mouth: a few SK6812 (RGBW) pixels on SPI, lit to match the eyes.

python3 mouth.py                   # the eye story, mouth only
python3 mouth.py roll crazy        # named scenes once, then dark
python3 mouth.py --all --cap 2     # every scene in turn, cut after 2 s
Options: --pin 10, --leds 10, --order GRBW, --brightness 0.15 1.0, --fps 25.
Requires spidev (dtparam=spi=on). Bit timing comes from the SPI clock, so pin
core_freq=250 in config.txt or the clock drifts with the core clock.

The mouth has no keyframes of its own: each scene is a function of the eye pose
the eye player produces (open, pupil position, pupil size, brightness incl. the
heartbeat), so the mouth follows whatever the eyes do. Colours are pumpkin
embers; only crazy goes rainbow and the kitt easter egg red.
"""
import argparse
import colorsys
import math
import sys
import time

import eyes

# SK6812: 0 = 0.3 us high, 1 = 0.6 us high, 1.25 us per bit, reset >= 80 us low.
# At 3.2 MHz one data bit is four SPI bits: 0 -> 1000, 1 -> 1100.
SPI_HZ = 3_200_000
RESET = bytes(32)
ENCODE = [bytes(((0b1100 if byte & 0x80 >> b else 0b1000) << 4 | (0b1100 if byte & 0x40 >> b else 0b1000)
                 for b in range(0, 8, 2))) for byte in range(256)]
SPI_BUS = {10: 0, 20: 1}   # GPIO10 = SPI0 MOSI (pin 19). GPIO20 = SPI1 MOSI, clashes with I2S here.
GAMMA = 2.2

EMBER = (1.0, 0.12, 0.0, 0.0)
PUMPKIN = (1.0, 0.35, 0.0, 0.0)
FLASH = (1.0, 0.5, 0.0, 0.6)


def flicker(t, i):
    """Candle: slow and fast sines per pixel, 0.6..1."""
    return 0.8 + 0.2 * math.sin(t * 6.3 + i * 1.7) * math.sin(t * 2.1 + i * 0.9)


def spread(n):
    return [i / (n - 1) * 2 - 1 for i in range(n)] if n > 1 else [0.0]


def scale(color, k):
    return tuple(c * max(0.0, min(1.0, k)) for c in color)


def sleep_mouth(eye, t, n):
    return [scale(EMBER, (1 - abs(x) * 0.7) * flicker(t, i)) for i, x in enumerate(spread(n))]


def wake_mouth(eye, t, n):
    return [scale(PUMPKIN, flicker(t, i)) if abs(x) <= eye.open else scale(EMBER, 0.3)
            for i, x in enumerate(spread(n))]


def lurk_mouth(eye, t, n):
    return [scale(PUMPKIN, flicker(t, i)) for i in range(n)]


def squint_mouth(eye, t, n):
    # A smirk: the corners glow, the middle fades.
    return [scale(PUMPKIN, (0.2 + 0.8 * abs(x)) * flicker(t, i)) for i, x in enumerate(spread(n))]


def roll_mouth(eye, t, n):
    # A hot spot chases the pupil along the mouth.
    return [scale(PUMPKIN, 0.15 + math.exp(-((x - eye.px) / 0.3) ** 2)) for x in spread(n)]


def crazy_mouth(eye, t, n):
    return [(*colorsys.hsv_to_rgb((x * 0.5 + t * 1.5) % 1, 1, 1), 0.0) for x in spread(n)]


def track_mouth(eye, t, n):
    # The grin widens from the middle as the visitor comes closer (track sets px = closeness).
    width = 0.25 + 0.75 * max(0.0, eye.px)
    return [scale(PUMPKIN, 1.0 if abs(x) <= width else 0.1) for x in spread(n)]


def jumpscare_mouth(eye, t, n):
    on = int(t * 12) % 2 == 0 if t < 0.8 else True
    return [FLASH if on else scale(EMBER, 0.2) for _ in range(n)]


def explode_mouth(eye, t, n):
    # Grows with the pupil (2..9 px) and goes dark with the eye when it bursts.
    width = (eye.pupil - 2) / 7
    return [scale(FLASH, 1.0 if abs(x) <= width else 0.0) for x in spread(n)]


def kitt_mouth(eye, t, n):
    # The red scanner: a hot core around the pupil with a wider afterglow.
    return [scale((1.0, 0.0, 0.0, 0.0), math.exp(-((x - eye.px) / 0.18) ** 2)
                  + 0.35 * math.exp(-((x - eye.px) / 0.45) ** 2)) for x in spread(n)]


def doze_mouth(eye, t, n):
    return sleep_mouth(eye, t, n)


MOUTHS = {name[:-6]: fn for name, fn in globals().items() if name.endswith('_mouth')}


def frame(scene, shown, t, n):
    """Pixels 0..1 RGBW for the scene at t seconds, modulated by the eyes' brightness."""
    left, right = shown
    pixels = MOUTHS.get(scene, lurk_mouth)(left, t, n)
    return [scale(p, (left.bright + right.bright) / 2) for p in pixels]


class Strip:
    """SK6812 pixels on SPI MOSI. `order` names the strip's channel order, e.g. GRBW.
    `brightness` is (min, max): the window the eyes' 0..1 level is mapped into."""
    def __init__(self, pin, count, order, brightness):
        import spidev
        self.count, (self.min, self.max) = count, brightness
        self.order = ['RGBW'.index(c) for c in order]
        self.spi = spidev.SpiDev()
        self.spi.open(SPI_BUS[pin], 0)
        self.spi.max_speed_hz = SPI_HZ

    def encode(self, pixels):
        data = bytearray()
        for pixel in pixels:
            for channel in self.order:
                data += ENCODE[round(255 * pixel[channel] ** GAMMA)]
        return bytes(data) + RESET

    def show(self, pixels):
        self.spi.writebytes2(self.encode([self.window(p) for p in pixels]))

    def window(self, pixel):
        peak = max(pixel)
        return scale(pixel, (self.min + (self.max - self.min) * peak) / peak) if peak else pixel

    def blank(self):
        self.spi.writebytes2(self.encode([(0.0,) * 4] * self.count))
        self.spi.close()


def play(strip, names, fps, distance, cap=0):
    player = eyes.Player()
    for name in names:
        print(name, flush=True)
        player.start(name, time.monotonic(), distance)
        while True:
            now = time.monotonic()
            strip.show(frame(player.scene, player.tick(now), now - player.started, strip.count))
            if player.done(now) or (cap and now - player.started >= cap):
                break
            time.sleep(1 / fps)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('scenes', nargs='*', choices=[*eyes.SCENES, []], metavar='scene')
    parser.add_argument('--pin', type=int, choices=SPI_BUS, default=10)
    parser.add_argument('--leds', type=int, default=10)
    parser.add_argument('--order', default='GRBW', help='channel order of the strip')
    parser.add_argument('--brightness', type=float, nargs=2, default=[0.15, 1.0], metavar=('MIN', 'MAX'))
    parser.add_argument('--fps', type=float, default=25)
    parser.add_argument('--distance', type=float, default=4.0, help='metres, for the track scene')
    parser.add_argument('--all', action='store_true', help='every scene once, in definition order')
    parser.add_argument('--cap', type=float, default=0, help='cut each scene after this many seconds')
    args = parser.parse_args()
    names = args.scenes or (list(eyes.SCENES) if args.all else ['track'] if args.distance < 4.0 else eyes.STORY * 1000)
    try:
        strip = Strip(args.pin, args.leds, args.order, args.brightness)
        try:
            play(strip, names, args.fps, args.distance, args.cap)
        finally:
            strip.blank()
    except KeyboardInterrupt:
        print('\nStopped.')
    except ImportError:
        print('Missing dependency: install python3-spidev.', file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'SPI error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
