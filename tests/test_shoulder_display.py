# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute native MCU ingress, publication and rendering with bounded fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from shoulder_display import ShoulderDisplay, rgb
from interactive import rgb_png


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--firmware', type=Path, required=True)
    p.add_argument('--data', type=Path, help='Optional reference SRAM data; runtime decompresses original firmware')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    panel = ShoulderDisplay(a.firmware, a.data)
    state = bytearray(0x70)
    state[0] = 4
    cases = []
    frames = {}
    def capture(name):
        frame = panel.receive(state)
        frames[name] = frame
        (a.out/(name+'.bin')).write_bytes(frame)
        (a.out/(name+'.png')).write_bytes(rgb_png(128, 96, rgb(frame)))
        cases.append(dict(name=name, lit_pixels=sum(b.bit_count() for b in frame),
                          sha256=hashlib.sha256(frame).hexdigest()))
        return frame
    assert not any(capture('disabled'))
    state[5] = state[0xE] = 1
    state[0x10:0x14] = bytes([5,2,1,0])
    assert any(capture('digits'))
    state[0x10:0x14] = bytes([0,0,0,8])
    assert capture('different_digits') != frames['digits']
    state[0xE] = 2
    state[5] = 0
    assert not any(capture('blink_off'))
    state[5] = 1
    assert capture('blink_on') == frames['different_digits']
    state[0xE] = 0
    assert not any(capture('cleared'))
    for bad in [b'', bytes(0x70), bytes(0x71), bytes(0x72)]:
        try:
            panel.receive(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('Malformed payload accepted')
    report = dict(passed=True, cases=cases, malformed_rejections=4,
                  **panel.evidence(), input_source='controlled native semantic snapshots',
                  camera_tested=False)
    (a.out/'validation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
