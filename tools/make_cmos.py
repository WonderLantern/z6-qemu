# SPDX-License-Identifier: GPL-2.0-or-later
"""Create a synthetic scene or convert your own image to three Bayer inputs."""
import argparse
import hashlib
import json
import secrets
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from cmos_source import scene, mosaic, pack_rows
from photo_cmos import linear_photo, pack12, unpack12

ROOT = Path(__file__).resolve().parents[1]/'.local/cmos'

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, help='Optional locally owned RGB image; no image is distributed')
    a = p.parse_args()
    image = None
    if a.image:
        with Image.open(a.image) as im:
            image = ImageOps.exif_transpose(im).convert('RGB')
    folder = ROOT/secrets.token_hex(8)
    folder.mkdir(parents=True)
    config = {}
    for kind,w,h,stride,packed in [('unpacked',640,480,1280,False), ('ingress',1380,918,2080,True), ('native0',2034,1434,4080,False)]:
        directory = folder/kind
        directory.mkdir()
        rgb = linear_photo(image,w,h) if image is not None else scene(w,h,0)
        samples = mosaic(rgb,'RGGB',12,64)
        raw = pack12(samples,stride) if packed else pack_rows(samples,stride)
        decoded = unpack12(raw,w,h,stride) if packed else np.frombuffer(raw,dtype='<u2').reshape(h,stride//2)[:,:w]
        if not np.array_equal(samples,decoded):
            raise ValueError('RAW packing failed round trip')
        filename = 'frame.raw12' if packed else 'frame.raw'
        (directory/filename).write_bytes(raw)
        srgb = np.where(rgb<=.0031308,12.92*rgb,1.055*np.power(rgb,1/2.4)-.055)
        Image.fromarray(np.rint(np.clip(srgb,0,1)*255).astype(np.uint8)).save(directory/'reference.png')
        digest = hashlib.sha256(raw).hexdigest()
        manifest = dict(kind='synthetic CMOS stimulus' if image is None else 'locally supplied photo CMOS stimulus',
            width=w,height=h,stride_bytes=stride,sample_bits=12,cfa='RGGB',
            storage='two samples in three little-endian bytes' if packed else 'little-endian uint16, right justified',
            black_level=64,white_level=4095,fps=30,firmware_layout_verified=False,
            packing_roundtrip_equal=True,frames=[dict(index=0,timestamp_ns=0,filename=filename,bytes=len(raw),sha256=digest)])
        manifest_path = directory/'manifest.json'
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        config[kind] = manifest_path.relative_to(ROOT).as_posix()
    (ROOT/'active.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    print('Generated and activated '+str(folder))
    print('RAW layouts are emulator hypotheses, not verified sensor wire formats.')

if __name__ == '__main__':
    main()
