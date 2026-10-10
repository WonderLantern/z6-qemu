# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded execution of the original Z6 companion-MCU shoulder compositor.

This is a native function harness, not a complete MCU/RTOS or OLED bus model.
Firmware assets remain local and are never embedded in source distributions.
"""
from pathlib import Path
import hashlib
import struct

FLASH = 0x08000000
FB = 0x20018310
STATE = 0x20030000
STOP = 0x2003EFF0


class ShoulderDisplay:
    def __init__(self, firmware, initialized_data=None):
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS
        from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR
        self.image = Path(firmware).read_bytes()
        if len(self.image) < 0x50000:
            raise ValueError('Invalid companion MCU image length')
        if hashlib.sha256(self.image).hexdigest() != '72f1fb29e24b36b872eec697a486abeff8bcef77f6020fa89473fd014aa18131':
            raise ValueError('Companion firmware identity is not the verified Z6 image')
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.mem_map(FLASH, 0x100000)
        self.uc.mem_write(FLASH, self.image[:0x80000])
        self.uc.mem_map(0x20000000, 0x40000)
        self.uc.mem_write(0x2003C000, self.image[0x1000:0x362c])
        self.uc.mem_write(0x2003F000, self.image[0x48e08:0x49658])
        self.uc.reg_write(UC_ARM_REG_SP, 0x2003B000)
        self.uc.reg_write(UC_ARM_REG_LR, STOP | 1)
        self.calls = 0
        # Execute the original scatter-table decompressor, using its declared
        # output length. No pre-extracted SRAM asset is needed by the runtime.
        self.call(0x08003838, 0x08048098, 0x2000D000, 0x1E58)
        self.data = bytes(self.uc.mem_read(0x2000D000, 0x1E58))
        if hashlib.sha256(self.data).hexdigest() != 'fe7d40059005cb3417005b9664267358ac255bee650e34558833a8a7f9824d73':
            raise ValueError('Native initialized companion data identity mismatch')
        if initialized_data is not None and Path(initialized_data).read_bytes() != self.data:
            raise ValueError('Supplied initialized data differs from native decompression')
        from unicorn import UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_PC
        def event_boundary(uc, address, size, user):
            # Native event delivery is outside this isolated function harness.
            # Data ingress and publication execute; RTOS scheduling is explicit.
            if address == 0x0802155A:
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        self.uc.hook_add(UC_HOOK_CODE, event_boundary, begin=0x0802155A, end=0x0802155A)

    def call(self, address, *args):
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            self.uc.reg_write(reg, value)
        self.uc.reg_write(UC_ARM_REG_SP, 0x2003B000)
        self.uc.reg_write(UC_ARM_REG_LR, STOP | 1)
        self.uc.emu_start(address | 1, STOP, count=2000000)
        if self.uc.reg_read(UC_ARM_REG_PC) != STOP:
            raise RuntimeError('Companion compositor exceeded instruction budget')
        self.calls += 1
        return self.uc.reg_read(UC_ARM_REG_R0)

    def compose(self, state):
        if len(state) != 0x72:
            raise ValueError('Native shoulder state must be exactly 0x72 bytes')
        self.uc.mem_write(STATE, bytes(state))
        self.call(0x08027E88, FB, STATE)
        return bytes(self.uc.mem_read(FB, 0x600))

    def receive(self, payload):
        if len(payload) != 0x70 or payload[0] != 4:
            raise ValueError('Expected native channel8 tag4 112-byte display snapshot')
        request, source = 0x20031000, 0x20031100
        self.uc.mem_write(source, bytes(payload))
        self.uc.mem_write(request, struct.pack('<HHI', len(payload), 0, source))
        self.call(0x080274BC, request)
        self.call(0x08029854, 0x20013A86)
        state = bytes(self.uc.mem_read(0x2001822C, 0x72))
        if state != bytes(payload) + struct.pack('<H', len(payload)):
            raise RuntimeError('Native shoulder ingress/publication did not preserve snapshot')
        return self.compose(state)

    def evidence(self):
        return dict(renderer='original-ex1620-08027e88', width=128, height=96,
                    format='1bpp-row-major-msb-first', native_calls=self.calls,
                    companion_sha256=hashlib.sha256(self.image).hexdigest(),
                    initialized_data_sha256=hashlib.sha256(self.data).hexdigest(),
                    full_mcu_emulated=False)


def rgb(frame):
    if len(frame) != 0x600:
        raise ValueError('Expected a 1536-byte shoulder framebuffer')
    out = bytearray()
    for value in frame:
        for bit in range(7, -1, -1):
            out.extend(bytes((220, 230, 225) if value & (1 << bit) else (12, 18, 16)))
    return bytes(out)
