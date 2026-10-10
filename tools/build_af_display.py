# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a QEMU-only batch in a fresh directory; never creates firmware."""
from pathlib import Path
import argparse, shutil
import hashlib, json, subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--toolchain-dir', type=Path, help='Directory containing ARM GNU tools; otherwise search PATH')
options = parser.parse_args()
out = ROOT/'.local/af-display-build'
out.mkdir(parents=True, exist_ok=True)
(out/'af_batch.c').write_bytes((ROOT/'tools/af_batch.c').read_bytes())
(out/'link.ld').write_text('ENTRY(af_batch)\nSECTIONS { . = 0x40000000; .text : { *(.text*) *(.rodata*) } /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) } }\n')
def tool(name, *args):
    executable = None
    if options.toolchain_dir:
        for suffix in ('', '.exe'):
            candidate = options.toolchain_dir / (name+suffix)
            if candidate.is_file():
                executable = str(candidate.resolve())
                break
    else:
        executable = shutil.which(name)
    if executable is None:
        raise RuntimeError('Missing ARM GNU tool: '+name+'; install it or use --toolchain-dir')
    result = subprocess.run([executable, *map(str,args)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(name+' failed: '+result.stderr)
    return result.stdout
tool('arm-none-eabi-gcc','-mthumb','-march=armv7-a','-mfloat-abi=soft','-Os',
     '-ffreestanding','-fno-builtin','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
     '-nostdlib','-Wall','-Wextra',out/'af_batch.c','-Wl,-T,'+str(out/'link.ld'),'-o',out/'batch.elf')
assert not tool('arm-none-eabi-nm','-u',out/'batch.elf').strip()
symbols=tool('arm-none-eabi-nm','-n',out/'batch.elf')
entry=next(int(line.split()[0],16)-0x40000000 for line in symbols.splitlines() if line.split()[-1]=='af_batch')
offsets={line.split()[-1]:int(line.split()[0],16)-0x40000000 for line in symbols.splitlines() if line.split()[-1] in ('pattern_begin','pattern_capture')}
tool('arm-none-eabi-objcopy','-O','binary',out/'batch.elf',out/'batch.raw')
(out/'batch.disasm').write_text(tool('arm-none-eabi-objdump','-d',out/'batch.elf'))
blob=(out/'batch.raw').read_bytes()
assert len(blob)<4096
(out/'build.json').write_text(json.dumps({'entry_offset':entry,'observation_offsets':offsets,'code_bytes':len(blob),'code_sha256':hashlib.sha256(blob).hexdigest(),'scope':'QEMU AF diagnostic; original geometry and GPU, not AF algorithm','source_sha256':hashlib.sha256((out/'af_batch.c').read_bytes()).hexdigest()},indent=2))
print(out)
