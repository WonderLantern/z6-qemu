# SPDX-License-Identifier: GPL-2.0-or-later
"""Reproducible photo-derived CMOS inputs. Nikon packing remains a hypothesis."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from cmos_source import mosaic, pack_rows

ROOT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def linear_photo(photo, width, height):
    # Stretch the complete image; interpolate linear light before applying CFA.
    srgb = np.asarray(photo, dtype=np.float32) / 255
    linear = np.where(srgb <= .04045, srgb / 12.92, ((srgb + .055) / 1.055) ** 2.4)
    return np.clip(np.stack([
        np.asarray(Image.fromarray(linear[:, :, c]).resize((width, height), Image.Resampling.BICUBIC))
        for c in range(3)], axis=2), 0, 1)


def pack12(samples, stride):
    h, w = samples.shape
    if w % 2 or stride < w * 3 // 2 or np.any(samples > 4095):
        raise ValueError('Invalid packed12 geometry or samples')
    out = np.zeros((h, stride), dtype=np.uint8)
    pairs = out[:, :w * 3 // 2].reshape(h, w // 2, 3)
    a, b = samples[:, ::2], samples[:, 1::2]
    pairs[:, :, 0] = a & 255
    pairs[:, :, 1] = (a >> 8) | ((b & 15) << 4)
    pairs[:, :, 2] = b >> 4
    return out.tobytes()


def unpack12(data, width, height, stride):
    pairs = np.frombuffer(data, dtype=np.uint8).reshape(height, stride)[:, :width * 3 // 2]
    pairs = pairs.reshape(height, width // 2, 3).astype(np.uint16)
    out = np.empty((height, width), dtype='<u2')
    out[:, ::2] = pairs[:, :, 0] | ((pairs[:, :, 1] & 15) << 8)
    out[:, 1::2] = (pairs[:, :, 1] >> 4) | (pairs[:, :, 2] << 4)
    return out
