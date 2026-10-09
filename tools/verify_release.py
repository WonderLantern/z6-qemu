# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify the declared public source inventory; ignore local runtime output."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.local', '.build', '.venv', '.git', '__pycache__'}
MANIFEST = ROOT / 'publication-manifest.json'


def inventory():
    result = {}
    for folder, directories, names in os.walk(ROOT):
        directories[:] = sorted(d for d in directories if d not in IGNORED)
        for name in directories + names:
            if (Path(folder) / name).is_symlink():
                raise ValueError('Public symlink: ' + str(Path(folder) / name))
        for name in sorted(names):
            path = Path(folder) / name
            relative = path.relative_to(ROOT)
            if path == MANIFEST:
                continue
            data = path.read_bytes()
            data.decode('utf-8')
            if path.suffix.lower() in {'.bin', '.bi', '.raw', '.raw12', '.wav', '.log', '.png', '.jpg'}:
                raise ValueError('Non-source asset: ' + str(relative))
            result[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    return result


if __name__ == '__main__':
    files = inventory()
    if sys.argv[1:] == ['--refresh']:
        MANIFEST.write_text(json.dumps(dict(format=1, model='Nikon Z6',
            firmware_included=False, files=files), indent=2) + '\n', encoding='utf-8')
    elif sys.argv[1:]:
        raise SystemExit('Usage: python tools/verify_release.py [--refresh]')
    expected = json.loads(MANIFEST.read_text(encoding='utf-8'))['files']
    if expected != files:
        raise SystemExit('Public source inventory differs; review before --refresh')
    print(f'PASS {len(files)} declared UTF-8 source files; hashes match')
