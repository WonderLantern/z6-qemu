# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic Bayer stimulus for a future Z6 sensor input device.

Only a frame source: no guessed MMIO, DMA destinations or interrupts are used.
The selected bit depth, CFA and unpacked u16 storage are experiment parameters,
not claims about the Z6 sensor link or its firmware's RAW buffer format.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

PATTERNS = {'RGGB': ((0, 1), (1, 2)), 'BGGR': ((2, 1), (1, 0)),
            'GRBG': ((1, 0), (2, 1)), 'GBRG': ((1, 2), (0, 1))}


def mosaic(rgb, pattern, bits, black):
    if pattern not in PATTERNS or bits not in (10, 12, 14, 16):
        raise ValueError('Unsupported CFA or sample depth')
    maximum = (1 << bits)-1
    if not 0 <= black < maximum:
        raise ValueError('Invalid black level')
    rgb = np.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or not np.isfinite(rgb).all() or np.any(rgb < 0) or np.any(rgb > 1):
        raise ValueError('Expected finite linear RGB values in [0,1]')
    result = np.empty(rgb.shape[:2], dtype='<u2')
    for y in range(2):
        for x in range(2):
            result[y::2, x::2] = np.rint(black + rgb[y::2, x::2, PATTERNS[pattern][y][x]]*(maximum-black))
    return result


def scene(width, height, frame):
    if width < 16 or height < 16 or width % 2 or height % 2 or width*height > 64*1024*1024:
        raise ValueError('Use even dimensions of at least 16; at most 64 Mi pixels')
    if frame < 0:
        raise ValueError('Frame index must be nonnegative')
    bars = np.array([[1, 1, 1], [1, 1, 0], [0, 1, 1], [0, 1, 0],
                     [1, 0, 1], [1, 0, 0], [0, 0, 1], [0, 0, 0]], dtype=float)
    yy, xx = np.mgrid[:height, :width]
    rgb = bars[np.minimum(xx*8//width, 7)]
    # Lower half is a linear ramp: reveal black/white clipping and row order.
    ramp = xx/(width-1)
    rgb[height//2:] = ramp[height//2:, :, None]
    # A moving bright stripe makes stale/reordered input frames measurable.
    bottom = yy >= height*3//4
    stripe = ((xx-frame*4) % width) < max(2, width//32)
    rgb[bottom] = np.where(stripe[bottom, None], 1.0, .125)
    return rgb


def pack_rows(samples, stride=None):
    data = np.asarray(samples, dtype='<u2')
    if data.ndim != 2:
        raise ValueError('Expected 2D samples')
    h, w = data.shape
    stride = w*2 if stride is None else stride
    if stride < w*2 or stride % 2:
        raise ValueError('Stride must be even and contain all pixels')
    out = np.zeros((h, stride), dtype=np.uint8)
    out[:, :w*2] = data.view(np.uint8).reshape(h, w*2)
    return out.tobytes()
