# SPDX-License-Identifier: GPL-2.0-or-later
"""Fetch verified upstream QEMU, apply the source overlay, and build ARM TCG."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '10.2.4'
SHA256 = '821b545b92f165e57dddccac5077d76d4d436a226595b8813ad59306bbfd0746'
SOURCES = ['qemu/nikon-z6.c','qemu/nikon-z6-profile.h','qemu/nikon-model-config.h','qemu/nikon-gpu.h','qemu/nikon-functional-isp.h','qemu/nikon-isp-pixels.h','qemu/prepare_source.py']

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024*1024): h.update(chunk)
    return h.hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work-dir',type=Path,default=ROOT/'.build')
    p.add_argument('--archive',type=Path,help='Optional pre-downloaded original upstream tarball')
    p.add_argument('--jobs',type=int,default=4)
    a = p.parse_args()
    if os.name == 'nt': p.error('Build in Linux or an explicitly selected WSL distribution')
    if not 1 <= a.jobs <= 64: p.error('--jobs must be 1..64')
    work = a.work_dir.resolve()
    work.mkdir(parents=True,exist_ok=True)
    archive = a.archive.resolve() if a.archive else work/f'qemu-{VERSION}.tar.xz'
    if not archive.exists():
        if a.archive: p.error('Requested archive does not exist')
        print('Downloading original upstream QEMU',flush=True)
        urllib.request.urlretrieve(f'https://download.qemu.org/qemu-{VERSION}.tar.xz',archive)
    if digest(archive) != SHA256: raise RuntimeError('Upstream QEMU archive SHA-256 mismatch')
    source = work/f'qemu-{VERSION}'
    marker = source/'.wonderlantern-extracted'
    if not marker.exists() or marker.read_text().strip() != SHA256:
        def source_filter(member, destination):
            # Upstream EDK2 contains host-header links for a separate ROM build.
            # They are unnecessary for this ARM emulator; never extract links
            # pointing outside the verified source archive's destination.
            try:
                return tarfile.data_filter(member, destination)
            except (tarfile.AbsoluteLinkError, tarfile.LinkOutsideDestinationError):
                return None
        with tarfile.open(archive,'r:xz') as t: t.extractall(work,filter=source_filter)
        marker.write_text(SHA256+'\n')
    subprocess.run(['python3',str(ROOT/'qemu/prepare_source.py'),str(source)],check=True)
    build = work/'build'
    build.mkdir(exist_ok=True)
    options = ['--target-list=arm-softmmu','--without-default-devices','--disable-docs','--disable-tools','--disable-user','--disable-werror','--disable-gtk','--disable-sdl','--disable-vnc','--disable-opengl','--disable-guest-agent','--disable-slirp','--disable-rust','--disable-debug-info']
    if not (build/'build.ninja').exists(): subprocess.run([str(source/'configure'),*options],cwd=build,check=True)
    subprocess.run(['ninja','-j',str(a.jobs),'qemu-system-arm'],cwd=build,check=True)
    binary = build/'qemu-system-arm'
    manifest = dict(qemu_version=VERSION,upstream_archive_sha256=SHA256,binary=str(binary),binary_sha256=digest(binary),sources={name:digest(ROOT/name) for name in SOURCES},configure=options)
    manifest['generated_core_sources'] = {name:digest(source/name) for name in ['hw/intc/arm_gic.c','target/arm/helper.c','target/arm/tcg/op_helper.c']}
    destination = ROOT/'.local/build-manifest.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    subprocess.run([str(binary),'--version'],check=True)
    print('Build manifest: '+str(destination),flush=True)

if __name__ == '__main__': main()
