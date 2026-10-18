#!/usr/bin/env python3
"""Play beep, silence, a sound file, silence, beep as ONE uninterrupted stream.

python3 audio_test.py sounds/T01.ogg [--gap 2] [--device default]
Decodes with ffmpeg to 44.1 kHz stereo s16le and pipes everything into a
single aplay process. A click heard only after the final beep comes from the
stream closing (amp shutdown), not from the audio itself.
"""
import argparse
import math
import subprocess
import sys

RATE = 44100
CHANNELS = 2
FRAME = 2 * CHANNELS  # s16le


def beep(seconds=0.15, hz=880, volume=0.3):
    frames = int(RATE * seconds)
    samples = bytearray()
    for i in range(frames):
        fade = min(1.0, i / 200, (frames - i) / 200)
        value = int(32767 * volume * fade * math.sin(2 * math.pi * hz * i / RATE))
        samples += value.to_bytes(2, 'little', signed=True) * CHANNELS
    return bytes(samples)


def silence(seconds):
    return bytes(int(RATE * seconds) * FRAME)


def decode(path):
    return subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', path, '-f', 's16le', '-acodec', 'pcm_s16le',
         '-ac', str(CHANNELS), '-ar', str(RATE), '-'],
        check=True, capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sound')
    parser.add_argument('--gap', type=float, default=2.0, help='silence around the sound in s')
    parser.add_argument('--device', default='default')
    args = parser.parse_args()
    stream = beep() + silence(args.gap) + decode(args.sound) + silence(args.gap) + beep()
    print(f'{len(stream) / FRAME / RATE:.1f} s in one stream on {args.device}', flush=True)
    subprocess.run(['aplay', '-q', '-D', args.device, '-t', 'raw', '-f', 'S16_LE',
                    '-r', str(RATE), '-c', str(CHANNELS)], input=stream, check=True)


if __name__ == '__main__':
    sys.exit(main())
