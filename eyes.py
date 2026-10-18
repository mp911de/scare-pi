#!/usr/bin/env python3
"""Procedural eye animations on two HT16K33 8x8 matrices.

python3 eyes.py                 # story mode: sleep, wake, lurk, ... , doze, sleep
python3 eyes.py roll crazy      # play the named scenes once, then blank
python3 eyes.py --all --cap 2   # every scene in turn, each cut after 2 s, to cross-check them
python3 eyes.py --distance 1.2  # track: pupils move towards up/right as distance shrinks
Options: --addresses 0x70 0x71, --brightness 3, --fps 25, --rotate 0..3 (default 1).
Requires smbus2. The eye model is shared with sim/eyes.html.

An eye pose is Eye(open 0..1, px -1..1, py -1..1 with up positive, pupil size in
pixels, bright 0..1, scroll in rows, invert). Lit pixels form the eye, the pupil is
a dark hole; inverted, only the pupil is lit.
Scenes are keyframe lists [(seconds, Eye)], eased between frames; a None pose
means "stay where you are". LAYERS adds blinking and a heartbeat pulse per scene.
"""
import argparse
import math
import random
import sys
import time
from dataclasses import dataclass

EYE_SHAPE = ['00111100', '01111110', '11111111', '11111111',
             '11111111', '11111111', '01111110', '00111100']


@dataclass(frozen=True)
class Eye:
    open: float = 0.0
    px: float = 0.0
    py: float = 0.0
    pupil: int = 2
    bright: float = 1.0
    scroll: float = 0.0
    invert: bool = False

    def render(self):
        grid = self.render_eye()
        shift = round(self.scroll) % 8
        return grid[-shift:] + grid[:-shift] if shift else grid

    def render_eye(self):
        rows = round(self.open * 8)
        top = (8 - rows) // 2
        bottom = top + rows
        px = round(3.5 + self.px * 2.5)
        py = round(3.5 - self.py * 2.5)
        grid = []
        for y in range(8):
            row = []
            for x in range(8):
                lit = EYE_SHAPE[y][x] == '1' and top <= y < bottom
                lo_x, lo_y = px - self.pupil // 2, py - self.pupil // 2
                hole = lo_x <= x < lo_x + self.pupil and lo_y <= y < lo_y + self.pupil
                if self.invert:
                    lit = hole
                elif hole:
                    lit = False
                if rows == 0 and y == 3 and not self.invert:  # closed eye stays a slit
                    lit = EYE_SHAPE[y][x] == '1'
                row.append(lit)
            grid.append(row)
        return grid


def ease(t):
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def lerp(a, b, k):
    return a + (b - a) * k


def sample(frames, t):
    if t <= frames[0][0]:
        return frames[0][1]
    for (t0, a), (t1, b) in zip(frames, frames[1:]):
        if t <= t1:
            k = ease((t - t0) / (t1 - t0))
            return Eye(lerp(a.open, b.open, k), lerp(a.px, b.px, k), lerp(a.py, b.py, k),
                       round(lerp(a.pupil, b.pupil, k)), lerp(a.bright, b.bright, k),
                       lerp(a.scroll, b.scroll, k), b.invert)
    return frames[-1][1]


def rnd(a, b):
    return a + random.random() * (b - a)


def E(open=0.0, px=0.0, py=0.0, pupil=2, bright=1.0, scroll=0.0, invert=False):
    return Eye(open, px, py, pupil, bright, scroll, invert)


DIM, BRIGHT = 0.25, 1.0


def sleep_scene(d):
    t = rnd(3, 7)
    f = [(0, E(bright=DIM)), (t, E(bright=DIM)), (t + 0.2, E(0.2, 0, -0.5, bright=DIM)), (t + 0.5, E(bright=DIM))]
    return f, f


def wake_scene(d):
    f = [(0, E(bright=DIM)), (1.5, E(0.4, bright=DIM)), (1.9, E(bright=DIM)), (2.4, E(0.8, bright=0.5)),
         (3.0, E(1, -0.6, 0.2, bright=0.5)), (4.0, E(1, 0.7, 0.2, bright=0.5)), (5.0, E(1, bright=DIM))]
    return f, f


def lurk_scene(d):
    tx, ty, hold = rnd(-1, 1), rnd(-0.6, 0.6), rnd(1, 3)
    f = [(0, None), (0.8, E(1, tx, ty, bright=DIM)), (0.8 + hold, E(1, tx, ty, bright=DIM))]
    return f, f


def roll_scene(d):
    f = [(0, None)]
    for i in range(1, 17):
        a = i / 16 * 2 * math.pi
        f.append((i * 0.12, E(1, math.sin(a), math.cos(a))))
    f.append((2.3, E(1)))
    return f, f


def crazy_scene(d):
    # The whole frame scrolls through the matrix, as if a new frame came in from the top;
    # the other eye scrolls the opposite way. Three rounds, each one faster.
    l, t, scroll = [(0, None), (0.3, E(1))], 0.3, 0
    for rounds, step in ((1, 0.12), (2, 0.08), (3, 0.05)):
        for _ in range(rounds * 8):
            t += step
            scroll += 1
            l.append((t, E(1, scroll=scroll)))
    l.append((t + 0.5, E(1, scroll=scroll)))
    r = [(t, E(e.open, e.px, e.py, e.pupil, e.bright, -e.scroll) if e else None) for t, e in l]
    return l, r


def squint_scene(d):
    f = [(0, None), (0.6, E(0.5, 0.8, 0, bright=DIM)), (2.0, E(0.5, 0.8, 0, bright=DIM)),
         (2.5, E(0.5, -0.8, 0, bright=DIM)), (4.0, E(0.5, -0.8, 0, bright=DIM)), (4.5, E(1, bright=DIM))]
    return f, f


def track_scene(distance_m):
    k = min(1.0, max(0.0, 1 - (distance_m - 0.3) / 3.7))
    f = [(0, None), (0.5, E(1, k, k, bright=lerp(0.5, BRIGHT, k))), (1.0, E(1, k, k, bright=lerp(0.5, BRIGHT, k)))]
    return f, f


def jumpscare_scene(d):
    f = [(0, None), (0.08, E(1, 0.2, 0.3, 1)), (0.3, E(1, 0.2, 0.3, 1)), (0.4, E(1, -0.2, 0.3, 1)),
         (0.5, E(1, 0.2, 0.3, 1)), (0.6, E(1, -0.2, 0.3, 1)), (2.5, E(1, 0, 0.3, 1)), (3.0, E(1))]
    return f, f


def explode_scene(d):
    # Inverted: only the 2x2 pupil glows, then it grows until it bursts the whole matrix.
    f = [(0, None), (0.4, E(1, 0, 0, 2, invert=True)), (1.4, E(1, 0, 0, 2, invert=True)),
         (2.6, E(1, 0, 0, 9, invert=True)), (2.8, E(1, 0, 0, 9, 0.0, invert=True)), (3.3, E(1))]
    return f, f


def doze_scene(d):
    f = [(0, None), (2.0, E(0.4, 0, -0.3, bright=DIM)), (2.6, E(0.9, bright=DIM)),
         (4.5, E(0.3, 0, -0.4, bright=DIM)), (6.0, E(bright=DIM))]
    return f, f


SCENES = {name[:-6]: fn for name, fn in globals().items() if name.endswith('_scene')}
# Layers the player adds on top of a scene: 'blink' closes fully open eyes every few
# seconds, 'pulse' modulates brightness like a resting heartbeat.
LAYERS = {'sleep': {'pulse'}, 'lurk': {'blink', 'pulse'}, 'squint': {'blink', 'pulse'},
          'wake': {'blink', 'pulse'}, 'track': {'blink'}, 'doze': {'blink', 'pulse'}, 'roll': set(),
          'crazy': set(), 'jumpscare': set(), 'explode': set()}
BLINK_EVERY, BLINK_SECONDS = (2.5, 6.0), 0.24
PULSE_PERIOD = 1.1
PULSE_DEPTH = {'sleep': 0.3}   # how far the beat dips below full brightness; others use AWAKE_DEPTH
AWAKE_DEPTH = 0.7


def heartbeat(t, depth=AWAKE_DEPTH):
    """Lub-dub: two bumps per period, the second softer. Returns (1 - depth)..1."""
    phase = (t % PULSE_PERIOD) / PULSE_PERIOD
    bump = lambda c, w: math.exp(-((phase - c) / w) ** 2)
    return 1 - depth + depth * max(bump(0.0, 0.07), 0.7 * bump(0.22, 0.07))


class Blinker:
    def __init__(self):
        self.next_at = rnd(*BLINK_EVERY)

    def apply(self, eye, t):
        if eye.open < 0.9:
            return eye
        if t >= self.next_at + BLINK_SECONDS:
            self.next_at = t + rnd(*BLINK_EVERY)
        if t < self.next_at:
            return eye
        k = (t - self.next_at) / BLINK_SECONDS  # 0..1: close then open
        return Eye(eye.open * (1 - math.sin(k * math.pi)), eye.px, eye.py, eye.pupil, eye.bright,
                   eye.scroll, eye.invert)
STORY = ['sleep', 'sleep', 'wake', 'lurk', 'lurk', 'squint', 'lurk', 'roll',
         'lurk', 'crazy', 'lurk', 'explode', 'lurk', 'doze', 'sleep']


TRANSITION = 0.4  # seconds to glide from the current pose into a scene's first keyframe


def resolve(frames, pose):
    """Fill None poses with the current one and glide in when the scene starts elsewhere."""
    frames = [(t, e if e is not None else pose) for t, e in frames]
    if frames[0][1] != pose:
        frames = [(0, pose)] + [(t + TRANSITION, e) for t, e in frames]
    return frames


class Player:
    """Plays one scene at a time, keeps the pose between scenes and applies the layers."""
    def __init__(self):
        self.pose = [E(), E()]
        self.clips, self.layers, self.started, self.end, self.scene = None, set(), 0.0, 0.0, None
        self.blinker = Blinker()

    def start(self, name, now, distance=4.0):
        left, right = SCENES[name](distance)
        self.clips = [resolve(left, self.pose[0]), resolve(right, self.pose[1])]
        self.end = max(clip[-1][0] for clip in self.clips)
        self.layers, self.started, self.scene = LAYERS[name], now, name

    def done(self, now):
        return self.clips is None or now - self.started >= self.end

    def tick(self, now):
        if self.clips:
            self.pose = [sample(clip, now - self.started) for clip in self.clips]
        shown = self.pose
        if 'blink' in self.layers:
            shown = [self.blinker.apply(eye, now) for eye in shown]
        if 'pulse' in self.layers:
            beat = heartbeat(now, PULSE_DEPTH.get(self.scene, AWAKE_DEPTH))
            shown = [Eye(e.open, e.px, e.py, e.pupil, e.bright * beat, e.scroll, e.invert) for e in shown]
        return shown


class Matrices:
    """Two HT16K33 8x8 backpacks on one I2C bus. Adafruit bit layout: bit (x+7)%8 of row y."""
    def __init__(self, bus, addresses, brightness, rotate):
        self.bus, self.addresses, self.rotate = bus, addresses, rotate
        for addr in addresses:
            bus.write_byte(addr, 0x21)
            bus.write_byte(addr, 0xE0 | brightness)
            bus.write_byte(addr, 0x81)

    def show(self, eyes):
        for addr, eye in zip(self.addresses, eyes):
            self.bus.write_byte(addr, 0xE0 | round(eye.bright * 15))
            grid = eye.render()
            for _ in range(self.rotate):
                grid = [list(row) for row in zip(*grid[::-1])]
            data = []
            for row in grid:
                byte = 0
                for x, lit in enumerate(row):
                    if lit:
                        byte |= 1 << ((x + 7) % 8)
                data += [byte, 0]
            self.bus.write_i2c_block_data(addr, 0x00, data)

    def blank(self):
        for addr in self.addresses:
            self.bus.write_i2c_block_data(addr, 0x00, [0] * 16)
            self.bus.write_byte(addr, 0x80)


def play(matrices, names, fps, distance, cap=0):
    player = Player()
    for name in names:
        print(name, flush=True)
        player.start(name, time.monotonic(), distance)
        while True:
            now = time.monotonic()
            matrices.show(player.tick(now))
            if player.done(now) or (cap and now - player.started >= cap):
                break
            time.sleep(1 / fps)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('scenes', nargs='*', choices=[*SCENES, []], metavar='scene')
    parser.add_argument('--bus', type=int, default=1)
    parser.add_argument('--addresses', type=lambda v: int(v, 0), nargs=2, default=[0x70, 0x71])
    parser.add_argument('--brightness', type=int, choices=range(16), default=3)
    parser.add_argument('--fps', type=float, default=25)
    parser.add_argument('--rotate', type=int, choices=range(4), default=1,
                        help='quarter turns; the backpacks sit 90 degrees off (default: 1)')
    parser.add_argument('--distance', type=float, default=4.0, help='metres, for the track scene')
    parser.add_argument('--all', action='store_true', help='every scene once, in definition order')
    parser.add_argument('--cap', type=float, default=0, help='cut each scene after this many seconds')
    args = parser.parse_args()
    names = args.scenes or (list(SCENES) if args.all else ['track'] if args.distance < 4.0 else STORY * 1000)
    try:
        from smbus2 import SMBus
        with SMBus(args.bus) as bus:
            matrices = Matrices(bus, args.addresses, args.brightness, args.rotate)
            try:
                play(matrices, names, args.fps, args.distance, args.cap)
            finally:
                matrices.blank()
    except KeyboardInterrupt:
        print('\nStopped.')
    except ImportError:
        print('Missing dependency: install smbus2.', file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'I2C error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
