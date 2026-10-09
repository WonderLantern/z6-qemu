# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic source round trips and rejected RAW inputs; no firmware."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import numpy as np
from cmos_source import mosaic, pack_rows, scene
from photo_cmos import pack12, unpack12
from raw_input import RawSequence, STORAGE
from interactive import checked_firmware


class Inputs(unittest.TestCase):
    def test_bayer_roundtrips(self):
        for cfa in ('RGGB', 'BGGR', 'GRBG', 'GBRG'):
            samples = mosaic(scene(32, 16, 0), cfa, 12, 64)
            for stride in (48, 56):
                self.assertTrue(np.array_equal(samples, unpack12(pack12(samples, stride), 32, 16, stride)))
            self.assertEqual(len(pack_rows(samples, 72)), 16 * 72)
            self.assertTrue(np.array_equal(samples, np.frombuffer(pack_rows(samples, 72), dtype='<u2').reshape(16, 36)[:, :32]))

    def test_manifest_integrity_and_rejections(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = struct.pack('<4H', 64, 4095, 64, 4095)
            raw = root / 'frame.raw'
            raw.write_bytes(data)
            manifest = dict(width=2, height=2, stride_bytes=4, sample_bits=12,
                            cfa='RGGB', black_level=64, white_level=4095, fps=30,
                            storage=STORAGE, frames=[dict(index=0, timestamp_ns=0,
                            filename=raw.name, bytes=8, sha256=hashlib.sha256(data).hexdigest())])
            path = root / 'manifest.json'
            path.write_text(json.dumps(manifest))
            self.assertEqual(RawSequence(path).status()['validated_frames'], 1)
            raw.write_bytes(b'\0' * 8)
            with self.assertRaises(ValueError):
                RawSequence(path)
            raw.write_bytes(data)
            manifest['frames'][0]['filename'] = '../frame.raw'
            path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                RawSequence(path)

    def test_wrong_firmware_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'synthetic.bin'
            path.write_bytes(bytes(16))
            with self.assertRaises(ValueError):
                checked_firmware(path)
            with path.open('wb') as stream:
                stream.truncate(33502842)
            with self.assertRaises(ValueError):
                checked_firmware(path)


if __name__ == '__main__':
    unittest.main()
