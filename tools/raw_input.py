# SPDX-License-Identifier: GPL-2.0-or-later
"""Validated, immutable Bayer input frames for the Z6 emulator harness.

This is the host side of the input boundary. Loading or reading a frame does
not transfer it to guest RAM, raise an interrupt, or establish its Z6 format.
"""
from array import array
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys


STORAGE = 'little-endian uint16, right justified'
CFAS = ('RGGB', 'BGGR', 'GRBG', 'GBRG')


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'Invalid {name}: expected integer {minimum}..{maximum}')
    return value


@dataclass(frozen=True)
class RawFrame:
    index: int
    timestamp_ns: int
    sha256: str
    data: bytes


class RawSequence:
    def __init__(self, manifest):
        self.path = Path(manifest).resolve(strict=True)
        if self.path.stat().st_size > 256*1024:
            raise ValueError('RAW manifest exceeds 256 KiB')
        encoded = self.path.read_bytes()
        m = json.loads(encoded)
        if not isinstance(m, dict) or m.get('storage') != STORAGE:
            raise ValueError('Expected an unpacked little-endian uint16 RAW manifest')
        self.width = integer(m.get('width'), 'width', 2, 65536)
        self.height = integer(m.get('height'), 'height', 2, 65536)
        if self.width % 2 or self.height % 2 or self.width*self.height > 64*1024*1024:
            raise ValueError('Expected even Bayer dimensions, at most 64 Mi pixels')
        self.bits = integer(m.get('sample_bits'), 'sample_bits', 10, 16)
        if self.bits not in (10, 12, 14, 16):
            raise ValueError('Unsupported RAW sample depth')
        self.cfa = m.get('cfa')
        if self.cfa not in CFAS:
            raise ValueError('Expected a 2x2 Bayer CFA')
        self.stride = integer(m.get('stride_bytes'), 'stride_bytes', self.width*2, 262144)
        if self.stride % 2 or self.stride*self.height > 128*1024*1024:
            raise ValueError('Invalid RAW row stride or frame size')
        self.black = integer(m.get('black_level'), 'black_level', 0, (1 << self.bits)-2)
        self.white = integer(m.get('white_level'), 'white_level', self.black+1, (1 << self.bits)-1)
        self.fps = integer(m.get('fps'), 'fps', 1, 240)
        frames = m.get('frames')
        if not isinstance(frames, list) or not 1 <= len(frames) <= 120:
            raise ValueError('Expected 1..120 RAW frames')
        self.records = []
        previous_time = -1
        for index, record in enumerate(frames):
            if not isinstance(record, dict) or integer(record.get('index'), 'frame index', 0, 119) != index:
                raise ValueError('RAW frame indices must be contiguous from zero')
            timestamp = integer(record.get('timestamp_ns'), 'timestamp_ns', 0, (1 << 63)-1)
            if timestamp <= previous_time:
                raise ValueError('RAW timestamps must increase')
            previous_time = timestamp
            name = record.get('filename')
            if not isinstance(name, str) or not name or '/' in name or '\\' in name or ':' in name:
                raise ValueError('RAW filenames must be local basenames')
            path = self.path.parent/name
            if path.resolve(strict=True).parent != self.path.parent:
                raise ValueError('RAW file escapes the sequence directory')
            if integer(record.get('bytes'), 'bytes', 1, 128*1024*1024) != self.stride*self.height:
                raise ValueError('RAW byte count does not match dimensions and stride')
            digest = record.get('sha256')
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid RAW SHA-256')
            self.records.append((path, timestamp, digest))
        self.records = tuple(self.records)
        self.manifest_sha256 = hashlib.sha256(encoded).hexdigest()
        # Check every input before accepting the sequence, without retaining a
        # potentially large sequence in RAM. read_frame also checks at use time.
        for index in range(len(self.records)):
            self.read_frame(index)

    def read_frame(self, index):
        integer(index, 'frame index', 0, len(self.records)-1)
        path, timestamp, expected_digest = self.records[index]
        if path.resolve(strict=True).parent != self.path.parent:
            raise ValueError('RAW file escapes the sequence directory')
        expected = self.stride*self.height
        with path.open('rb') as source:
            data = source.read(expected+1)
        if len(data) != expected:
            raise ValueError(f'RAW size mismatch: {path.name}')
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_digest:
            raise ValueError(f'RAW SHA-256 mismatch: {path.name}')
        maximum = (1 << self.bits)-1
        for y in range(self.height):
            row = data[y*self.stride:y*self.stride+self.width*2]
            values = array('H', row)
            if sys.byteorder != 'little':
                values.byteswap()
            if max(values) > maximum:
                raise ValueError(f'RAW sample exceeds {self.bits} bits: {path.name}, row {y}')
        return RawFrame(index, timestamp, digest, data)

    def status(self):
        return dict(state='loaded', manifest=str(self.path), manifest_sha256=self.manifest_sha256,
                    width=self.width, height=self.height, sample_bits=self.bits, cfa=self.cfa,
                    storage=STORAGE, stride_bytes=self.stride, black_level=self.black,
                    white_level=self.white, fps=self.fps, validated_frames=len(self.records),
                    guest_frames_transferred=0, firmware_frames_consumed=0,
                    firmware_layout_verified=False, cmos_input_connected=False,
                    blocked_by='Native RAW buffer layout, destination and completion event are not established')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    print(json.dumps(RawSequence(parser.parse_args().manifest).status(), indent=2))
