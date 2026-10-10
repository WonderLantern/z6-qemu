# SPDX-License-Identifier: GPL-2.0-or-later
"""QTest the actual CAPTG counter model, including 900 seconds.

Hardware count inputs are synthetic. This verifies timer deadlines and cancel,
not the sensor integration window or a firmware still-capture sequence.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    records = []
    with tempfile.TemporaryDirectory(prefix='z6-counter-time-') as directory:
        endpoint = str(Path(directory) / 'qtest.sock')
        log_path = Path(directory) / 'qemu.log'
        with log_path.open('w') as log:
            proc = subprocess.Popen([args.qemu, '-M', 'nikon-z6-display',
                                     '-accel', 'qtest', '-display', 'none',
                                     '-qtest', 'unix:'+endpoint+',server=on,wait=off'],
                                    env=dict(os.environ, Z6_MMIO_QUIET='1',
                                             Z6_TRACE_EXPOSURE='1'), stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if Path(endpoint).exists():
                        break
                    if proc.poll() is not None:
                        raise RuntimeError(log_path.read_text())
                    time.sleep(.05)
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.settimeout(15)
                    sock.connect(endpoint)
                    stream = sock.makefile('rwb', buffering=0)

                    def command(value):
                        stream.write((value+'\n').encode())
                        reply = stream.readline().decode().strip()
                        while reply.startswith('IRQ '):
                            reply = stream.readline().decode().strip()
                        assert reply.startswith('OK'), (value, reply)
                        return reply.split()[1:]

                    def write(address, value):
                        command(f'writel {address:#x} {value:#x}')

                    def read(address):
                        return int(command(f'readl {address:#x}')[0], 16)

                    # Channel11 keeps the finite-run channels0..4 separate.
                    cfg, status, mask = 0x2c011c00, 0x2c010c10, 1 << 11

                    def arm(ticks, clock=0x31):
                        write(0x2c011000, 0)
                        write(cfg, 1)
                        write(cfg, 0)
                        write(status, 0x3f)
                        write(cfg+4, clock)
                        write(cfg+8, 0xffffffff)
                        initial = (-ticks) & 0xffffffff
                        write(0x2c011004, initial)
                        write(0x2c011008, mask)
                        start = int(command('clock_step 1')[0], 0)
                        write(0x2c011000, mask)
                        assert read(cfg+12) == initial
                        return start, initial

                    for ticks in (125, 32_000_021, 60_000_021,
                                  900_000_000, 900_000_021):
                        start, initial = arm(ticks)
                        expected_ns = ticks * 1000
                        command(f'clock_step {expected_ns-1}')
                        assert read(status) == 0, 'no early terminal interrupt'
                        end = int(command('clock_step 1')[0], 0)
                        assert read(status) & 1, 'terminal must occur at deadline'
                        assert end-start == expected_ns
                        write(0x2c011000, 0)
                        records.append({'initial': initial, 'terminal': 0xffffffff,
                                        'ticks': ticks, 'tick_ns_hypothesis': 1000,
                                        'start_virtual_ns': start, 'end_virtual_ns': end,
                                        'elapsed_ns': end-start, 'result': 'PASS'})

                    start, _ = arm(900_000_000)
                    command('clock_step 1000000000')
                    write(0x2c011000, 0)
                    stopped_count = read(cfg+12)
                    command('clock_step 900000000000')
                    assert read(status) == 0, 'cancel must suppress terminal'
                    assert read(cfg+12) == stopped_count, 'stopped count must freeze'
                    records.append({'cancel_and_freeze': 'PASS'})

                    arm(125, clock=0x30)
                    command('clock_step 1000000')
                    assert read(status) == 0, 'unknown clock must not invent completion'
                    write(0x2c011000, 0)
                    records.append({'unsupported_clock_no_completion': 'PASS'})
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        traces = log_path.read_text()
        assert 'Z6_COUNTER_TIMING phase=start' in traces
        assert 'Z6_COUNTER_TIMING phase=terminal' in traces
        assert 'Z6_COUNTER_TIMING phase=stop' in traces
    report = {'scope': 'synthetic CAPTG counter device integration',
              'physical_tick_verified': False, 'sensor_integration_verified': False,
              'firmware_capture_verified': False, 'cases': records}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
