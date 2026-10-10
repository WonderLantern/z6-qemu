# SPDX-License-Identifier: GPL-2.0-or-later
"""Diagnostic AF geometry/state; original ROM helpers and GPU, no AF algorithm."""
from pathlib import Path
import hashlib
import json
import struct
from probe import call_fixture

KEYS = {'af_s', 'af_l', 'af_toggle', 'af_left', 'af_right', 'af_up', 'af_down',
        'af_idle', 'af_locked', 'af_failed'}
COLORS = {'idle': 0xffffffff, 'locked': 0x00ff00ff, 'failed': 0xff0000ff}


def borders(rect, color):
    x0, y0, x1, y1 = rect
    return [(x0,y0,x1,y0+2,color),(x0,y1-2,x1,y1,color),
            (x0,y0+2,x0+2,y1-2,color),(x1-2,y0+2,x1,y1-2,color)]


def invoke(camera, packet, label, fn, payload, args, thumb=True):
    r = call_fixture(camera.remote, packet, fn, payload, args, thumb=thumb)
    camera.audit({'kind':'af-display-native-call','name':label,'result':r})
    return 'T05thread:'+r['return_cpu']+';', r


def geometry(camera, packet, mode, center):
    # Original ordinary S/L branch; no fabricated sensor AF result is published.
    gate = int.from_bytes(camera.remote.memory(0xc181b828,4),'little')
    if gate:
        raise RuntimeError('AF geometry special branch active; ordinary S/L fixture rejected')
    data = bytearray(1088)
    data[4] = 3 if mode == 'S' else 4
    struct.pack_into('<2H',data,8,720,480)
    packet, r = invoke(camera,packet,'原厂 S/L 尺寸',0x103679d2,bytes(data),
                        [('scratch',0),('scratch',8),('scratch',12),('scratch',32)])
    data = bytearray.fromhex(r['output'])
    w,h = struct.unpack_from('<2H',data,12)
    if not 6 <= w < 700 or not 6 <= h < 460:
        raise RuntimeError('Original AF geometry did not produce bounded dimensions')
    cx = max(w//2+8,min(720-w//2-8,center[0]))
    cy = max(h//2+8,min(480-h//2-8,center[1]))
    struct.pack_into('<2H',data,16,cx,cy)
    packet,r = invoke(camera,packet,'原厂 AF 中心转矩形',0x103678fc,bytes(data),
                      [('scratch',20),('scratch',16),('scratch',12)])
    rect = struct.unpack_from('<4h',bytes.fromhex(r['output']),20)
    if not (0 <= rect[0] < rect[2] <= 720 and 0 <= rect[1] < rect[3] <= 480):
        raise RuntimeError('Original AF rectangle outside source viewport')
    return packet,rect,(cx,cy),(w,h)


def backend(camera, packet):
    if camera.focus_code:
        return packet,camera.focus_code
    folder = Path(__file__).resolve().parent.parent/'.local/af-display-build'
    if not (folder/'build.json').is_file() or not (folder/'batch.raw').is_file():
        raise RuntimeError('Build the AF display helper first: python tools/build_af_display.py')
    meta = json.loads((folder/'build.json').read_text())
    code = (folder/'batch.raw').read_bytes()
    source = Path(__file__).with_name('af_batch.c').read_bytes()
    if hashlib.sha256(code).hexdigest()!=meta['code_sha256'] or hashlib.sha256(source).hexdigest()!=meta['source_sha256']:
        raise RuntimeError('AF diagnostic helper changed; rebuild with build_af_display.py')
    packet,r = invoke(camera,packet,'分配 AF 诊断绘制辅助',0x10164a44,bytes(8),[len(code)+127,0])
    allocation = int(r['return_r0'],16)
    if not allocation:
        raise RuntimeError('AF diagnostic allocation failed')
    address = (allocation+63)&~63
    assert camera.remote.command(f'M{address:x},{len(code):x}:'+code.hex())=='OK'
    packet,_ = invoke(camera,packet,'AF 辅助 D cache',0x100398b0,bytes(8),[address,(len(code)+63)&~63],False)
    packet,_ = invoke(camera,packet,'AF 辅助 I cache',0x10039890,bytes(8),[address,(len(code)+63)&~63],False)
    camera.focus_code = address+meta['entry_offset']
    camera.audit({'kind':'af-display-diagnostic-allocation','code_sha256':meta['code_sha256'],
                  'allocation':hex(allocation),'entry':hex(camera.focus_code),
                  'firmware_code_modified':False})
    return packet,camera.focus_code


def apply(camera, packet, key=None):
    focus = dict(camera.focus_state)
    focus['center'] = list(focus['center'])
    if key in ('af_s','af_l'):
        focus.update(mode=key[-1].upper(),enabled=True)
    elif key=='af_toggle':
        focus['enabled'] = not focus['enabled']
    elif key in ('af_idle','af_locked','af_failed') and focus['enabled']:
        focus['status'] = key[3:]
    elif key in ('af_left','af_right','af_up','af_down') and focus['enabled']:
        dx,dy = {'af_left':(-12,0),'af_right':(12,0),'af_up':(0,-12),'af_down':(0,12)}[key]
        focus['center'][0]+=dx;focus['center'][1]+=dy
    packet,rect,center,size = geometry(camera,packet,focus['mode'],focus['center'])
    # Packed zero is a native no-op; nonzero RGB with alpha zero selects SRC clear.
    commands = borders(camera.focus_rect,0xffffff00) if camera.focus_rect else []
    if focus['enabled']:
        commands += borders(rect,COLORS[focus['status']])
    if commands:
        packet,fn = backend(camera,packet)
        data = b''.join(struct.pack('<5I',*r) for r in commands)+bytes(8)
        progress = len(commands)*20
        for attempt in range(12):
            packet,r = invoke(camera,packet,'原厂 GPU AF 诊断框',fn,data,
                              [('scratch',0),len(commands),0,('scratch',progress)])
            rc = int(r['return_r0'],16)
            if rc==0:
                submitted,pending = struct.unpack_from('<2I',bytes.fromhex(r['output']),progress)
                if submitted!=len(commands) or pending:
                    raise RuntimeError('AF GPU batch did not finish')
                break
            if rc!=1:
                raise RuntimeError('AF GPU source target differs from checked viewport')
            packet,_ = invoke(camera,packet,'等待 AF GPU',0x10170cca,bytes(8),[10])
        else:
            raise RuntimeError('AF GPU remained busy')
        packet,_ = invoke(camera,packet,'等待 AF LCD 提交',0x10170cca,bytes(8),[100])
    camera.focus_rect = rect if focus['enabled'] else None
    focus.update(center=list(center),size=list(size),rect=list(rect),
                 simulated=True,scope='original geometry and GPU diagnostic; not AF engine',
                 input_enabled=focus['enabled'])
    camera.focus_state = focus
    camera.update(focus=dict(focus))
    camera.audit({'kind':'af-display-state','key':key,**focus})
    return packet
