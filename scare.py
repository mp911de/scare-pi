#!/usr/bin/env python3
"""The Halloween show: LD2420 radar, two HT16K33 eyes, one audio stream, one process.

python3 scare.py                        # reads scare.toml next to this file
python3 scare.py --simulated-presence-distance 1.5   # no radar; a visitor at 1.5 m
Ctrl+C blanks the eyes and closes the stream.
"""
import argparse
import pathlib
import sys
import time
import tomllib

import audio
import eyes
import ld2420
from director import Director


class SimulatedRadar:
    """Stands in for ld2420.Radar: a visitor at a fixed distance, or nobody."""
    def __init__(self, distance):
        self.distance = distance
        self.reading = self

    def poll(self):
        pass

    def state(self, now):
        return (self.distance is not None, self.distance, '')


def open_radar(config, trace):
    import serial
    port = serial.Serial(config['port'], baudrate=config['baud'], timeout=0,
                         write_timeout=1, exclusive=True)
    port.reset_input_buffer()
    radar = ld2420.Radar(port, trace=trace)
    radar.initialize()
    return radar


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=pathlib.Path(__file__).with_name('scare.toml'))
    parser.add_argument('--simulated-presence-distance', type=float, metavar='M',
                        help='no radar; a visitor standing at this distance in metres')
    parser.add_argument('--trace', action='store_true', help='log radar bytes to stderr')
    args = parser.parse_args()
    config = tomllib.loads(pathlib.Path(args.config).read_text())
    root = pathlib.Path(args.config).parent
    sounds = [audio.load(path) for path in sorted((root / config['sounds']['dir']).glob('*.wav'))]
    from smbus2 import SMBus
    simulated = args.simulated_presence_distance
    radar = SimulatedRadar(simulated) if simulated is not None else open_radar(config['radar'], args.trace)
    mixer = audio.Mixer(config['audio']['device'])
    player = eyes.Player()
    director = Director(config, player, mixer, sounds)
    e = config['eyes']
    try:
        with SMBus(1) as bus:
            matrices = eyes.Matrices(bus, e['addresses'], 15, e['rotate'])
            try:
                reading = ''
                while True:
                    radar.poll()
                    now = time.monotonic()
                    present, distance, reason = radar.reading.state(now)
                    director.update(now, present, distance)
                    line = f'{player.scene:<10} presence={present} {reason}'
                    if line != reading:  # log scene and presence changes, not every centimetre
                        reading = line
                        print(f'{time.strftime("%H:%M:%S")} {line} at {distance} m', flush=True)
                    matrices.show(player.tick(now))
                    time.sleep(1 / e['fps'])
            finally:
                matrices.blank()
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        mixer.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
