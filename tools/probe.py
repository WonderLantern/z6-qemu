# SPDX-License-Identifier: GPL-2.0-or-later
"""Boot/graphics diagnostics; optional HLE fixtures modify guest state, never code."""
from pathlib import Path
import argparse, hashlib, json, os, socket, struct, subprocess, sys, time

from rsp import Remote
TRACE_CALL = []
TRACE_REPEAT = set()
TRACE_WATCH = []
ACTIVE_FIXTURE = None


def call_fixture(remote, packet, function, payload, arguments, services=None, thumb=True, observers=None):
    """Call guest code in a paused task; track scheduler migration on return.

    Arguments can be integers or ('scratch', offset). No code bytes are patched.
    This is diagnostic HLE and must never be counted as passive observation.
    """
    services = services or {}
    observers = observers or {}
    if set(services) & (set(TRACE_CALL) | set(observers)):
        raise ValueError('Service interception overlaps observation breakpoint')
    global ACTIVE_FIXTURE
    ACTIVE_FIXTURE = {'function': hex(function), 'payload': payload.hex(),
                      'instruction_set': 'Thumb' if thumb else 'ARM',
                      'arguments': [hex(v) if isinstance(v, int) else {'scratch_offset': v[1]} for v in arguments],
                      'completed': False, 'register_context_restored': False}
    thread = packet.split('thread:')[1].split(';')[0]
    remote.command('Hg' + thread)
    saved = remote.command('g')
    regs_bytes = bytearray.fromhex(saved)
    if len(regs_bytes) != 68:
        raise ValueError('Diagnostic calls require negotiated 68-byte ARM registers')
    scratch = (struct.unpack_from('<I', regs_bytes, 52)[0] - len(payload) - 7) & ~7
    original_scratch = remote.memory(scratch, len(payload))
    assert remote.command(f'M{scratch:x},{len(payload):x}:' + payload.hex()) == 'OK'
    registers = [(i, scratch + v[1] if isinstance(v, tuple) else v)
                 for i, v in enumerate(arguments)]
    registers += [(13, scratch), (14, 0x100202b4), (15, function & ~1)]
    for reg, value in registers:
        struct.pack_into('<I', regs_bytes, 4 * reg, value)
    cpsr = struct.unpack_from('<I', regs_bytes, 64)[0]
    struct.pack_into('<I', regs_bytes, 64, (cpsr | 0x20) if thumb else (cpsr & ~0x20))
    assert remote.command('Z1,100202b4,4') == 'OK'
    assert remote.command('G' + regs_bytes.hex()) == 'OK'
    for pc in services:
        assert remote.command(f'Z1,{pc:x},2') == 'OK'
    pending = set(TRACE_CALL) | set(observers)
    watches = set(TRACE_WATCH)
    for address, length in watches:
        assert remote.command(f'Z2,{address:x},{length:x}') == 'OK'
    for pc in pending:
        assert remote.command(f'Z1,{pc:x},2') == 'OK'
    trace = []
    ACTIVE_FIXTURE['trace'] = trace
    ACTIVE_FIXTURE['scratch'] = hex(scratch)
    while True:
        remote.send('c'); returned = remote.receive()
        if 'thread:' not in returned:
            raise RuntimeError('Guest exited or stopped during diagnostic call: '+returned)
        return_thread = returned.split('thread:')[1].split(';')[0]
        remote.command('Hg' + return_thread)
        after = remote.registers()
        pc = int(after['r15'], 16)
        if pc in services:
            # Explicit diagnostic HLE. The service owns its return registers;
            # the outer fixture still restores the original task context.
            services[pc](remote, after)
            continue
        watched = next(((a, n) for a, n in watches if f'watch:{a:x};' in returned), None)
        if pc not in pending and watched is None:
            break
        if pc in observers:
            observers[pc](remote, after)
        event = {'registers': after, 'memory': {}}
        if watched:
            event['watch'] = {'address': hex(watched[0]), 'bytes': watched[1],
                              'value': remote.memory(*watched).hex()}
        for register in ['r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'r13']:
            pointer = int(after[register], 16)
            if (0xa1800000 <= pointer <= 0xac400000 - 128 or 0xc0000000 <= pointer <= 0xffffffff - 128):
                event['memory'][register] = remote.memory(pointer, 128).hex()
        trace.append(event)
        if watched:
            address, length = watched
            remote.command(f'z2,{address:x},{length:x}'); watches.remove(watched)
            if len(trace) < 64:
                assert remote.command('Hc'+return_thread) == 'OK'
                remote.send('s'); step = remote.receive()
                assert step.startswith('T05'), step
                assert remote.command('Hc-1') == 'OK'
                assert remote.command(f'Z2,{address:x},{length:x}') == 'OK'
                watches.add(watched)
            continue
        remote.command(f'z1,{pc:x},2'); pending.remove(pc)
        if pc in TRACE_REPEAT and len(trace) < 256:
            # RSP continue does not step over hardware breakpoints. Step the
            # stopped CPU once, then resume normal SMP execution with the
            # observation point reinstalled. No guest instructions are changed.
            assert remote.command('Hc'+return_thread) == 'OK'
            remote.send('s')
            step = remote.receive()
            assert step.startswith('T05'), step
            assert remote.command('Hc-1') == 'OK'
            assert remote.command(f'Z1,{pc:x},2') == 'OK'
            pending.add(pc)
    for pc in pending:
        remote.command(f'z1,{pc:x},2')
    for pc in services:
        remote.command(f'z1,{pc:x},2')
    for address, length in watches:
        remote.command(f'z2,{address:x},{length:x}')
    assert int(after['r15'], 16) == 0x100202b4, after
    remote.command('z1,100202b4,4')
    output = remote.memory(scratch, len(payload))
    assert remote.command(f'M{scratch:x},{len(payload):x}:' + original_scratch.hex()) == 'OK'
    assert remote.command('G' + saved) == 'OK'
    ACTIVE_FIXTURE = None
    return {'function': hex(function), 'instruction_set': 'Thumb' if thumb else 'ARM',
            'payload': payload.hex(), 'output': output.hex(),
            'arguments': [hex(v) if isinstance(v, int) else {'scratch_offset': v[1]} for v in arguments],
            'return_r0': after['r0'], 'call_cpu': thread, 'return_cpu': return_thread,
            'trace': trace,
            'kind': 'synthetic diagnostic input; not a controller protocol model'}
