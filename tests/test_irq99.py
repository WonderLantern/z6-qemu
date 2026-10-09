# SPDX-License-Identifier: GPL-2.0-or-later
"""QTest integration: pending RAW completion follows IRQ99 enable changes.

Runs a tiny dummy DMA in the actual device model, with the CPU stopped.
No firmware, camera, or card operations. Run under the Nikon WSL runtime.
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
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='z6-irq99-') as directory:
        endpoint = str(Path(directory) / 'qtest.sock')
        qmp_endpoint = str(Path(directory) / 'qmp.sock')
        env = dict(os.environ, Z6_IMAGE_PROCESS_TEST='1',
                   Z6_IMAGE_CONFIG_RECORD='1', Z6_ISP_BOUNDARY_TEST='1',
                   Z6_MMIO_QUIET='1')
        with open(Path(directory) / 'qemu.log', 'w') as log:
            proc = subprocess.Popen([args.qemu, '-M', 'nikon-z6-display',
                                     '-accel', 'qtest', '-display', 'none',
                                     '-qmp', 'unix:'+qmp_endpoint+',server=on,wait=off',
                                     '-qtest', 'unix:'+endpoint+',server=on,wait=off'],
                                    env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if Path(endpoint).exists():
                        break
                    if proc.poll() is not None:
                        raise RuntimeError(Path(directory, 'qemu.log').read_text())
                    time.sleep(.05)
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.connect(endpoint)
                    stream = sock.makefile('rwb', buffering=0)
                    irq_events = []

                    def command(value):
                        stream.write((value+'\n').encode())
                        reply = stream.readline().decode().strip()
                        while reply.startswith('IRQ '):
                            irq_events.append(reply)
                            reply = stream.readline().decode().strip()
                        assert reply.startswith('OK'), (value, reply)
                        return reply.split()[1:]

                    def write(address, value):
                        command(f'writel {address:#x} {value:#x}')

                    def read(address):
                        return int(command(f'readl {address:#x}')[0], 16)

                    with socket.socket(socket.AF_UNIX) as qmp:
                        qmp.connect(qmp_endpoint)
                        qmp_stream = qmp.makefile('rwb', buffering=0)
                        json.loads(qmp_stream.readline())

                        def query(execute, arguments=None):
                            request = {'execute': execute}
                            if arguments is not None:
                                request['arguments'] = arguments
                            qmp_stream.write((json.dumps(request)+'\n').encode())
                            while True:
                                response = json.loads(qmp_stream.readline())
                                if 'return' in response:
                                    return response['return']
                                if 'error' in response:
                                    raise RuntimeError(response)

                        query('qmp_capabilities')
                        cameras = sorted(m['name'] for m in query('query-machines')
                                         if m['name'].startswith('nikon-'))
                        assert cameras == ['nikon-z6-display'], cameras
                        memory_map = query('human-monitor-command', {'command-line': 'info mtree'})
                        assert 'z6-ram-' in memory_map, 'Z6 native memory windows missing'
                        for donor in ('z7-inferred-ram', 'z7-image-large-pool',
                                      'z7-gui-pool', 'z7-image-preview-pool',
                                      'z7-capture-pools-', 'z6-assisted-workram'):
                            assert donor not in memory_map, 'unexpected donor/wide backing: '+donor
                        children = query('qom-list', {'path': '/machine/unattached'})
                        private = next(p['name'] for p in children if 'a15mpcore_priv' in p['type'])
                    command('irq_intercept_in /machine/unattached/'+private)
                    irq_events.clear()
                    for base in (0x20140000, 0x20144000):
                        for value in (1, 0, 1):
                            write(base+0x1620, value)
                            assert read(base+0x1620) == value, 'native grid enable readback'
                    for address in (0x20065000, 0x20065400):
                        write(address, 0x100010)
                        assert read(address) == 0x100010, 'SDES configuration readback'
                        write(address, read(address) & ~0x10)
                        assert read(address) == 0x100000, 'SDES RMW must preserve bit20'
                    for offset, value in ((0x48, 0x14000e), (0x300, 2),
                                          (0x3e8, 2), (0x30c, 32), (0x3f0, 32),
                                          (0x310, 0xc1800000), (0x3ec, 0xc1800000)):
                        write(0x20380000+offset, value)
                    write(0x20380008, 1)
                    command('clock_step 2000000')
                    assert read(0x20380024) & 2, 'dummy DMA must really complete'
                    assert 'IRQ raise 67' not in irq_events, 'masked IRQ must stay low'
                    write(0x20380020, 2)
                    assert irq_events[-1] == 'IRQ raise 67', 'enabling pending IRQ must assert'
                    write(0x20380020, 0)
                    assert irq_events[-1] == 'IRQ lower 67', 'masking IRQ must deassert'
                    write(0x20380020, 2)
                    assert irq_events[-1] == 'IRQ raise 67', 'pending completion must reassert'
                    write(0x20380024, 2)
                    assert irq_events[-1] == 'IRQ lower 67', 'W1C must deassert'
                    print(json.dumps({'irq99_enable_pending_w1c': 'PASS',
                                      'sdes_configuration_readback': 'PASS',
                                      'native_grid_enable_readback': 'PASS',
                                      'z6_memory_profile_isolation': 'PASS',
                                      'z6_independent_machine_registration': 'PASS',
                                      'scope': 'QEMU device integration; no physical hardware'}))
            finally:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == '__main__':
    main()
