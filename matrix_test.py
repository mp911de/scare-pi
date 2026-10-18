#!/usr/bin/env python3
"""Alternate two HT16K33 8x8 matrices until Ctrl+C (then blank both).

python3 matrix_test.py --addresses 0x70 0x71
Requires smbus2. Each display is on for 0.5 s and off for 0.5 s (1 Hz).
Use --bicolor for red/green backpacks; illuminated pixels will be yellow.
Protocol: https://github.com/adafruit/Adafruit_CircuitPython_HT16K33
"""
import argparse
import sys
import time


def address(value):
    try:
        result = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Use an address such as 0x70') from exc
    if not 0x70 <= result <= 0x77:
        raise argparse.ArgumentTypeError('HT16K33 addresses must be 0x70..0x77')
    return result


def fill(bus, addr, enabled, bicolor=False):
    row = [255, 255 if bicolor else 0] if enabled else [0, 0]
    bus.write_i2c_block_data(addr, 0x00, row * 8)


def blink(bus, addresses, brightness, bicolor):
    try:
        for addr in addresses:
            bus.write_byte(addr, 0x21)  # Oscillator on.
            fill(bus, addr, False, bicolor)
            bus.write_byte(addr, 0xE0 | brightness)
            bus.write_byte(addr, 0x81)  # Display on, hardware blink disabled.
        print(f'Alternating {addresses[0]:#04x} / {addresses[1]:#04x}: '
              '1 Hz per matrix, swapping every 0.5 s. Ctrl+C to stop.', flush=True)
        active = 0
        while True:
            started = time.monotonic()
            fill(bus, addresses[1 - active], False, bicolor)
            fill(bus, addresses[active], True, bicolor)
            time.sleep(max(0, 0.5 - (time.monotonic() - started)))
            active = 1 - active
    finally:
        # Attempt both even if one device failed or initialization was interrupted.
        for addr in addresses:
            try:
                fill(bus, addr, False, bicolor)
                bus.write_byte(addr, 0x80)
            except OSError as exc:
                print(f'Could not blank {addr:#04x}: {exc}', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bus', type=int, default=1, help='I2C bus number (default: 1)')
    parser.add_argument('--addresses', type=address, nargs=2, default=[0x70, 0x71],
                        metavar=('FIRST', 'SECOND'))
    parser.add_argument('--brightness', type=int, choices=range(16), default=3,
                        help='HT16K33 brightness 0..15 (default: 3)')
    parser.add_argument('--bicolor', action='store_true')
    args = parser.parse_args()
    if args.bus < 0 or args.addresses[0] == args.addresses[1]:
        parser.error('Use a nonnegative bus number and two different addresses')
    try:
        from smbus2 import SMBus
        with SMBus(args.bus) as bus:
            blink(bus, args.addresses, args.brightness, args.bicolor)
    except KeyboardInterrupt:
        print('\nStopped.')
        return 0
    except ImportError:
        print('Missing dependency: install smbus2 for this Python interpreter.', file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'I2C error: {exc}\nCheck the bus, addresses, wiring and device permissions.',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
