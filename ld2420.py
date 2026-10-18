#!/usr/bin/env python3
"""LD2420 driver (pyserial) with a CLI: handshake, firmware query, 1 Hz presence/range monitor.

python3 ld2420.py --new                 # >=1.5.3: 115200 baud, OT1 -> Pi RX
python3 ld2420.py --old                 # <=1.5.2: 256000 baud, OT2 -> Pi RX
Add --port /dev/ttyUSB0 to override /dev/serial0. Requires pyserial.
Pi TX connects to sensor RX. The mode flag cannot switch physical wiring.

Follows ESPHome: text reporting through v1.5.3, binary energy from v1.5.4.
Use --trace to log actual transmitted/received bytes to stderr. Applies a 5 m
software cutoff, without changing the sensor's range/threshold calibration.
Presence is yes only for a positive presence report with fresh range in (0, 500] cm.
Unknown/stale data is distinguished from absence. Ctrl+C closes the UART.
On a Pi, disable the serial console and point /dev/serial0 at the PL011
(ttyAMA0); the mini UART (ttyS0) cannot hold 256000 baud reliably.
Protocol reference:
https://github.com/esphome/esphome/blob/dev/esphome/components/ld2420/ld2420.cpp
https://github.com/esphome/esphome/blob/dev/esphome/components/ld2420/ld2420.h
"""
import argparse
import re
import struct
import sys
import time
from dataclasses import dataclass

HEADER = bytes.fromhex('fd fc fb fa')
FOOTER = bytes.fromhex('04 03 02 01')
ENERGY_HEADER = bytes.fromhex('f4 f3 f2 f1')
ENERGY_FOOTER = bytes.fromhex('f8 f7 f6 f5')
MAX_DISTANCE_CM = 500
STALE_SECONDS = 3.0
TOTAL_GATES = 16  # ld2420.h: TOTAL_GATES
ENERGY_BODY_SIZE = 1 + 2 + TOTAL_GATES * 2
SIMPLE_MODE = 0x0064
ENERGY_MODE = 0x0004


class ProtocolError(Exception):
    pass


def command_frame(command, payload=b''):
    body = struct.pack('<H', command) + payload
    return HEADER + struct.pack('<H', len(body)) + body + FOOTER


def decode_firmware(data):
    # handle_ack_data_: length at frame[10], string at frame[12].
    # data starts at frame[10]. ESPHome does not interpret frame[11].
    if len(data) < 2 or not 0 < data[0] <= len(data) - 2:
        raise ProtocolError('Firmware reply has an invalid version length')
    try:
        version = data[2:2 + data[0]].rstrip(b'\x00').decode('ascii')
    except UnicodeDecodeError as exc:
        raise ProtocolError('Firmware version is not ASCII') from exc
    if not re.fullmatch(r'v?\d+\.\d+\.\d+', version, re.IGNORECASE):
        raise ProtocolError(f'Unrecognized firmware version: {version!r}')
    return version


def reporting_mode(version):
    # setup()/CALIBRATE_VERSION_MIN: energy reporting starts at v1.5.4.
    parts = tuple(int(part) for part in version.lstrip('vV').split('.'))
    return ENERGY_MODE if parts >= (1, 5, 4) else SIMPLE_MODE


class StreamParser:
    """Bounded incremental framing; accept fragmented ACKs and text reports."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        events = []
        while self.buffer:
            candidates = [(self.buffer.find(h), h) for h in (HEADER, ENERGY_HEADER)]
            candidates = [(i, h) for i, h in candidates if i >= 0]
            frame_at, header = min(candidates, default=(-1, b''))
            newline = self.buffer.find(b'\n')
            if frame_at == 0:
                if len(self.buffer) < 6:
                    break
                length = struct.unpack_from('<H', self.buffer, 4)[0]
                # ESPHome frames on the footer and ignores the length field.
                # Accept any energy body holding presence + range; ACKs need
                # command + status.
                minimum = 3 if header == ENERGY_HEADER else 4
                if not minimum <= length <= 0x64:
                    del self.buffer[0]
                    continue
                total = length + 10
                if len(self.buffer) < total:
                    break
                footer = FOOTER if header == HEADER else ENERGY_FOOTER
                if self.buffer[total - 4:total] != footer:
                    del self.buffer[0]
                    continue
                if header == HEADER:
                    events.append(('ack', bytes(self.buffer[6:total - 4])))
                else:
                    events.append(('energy', bytes(self.buffer[6:total - 4])))
                del self.buffer[:total]
            elif newline >= 0 and (frame_at < 0 or newline < frame_at):
                events.append(('text', bytes(self.buffer[:newline]).strip()))
                del self.buffer[:newline + 1]
            elif frame_at > 0:
                del self.buffer[:frame_at]
            else:
                if len(self.buffer) > 512:
                    del self.buffer[:-3]  # Retain a possible partial frame header.
                break
        return events


@dataclass
class Reading:
    present: bool | None = None
    distance_cm: int | None = None
    last_report: float | None = None
    last_range_at: float | None = None

    def update(self, line, now):
        # handle_simple_mode_ scans ON/OFF and decimal digits in a CRLF line;
        # it does not require the literal "Range" label or spaces around ON.
        state = re.search(rb'OFF|ON', line)
        digits = bytes(value for value in line if 48 <= value <= 57)
        distance = int(digits) if digits and len(digits) <= 5 else None
        if state:
            present = state[0] == b'ON'
            if not present or self.present is not True:
                self.distance_cm = self.last_range_at = None
            self.present = present
        if distance is not None and (not state or state[0] == b'ON'):
            self.distance_cm = distance
            self.last_range_at = now
        if state or distance is not None:
            self.last_report = now

    def update_energy(self, body, now):
        # handle_energy_mode_: frame[6] presence, frame[7:9] cm,
        # frame[9:41] sixteen uint16 energies; ld2420.h: 45-byte frame.
        self.present = bool(body[0])
        self.distance_cm = struct.unpack_from('<H', body, 1)[0]
        self.last_report = self.last_range_at = now

    def state(self, now):
        """(present, distance_m, reason): present is True, False or None for unknown."""
        if self.last_report is None:
            return None, None, 'waiting for sensor data'
        if now - self.last_report > STALE_SECONDS:
            return None, None, 'sensor data stale'
        if self.present is False:
            return False, None, ''
        if (self.present is None or self.last_range_at is None
                or now - self.last_range_at > STALE_SECONDS
                or not self.distance_cm):
            return None, None, 'waiting for valid presence/range'
        if self.distance_cm > MAX_DISTANCE_CM:
            return False, None, 'outside 5.00 m cutoff'
        return True, self.distance_cm / 100, ''

    def summary(self, now):
        present, distance, reason = self.state(now)
        label = {True: 'yes', False: 'no', None: 'unknown'}[present]
        where = f'{distance:.2f} m' if distance else '--'
        return f'presence={label} distance={where}' + (f' ({reason})' if reason else '')


class Radar:
    def __init__(self, port, trace=False):
        self.port = port
        self.parser = StreamParser()
        self.reading = Reading()
        self.mode = None
        self.trace = trace
        self.received_bytes = 0
        self.energy_size_warned = False

    def trace_bytes(self, direction, data):
        if self.trace and data:
            print(f'{time.monotonic():.3f} {direction} {data.hex(" ")}',
                  file=sys.stderr, flush=True)

    def poll(self):
        raw = self.port.read(min(self.port.in_waiting or 1, 1024))
        self.received_bytes += len(raw)
        self.trace_bytes('RX', raw)
        events = self.parser.feed(raw)
        now = time.monotonic()
        for kind, data in events:
            if kind == 'text' and self.mode == SIMPLE_MODE:
                self.reading.update(data, now)
            elif kind == 'energy' and self.mode == ENERGY_MODE:
                if len(data) != ENERGY_BODY_SIZE and not self.energy_size_warned:
                    self.energy_size_warned = True
                    print(f'Energy frame body is {len(data)} bytes, expected {ENERGY_BODY_SIZE}; '
                          'decoding presence and range only.', file=sys.stderr, flush=True)
                self.reading.update_energy(data, now)
        return events

    def command(self, command, payload=b'', retries=3, timeout=1.0):
        before = self.received_bytes
        for _ in range(retries):
            frame = command_frame(command, payload)
            self.trace_bytes('TX', frame)
            self.port.write(frame)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for kind, body in self.poll():
                    if kind != 'ack':
                        continue
                    reply, status = struct.unpack_from('<HH', body)
                    if reply != (command | 0x0100):
                        continue
                    if status:
                        raise ProtocolError(f'Command 0x{command:04x} rejected: status 0x{status:04x}')
                    return body[4:]
        raise ProtocolError(f'No valid ACK for command 0x{command:04x} after {retries} attempts '
                            f'({self.received_bytes - before} bytes received; use --trace)')

    def initialize(self):
        # Leave configuration mode on any failure after the sensor entered it.
        configured = False
        try:
            self.command(0x00FF, struct.pack('<H', 2))
            configured = True
            print('Handshake: SUCCESS (configuration ACK received)', flush=True)
            data = self.command(0x0000)
            version = decode_firmware(data)
            print(f'Firmware: {version}', flush=True)
            self.mode = reporting_mode(version)
            # set_system_mode(): parameter 0, uint16 mode, uint16 reserved 0.
            self.command(0x0012, struct.pack('<HHH', 0, self.mode, 0))
        except BaseException:
            if configured:
                try:
                    self.command(0x00FE, retries=1)
                except (ProtocolError, OSError) as exc:
                    print(f'Could not exit configuration mode: {exc}', file=sys.stderr)
            raise
        self.command(0x00FE)
        self.reading = Reading()
        name = 'Binary energy' if self.mode == ENERGY_MODE else 'Simple text'
        print(f'{name} reporting enabled. Software cutoff: 5.00 m.', flush=True)

    def monitor(self):
        print('Printing at 1 Hz; Ctrl+C to stop.', flush=True)
        deadline = time.monotonic() + 1.0
        while True:
            self.poll()
            now = time.monotonic()
            if now >= deadline:
                print(f'{time.strftime("%H:%M:%S")} {self.reading.summary(now)}', flush=True)
                deadline += 1.0
                if deadline <= now:
                    deadline = now + 1.0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--old', action='store_true', help='256000 baud; sensor TX is OT2')
    modes.add_argument('--new', action='store_true', help='115200 baud; sensor TX is OT1')
    parser.add_argument('--port', default='/dev/serial0', help='UART device (default: /dev/serial0)')
    parser.add_argument('--trace', action='store_true', help='Log actual TX/RX bytes to stderr')
    args = parser.parse_args()
    baud = 256000 if args.old else 115200
    try:
        import serial
        print(f'Opening {args.port} at {baud} baud, 8N1; '
              f'sensor TX={"OT2" if args.old else "OT1"}', flush=True)
        with serial.Serial(args.port, baudrate=baud, timeout=0.05,
                           write_timeout=1, exclusive=True) as port:
            port.reset_input_buffer()
            radar = Radar(port, trace=args.trace)
            radar.initialize()
            radar.monitor()
    except KeyboardInterrupt:
        print('\nStopped; UART closed.')
        return 0
    except ImportError:
        print('Missing dependency: install pyserial for this Python interpreter.', file=sys.stderr)
        return 1
    except (OSError, ProtocolError) as exc:
        print(f'LD2420 test failed: {exc}\nCheck UART device/permissions, common ground, '
              'TX/RX wiring and --old/--new selection. On a Pi the serial console must be '
              'off and /dev/serial0 should be the PL011 (ttyAMA0).', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
