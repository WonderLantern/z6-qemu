# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only capture diagnostics for the Z6 C3.80 guest.

An AutoOperation reply acknowledges an action, including failed capture starts.
Only observed sensor transfers and processed frames can establish live view.
"""
import struct


def capture_state(remote):
    pointer = int.from_bytes(remote.memory(0xc181987c, 4), 'little')
    return {'mode': remote.memory(0xc1819880, 1)[0], 'pointer': hex(pointer),
            'stage': int.from_bytes(remote.memory(pointer+0xe0, 4), 'little'),
            'ready': int.from_bytes(remote.memory(0xc1819a40, 4), 'little')}


def action_completed(result):
    return (result['return_r0'] == '0x00000001' and
            bytes.fromhex(result['output'])[16:20] == bytes(4))


def capture_health(remote, image_evidence=None):
    # Z6 101df672 accumulates flags at +14, active error at +18.
    flags, active = struct.unpack('<2I', remote.memory(0xc18b7240, 8))
    inhibits = int.from_bytes(remote.memory(0xc2376d60, 16), 'little')
    parameter_init = int.from_bytes(remote.memory(0xc18b6230, 4), 'little')
    pointer = int.from_bytes(remote.memory(0xc18fa968, 4), 'little')
    version = None
    raw = None
    if pointer:
        raw = remote.memory(pointer+0xbe014, 2)
        version = (raw[0] << 4) | (raw[1] >> 4)  # Z6 10122454.
    return {'observation': 'paused guest snapshot; not a continuous sensor monitor',
            'application': capture_state(remote),
            'prepro_wait_input': hex(int.from_bytes(remote.memory(0xc25ed3b8, 4), 'little')),
            'error_flags': hex(flags), 'error_active': active,
            'capture_failed': bool(flags and active),
            'active_inhibit_ids': [hex(bit) for bit in range(97) if inhibits & (1 << bit)],
            'parameter_initialization_pending_mask': hex(parameter_init),
            'parameter_refresh_enabled': parameter_init == 0,
            'sensor_resource': {'bank': '0x38', 'pointer': hex(pointer),
                                'source_flash': '0x13e80000',
                                'version_bytes': raw.hex() if raw else None,
                                'version': hex(version) if version is not None else None,
                                'expected_version': '0x37',
                                'version_valid': version == 0x37},
            'cmos_input_connected': bool(image_evidence and image_evidence.get('raw_batches', 0)),
            'cmos_frames_injected': (image_evidence or {}).get('raw_batches', 0)*4,
            'live_view_verified': None if image_evidence else False,
            'processed_source_scanout_observed': bool(image_evidence and image_evidence.get('processed_buffer_scanned')),
            'image_evidence_scope': 'experimental device log; visual QA recorded separately' if image_evidence else 'legacy profile; native0 device logs not sampled here'}
