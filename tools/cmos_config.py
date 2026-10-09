# SPDX-License-Identifier: GPL-2.0-or-later
"""Local stimulus selection. Generated data stays outside the public tree."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / '.local/cmos'

def active_manifest(kind='unpacked'):
    try:
        config = json.loads((ROOT/'active.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise RuntimeError('Generate CMOS inputs first: python3 tools/make_cmos.py') from None
    path = (ROOT / config[kind]).resolve(strict=True)
    path.relative_to(ROOT.resolve())
    return path

def active_ingress(kind='ingress'):
    path = active_manifest(kind)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    frame = manifest['frames'][0]
    raw = (path.parent/frame['filename']).resolve(strict=True)
    raw.relative_to(path.parent)
    data = raw.read_bytes()
    if len(data) != manifest['height']*manifest['stride_bytes'] or hashlib.sha256(data).hexdigest() != frame['sha256']:
        raise ValueError('Active CMOS input integrity mismatch')
    return raw
