# SPDX-License-Identifier: GPL-2.0-or-later
"""Local interactive Z6 GUI. Original firmware keys through diagnostic GDB calls.

Runs under WSL with standard Python only. The browser sees live QMP screenshots.
Only the worker owns QMP/RSP; HTTP requests enqueue bounded, named operations.
"""
from pathlib import Path
import argparse
import hashlib
import http.server
import json
import os
import queue
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import tempfile
import traceback
import time
import zlib

import probe
import focus_display
from probe import call_fixture, Remote
from capture_diagnostics import action_completed, capture_health, capture_state

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
BUILD_MANIFEST = PROJECT / '.local/build-manifest.json'
FIRMWARE = None
OFFICIAL_FIRMWARE_SHA256 = '1e6348d58750e67372d0a8e363932c57ee9c04d0eb8f62803bcd19812df0d25c'


def checked_firmware(path, allow_modified=False, expected_sha256=None):
    data = path.read_bytes()
    if len(data) != 33502842:
        raise ValueError('Requires the extracted Z6 C 3.80 MAIN, not the upgrade package')
    digest = hashlib.sha256(data).hexdigest()
    if not allow_modified and digest != OFFICIAL_FIRMWARE_SHA256:
        raise ValueError('Modified MAIN requires --allow-modified-firmware')
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Firmware payload hash changed after selection')
    return digest


from raw_input import RawSequence
from cmos_config import active_manifest, active_ingress
SYSTEM_REPORT = bytes.fromhex('000100000200000000000000000000000000000002000000000000000000000000000000')
# Z6 ROM10637f04, 16-byte AO entries; MENU index67 independently checked
# against ID_SW1_MENU at file0061f28c (40-byte record, bank1 mask8000).
KEYS = {'half': 7, 'right': 34, 'left': 35, 'up': 36, 'down': 37,
        'menu': 67, 'play': 68, 'delete': 69, 'i': 72, 'ok': 74}
DIALS = {'main_cw': (0x10, 1), 'main_ccw': (0x10, -1),
         'sub_cw': (0x14, 1), 'sub_ccw': (0x14, -1)}
# Physical selector DSID0; runtime readback matches 136F: P/A/S/M=0/1/2/3.
MODES = {'mode_p': 0, 'mode_s': 2, 'mode_a': 1, 'mode_m': 3}
LABELS = {**{k:k for k in focus_display.KEYS}, 'half': '返回取景', 'right': '右', 'left': '左 / 返回', 'up': '上', 'down': '下',
          'menu': 'MENU', 'play': '回放', 'delete': '删除', 'i': 'i', 'ok': 'OK',
          'main_cw': '主拨轮顺时针', 'main_ccw': '主拨轮逆时针',
          'sub_cw': '副拨轮顺时针', 'sub_ccw': '副拨轮逆时针',
          'counter_probe': '计时自检', 'capture': '拍照', 'mode_p': 'P档', 'mode_s': 'S档', 'mode_a': 'A档', 'mode_m': 'M档'}


def ppm_pixels(data):
    # QEMU's screendump P6 header, followed by packed RGB bytes.
    magic, dimensions, maximum, pixels = data.split(b'\n', 3)
    w, h = map(int, dimensions.split())
    if magic != b'P6' or maximum != b'255' or (w, h) not in ((720, 480), (1024, 682), (1024, 680)) or len(pixels) != w*h*3:
        raise ValueError('Unexpected QEMU screenshot format')
    return w, h, pixels


def rgb_png(w, h, pixels):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload))+kind+payload+struct.pack('>I', zlib.crc32(kind+payload))
    rows = b''.join(b'\0'+pixels[y*w*3:(y+1)*w*3] for y in range(h))
    png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    return png+chunk(b'IDAT', zlib.compress(rows, 1))+chunk(b'IEND', b'')


def ppm_png(data):
    w, h, pixels = ppm_pixels(data)
    return rgb_png(w, h, pixels), pixels


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class QMP:
    def __init__(self, port):
        self.socket = socket.create_connection(('127.0.0.1', port), 5)
        self.file = self.socket.makefile('rwb', buffering=0)
        json.loads(self.file.readline())
        self.command('qmp_capabilities')

    def command(self, name, arguments=None):
        request = {'execute': name}
        if arguments is not None:
            request['arguments'] = arguments
        self.file.write(json.dumps(request).encode()+b'\n')
        while True:
            raw = self.file.readline()
            if not raw:
                raise EOFError('QEMU monitor disconnected')
            reply = json.loads(raw)
            if 'error' in reply:
                raise RuntimeError(reply['error'])
            if 'return' in reply:
                return reply['return']

    def close(self):
        self.file.close()
        self.socket.close()


class Camera:
    def __init__(self, port, profile='menu', capture_trace=False, tg_test_pulse=False,
                 exmcu_test_device=False, capture_control_test=False, raw_source=None,
                 exmcu_no_lens=False, orientation_fixture=None, keep_awake=False,
                 tg_periodic_test=False, raw_ingress_test=None, tg_paired_test=False, isp_boundary_test=False,
                 photo_liveview=False, one_insn_per_tb=False,
                 allow_modified_firmware=False, firmware_sha256=None, exposure_probe=False, companion_firmware=None):
        # Fail before launching QEMU if any selected input is malformed.
        self.raw_source = RawSequence(raw_source) if raw_source else None
        self.port = port
        self.exposure_probe = exposure_probe
        self.allow_modified_firmware = allow_modified_firmware
        self.firmware_sha256 = firmware_sha256 or OFFICIAL_FIRMWARE_SHA256
        self.session_grid_setting = None
        self.session_exposure_mode = 3
        self.photo_liveview = photo_liveview
        self.one_insn_per_tb = one_insn_per_tb
        self.device_log_position = 0
        self.device_log_tail = ''
        self.device_evidence = {}
        self.preview_buffers = set()
        if photo_liveview:
            self.image_process_test = self.lcd_scanout_test = True
            self.icount_shift = 3
        self.profile = profile
        self.capture_trace = capture_trace
        self.capture_control_test = capture_control_test
        self.tg_test_pulse = tg_test_pulse or capture_control_test
        self.tg_periodic_test = tg_periodic_test
        self.tg_paired_test = tg_paired_test
        self.isp_boundary_test = isp_boundary_test
        self.raw_ingress_test = Path(raw_ingress_test).resolve(strict=True) if raw_ingress_test else None
        if self.raw_ingress_test and (not tg_periodic_test or self.raw_ingress_test.stat().st_size != 1909440):
            raise ValueError('RAW ingress experiment requires the timing test and a 1909440-byte stimulus')
        if isp_boundary_test and not self.raw_ingress_test:
            raise ValueError('ISP boundary experiment requires the RAW ingress test')
        self.exmcu_test_device = exmcu_test_device or capture_control_test or exmcu_no_lens
        self.exmcu_no_lens = exmcu_no_lens
        if orientation_fixture is not None and orientation_fixture not in range(4):
            raise ValueError('Orientation must be 0, 1, 2 or 3')
        self.orientation_fixture = orientation_fixture
        self.keep_awake = keep_awake
        self.focus_state = {'enabled':False,'mode':'S','status':'idle','center':[360,240],'simulated':True}
        self.focus_code = 0
        self.focus_rect = None
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.requests = queue.Queue(maxsize=16)
        self.state = {'phase': 'booting', 'message': '正在启动虚拟相机', 'busy': True,
                      'frame': 0, 'last_key': None, 'completed_action': 0, 'error': None,
                      'no_lens_simulation': self.exmcu_no_lens,
                      'orientation_fixture': self.orientation_fixture,
                      'keep_awake': self.keep_awake, 'idle_timeout_override': None}
        self.png = None
        self.shoulder_png = None
        self.shoulder_renderer = None
        self.shoulder_log_position = 0
        self.shoulder_log_tail = ''
        self.shoulder_packets = 0
        try:
            from shoulder_display import ShoulderDisplay
            if companion_firmware is None:
                raise ValueError('Shoulder display disabled; provide --companion-firmware')
            self.shoulder_renderer = ShoulderDisplay(companion_firmware)
            self.state['shoulder'] = dict(available=True, frame=0, packets=0,
                message='等待原厂肩屏数据', **self.shoulder_renderer.evidence())
        except (ImportError, OSError, ValueError) as exc:
            self.state['shoulder'] = dict(available=False, frame=0, message=str(exc))
        self.previous_pixels = None
        self.proc = self.remote = self.monitor = self.console = None
        self.running = False
        self.stamp = time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(2)
        self.directory = PROJECT/'.local/sessions'/self.stamp
        self.directory.mkdir(parents=True)
        self.audit_path = self.directory/'actions.jsonl'
        self.sequence = 0
        self.boot_count = 0
        self.refresh_samples = self.png_encodes = 0
        self.refresh_seconds = 0.0
        if self.raw_source:
            self.state['raw_input'] = self.raw_source.status()
            self.audit({'kind': 'raw_source_loaded', **self.raw_source.status()})

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self):
        with self.lock:
            return dict(self.state, queued=self.requests.qsize(), session=self.stamp)

    def audit(self, record):
        with self.audit_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(time=time.time(), **record), ensure_ascii=False)+'\n')

    def submit(self, action, key=None):
        if key in ('capture', 'counter_probe') and not self.exposure_probe:
            raise ValueError('Capture probe requires --exposure-probe')
        if action not in ('key', 'pause', 'resume', 'restart', 'stop', 'shooting', 'menu-profile') or (action == 'key' and key not in {*KEYS, *DIALS, *MODES, *focus_display.KEYS, 'capture', 'counter_probe'}):
            raise ValueError('未知按键或操作')
        with self.lock:
            if self.state['phase'] == 'booting':
                raise RuntimeError('相机正在启动，请稍候')
            if action == 'key' and self.state['phase'] != 'running':
                raise RuntimeError('请先恢复运行')
            self.sequence += 1
            item = {'id': self.sequence, 'action': action, 'key': key}
            self.requests.put_nowait(item)
        return item

    def receive_stop(self):
        packet = self.remote.receive()
        if 'thread:' not in packet:
            raise RuntimeError('Guest stopped unexpectedly: '+packet)
        self.remote.command('Hg'+packet.split('thread:')[1].split(';')[0])
        self.running = False
        return packet

    def continue_guest(self):
        """Wait for RSP continue to reach QEMU before querying it as running.

        RSP and QMP use different sockets; an immediate query can still return
        debug (observed 1.5ms after MENU returned). Never issue a second
        continue to conceal an unexpected stop.
        """
        self.remote.send('c')
        until = time.monotonic() + 1
        while True:
            status = self.monitor.command('query-status')
            if status['running']:
                self.running = True
                return
            if time.monotonic() >= until:
                raise RuntimeError('QEMU did not acknowledge continue: ' + status['status'])
            time.sleep(.01)

    def run_to(self, address):
        assert not self.running
        assert self.remote.command(f'Z1,{address:x},2') == 'OK'
        self.remote.send('c'); self.running = True
        packet = self.receive_stop()
        regs = self.remote.registers()
        if int(regs['r15'], 16) != address:
            raise RuntimeError(f'Unexpected stop at {regs["r15"]}; expected {address:#x}')
        assert self.remote.command(f'z1,{address:x},2') == 'OK'
        return packet

    def call(self, packet, name, function, payload, arguments):
        self.update(message=name)
        result = call_fixture(self.remote, packet, function, payload, arguments)
        self.audit({'kind': 'original_firmware_call', 'name': name, 'result': result})
        return 'T05thread:'+result['return_cpu']+';'

    def exposure_observation(self, packet):
        result = {}
        for name, dsid in [('mode', 0x136f), ('physical_mode', 0), ('mode_asset', 2), ('photo_mode', 0x200), ('tv_display_index', 0x1500), ('capture_kind', 0x1319), ('tv', 0x204), ('tv_secondary', 0x20b)]:
            value = call_fixture(self.remote, packet, 0x1015bebe, bytes(8), [dsid])
            packet = 'T05thread:'+value['return_cpu']+';'
            number = int(value['return_r0'], 16)
            result[name] = number if number < 0x80000000 else number-0x100000000
        value = call_fixture(self.remote, packet, 0x103d42fe, bytes(8),
                             [0x1308, ('scratch', 0), 8])
        packet = 'T05thread:'+value['return_cpu']+';'
        result['display_tuple'] = list(struct.unpack('<ii', bytes.fromhex(value['output'])))
        return packet, result

    def dial_or_mode(self, packet, name):
        packet, before = self.exposure_observation(packet)
        if name in DIALS:
            # Same physical-input boundary as the original AO key injector.
            snapshot = call_fixture(self.remote, packet, 0x101b640c,
                                    bytes(48), [('scratch', 0)])
            packet = 'T05thread:'+snapshot['return_cpu']+';'
            report = bytearray.fromhex(snapshot['output'])
            for offset in (0x10, 0x14, 0x18, 0x1c):
                struct.pack_into('<i', report, offset, 0)
            offset, delta = DIALS[name]
            struct.pack_into('<i', report, offset, delta)
            packet = self.call(packet, LABELS[name], 0x101b63e6,
                               report, [('scratch', 0)])
        else:
            packet = self.call(packet, LABELS[name], 0x101d7f02, bytes(8),
                               [0, MODES[name]])
        packet = self.call(packet, '等待拨轮处理', 0x10170cca, bytes(8), [300])
        packet, after = self.exposure_observation(packet)
        self.audit({'kind': 'native-dial-input' if name in DIALS else 'native-mode-input',
                    'input': name, 'before': before, 'after': after,
                    'firmware_code_modified': False})
        if name in MODES:
            if after['physical_mode'] != MODES[name] or after['mode'] != MODES[name]:
                raise RuntimeError('Native exposure mode did not select '+LABELS[name])
            self.session_exposure_mode = MODES[name]
        self.update(exposure=after)
        return packet

    def counter_driver_probe(self, packet, time_pair=(192, -960), expected_ns=32000000000):
        """Original converter/driver experiment, separate from still exposure.

        It uses an idle counter with masked IRQ, then stops and restores it.
        Deadline expiration is tested separately with QTest virtual time.
        """
        converted = call_fixture(self.remote, packet, 0x1011c14a,
                                 struct.pack('<ii', *time_pair), [('scratch', 0)])
        packet = 'T05thread:'+converted['return_cpu']+';'
        ns = int(converted['return_r0'], 16) | (int(converted['return_r1'], 16) << 32)
        if ns != expected_ns:
            raise RuntimeError(f'Converter returned {ns}ns, expected {expected_ns}ns')
        # +21 is a declared zero-calibration fixture, NOT decoded sensor timing.
        ticks = ns // 1000 + 21
        enable = int.from_bytes(self.remote.memory(0x2c011000, 4), 'little')
        irq_mask = int.from_bytes(self.remote.memory(0x2c01100c, 4), 'little')
        selected = None
        candidates = []
        for ch in range(11, -1, -1):
            if enable & (1 << ch):
                continue
            obj = 0xc1806390 + 0x14 * ch
            data = self.remote.memory(obj, 20)
            table = struct.unpack_from('<I', data, 8)[0]
            candidates.append({'channel': ch, 'object': data.hex(), 'table': hex(table)})
            if data[4] != ch or not (0xa1800000 <= table < 0xa4000000 or 0xc1800000 <= table < 0xc4000000):
                continue
            base = 0x2c011100 + ch * 0x100
            pointers = struct.unpack('<23I', self.remote.memory(table, 92))
            if pointers[8] != base+8:
                continue
            pending = int.from_bytes(self.remote.memory(0x2c010110+ch*0x100, 4), 'little')
            if pending:
                continue
            selected = (ch, obj, base, data)
            break
        if selected is None:
            self.audit({'kind': 'counter-driver-candidates', 'candidates': candidates})
            raise RuntimeError('No initialized idle counter available for driver probe')
        ch, obj, base, data = selected
        saved_clock, saved_terminal, saved_count = struct.unpack('<3I', self.remote.memory(base+4, 12))
        callback = struct.unpack_from('<I', data, 16)[0]
        saved_cfg = struct.pack('<5I', saved_count, saved_terminal, saved_clock, 1, 1)
        cfg = struct.pack('<5I', (-ticks) & 0xffffffff, 0xffffffff, 0x31, 1, 1)
        record = {'scope': 'firmware converter and original counter driver fixture',
                  'time_pair': list(time_pair), 'expected_ns': expected_ns,
                  'converter_ns': ns, 'calibration_fixture': 0, 'compensation_us_fixture': 21,
                  'ticks': ticks, 'tick_ns_hypothesis': 1000, 'channel': ch,
                  'object': hex(obj), 'config': cfg.hex(),
                  'sensor_integration_verified': False, 'firmware_capture_verified': False}
        armed = False
        try:
            packet = self.call(packet, '屏蔽自检通道中断', 0x1005b354, bytes(8), [obj])
            packet = self.call(packet, '提交原厂计数器配置', 0x1005b3ba, cfg,
                               [obj, ('scratch', 0), 0])
            armed = True
            packet = self.call(packet, '启动原厂计数器', 0x1005b376, bytes(8), [obj])
            armed = True
            active = int.from_bytes(self.remote.memory(0x2c011000, 4), 'little')
            registers = struct.unpack('<3I', self.remote.memory(base+4, 12))
            record.update(enabled=bool(active & (1 << ch)), clock=registers[0],
                          terminal=registers[1], observed_count=registers[2])
            if not record['enabled'] or record['clock'] != 0x31 or record['terminal'] != 0xffffffff:
                raise RuntimeError('Original counter driver did not program expected registers')
        finally:
            if armed:
                packet = self.call(packet, '停止自检计数器', 0x1005b398, bytes(8), [obj])
            packet = self.call(packet, '还原自检通道配置', 0x1005b3ba, saved_cfg,
                               [obj, ('scratch', 0), callback])
            packet = self.call(packet, '还原自检中断屏蔽',
                               0x1005b354 if irq_mask & (1 << ch) else 0x1005b332,
                               bytes(8), [obj])
        restored_enable = int.from_bytes(self.remote.memory(0x2c011000, 4), 'little')
        record['restored_inactive'] = not bool(restored_enable & (1 << ch))
        if not record['restored_inactive']:
            raise RuntimeError('Counter probe left a running channel')
        self.audit({'kind': 'native-counter-driver-probe', **record})
        self.update(counter_probe=record)
        return packet

    def capture_probe(self, packet):
        """Physical release switches; observation only, never a completion fixture."""
        packet, exposure_before = self.exposure_observation(packet)
        health_before = capture_health(self.remote, self.device_evidence or None)
        snapshot = call_fixture(self.remote, packet, 0x101b640c,
                                bytes(48), [('scratch', 0)])
        packet = 'T05thread:'+snapshot['return_cpu']+';'
        original = bytearray.fromhex(snapshot['output'])
        for offset in (0x10, 0x14, 0x18, 0x1c):
            struct.pack_into('<i', original, offset, 0)
        initial = struct.unpack_from('<I', original)[0]
        if initial & 0xc0000000:
            raise RuntimeError('Release switches already pressed; refuse probe')
        events = []
        # Bounded original entry observations; no service-return interception.
        probe_points = [0x103265ac, 0x103265b2, 0x103265c8, 0x103265cc, 0x10326632, 0x103266aa, 0x1030fdaa, 0x1030fdde, 0x103264f2, 0x10326532, 0x1032653a, 0x1032654c, 0x10326568, 0x103265a8, 0x103265b8, 0x1033965c, 0x1030f60e, 0x10378a40, 0x1033938a, 0x103393b4, 0x103393dc, 0x10339da0, 0x10339484, 0x10334fdc, 0x10335028, 0x1033423a, 0x103343e2, 0x103345f6, 0x103346da, 0x10335d2a, 0x10334196, 0x10334bf8, 0x10334c14, 0x10335e04, 0x103687a0, 0x1008fe80, 0x1008fca2, 0x1015bcd2, 0x1020d98c, 0x1005d42e, 0x101b6394, 0x10061672, 0x100621c0, 0x10061810, 0x1006157e, 0x1016585e, 0x1011c14a, 0x100cda34,
                        0x1005b3ba, 0x1005b376]
        dispatch_callback = int(health_before['gui_action_dispatch']['callback'], 16)
        if 0x10020000 <= (dispatch_callback & ~1) < 0x12020000:
            probe_points.append(dispatch_callback & ~1)
        client = int(health_before['application']['pointer'], 16)
        callback = int.from_bytes(self.remote.memory(client+8, 4), 'little')
        if 0x10020000 <= (callback & ~1) < 0x12020000:
            probe_points.append(callback & ~1)
        previous_trace = list(probe.TRACE_CALL)
        probe.TRACE_CALL.extend(point for point in probe_points if point not in probe.TRACE_CALL)
        try:
            for label, mask, settle in [
                ('半按快门', 0x80000000, 100),
                ('全按快门', 0xc0000000, 100),
                ('释放全按', 0x80000000, 100),
                ('释放半按', 0, 500),
            ]:
                report = bytearray(original)
                struct.pack_into('<I', report, 0, initial | mask)
                packet = self.call(packet, label, 0x101b63e6, report, [('scratch', 0)])
                packet = self.call(packet, '等待快门输入处理', 0x10170cca, bytes(8), [settle])
                events.append({'switch_mask': hex(mask),
                               'live_report': self.remote.memory(0xc1f90df8, 48).hex(),
                               'sampled_report': self.remote.memory(0xc1f90ca8, 0x64).hex(),
                               'capture': capture_health(self.remote, self.device_evidence or None)})
        finally:
            probe.TRACE_CALL[:] = previous_trace
        packet, exposure_after = self.exposure_observation(packet)
        result = {'before': health_before, 'exposure_before': exposure_before,
                  'events': events, 'after': events[-1]['capture'],
                  'exposure_after': exposure_after,
                  'physical_input_submitted': True, 'exposure_completed': None,
                  'timing_verified': False, 'firmware_code_modified': False}
        self.audit({'kind': 'physical-capture-probe', **result})
        self.update(capture_probe=result)
        return packet

    def key(self, packet, name):
        if name in focus_display.KEYS:
            return focus_display.apply(self,packet,name)
        if name == 'counter_probe':
            return self.counter_driver_probe(packet)
        if name == 'capture':
            return self.capture_probe(packet)
        if name in DIALS or name in MODES:
            return self.dial_or_mode(packet, name)
        before = {'live': self.remote.memory(0xc1f90dfc, 4).hex(),
                  'sampled': self.remote.memory(0xc1f90cc0, 4).hex()}
        if name == 'half':
            # Research-only API, deliberately absent from the public UI:
            # warm Start has not restored continuous liveview yet.
            # AO index7 is disabled (entry first word0). Submit the verified
            # SW0_RELEASE_HALF bit through the same original48B input setter.
            original = self.remote.memory(0xc1f90df8, 48)
            pressed = bytearray(original)
            struct.pack_into('<I', pressed, 0, struct.unpack_from('<I', pressed)[0] | 0x80000000)
            packet = self.call(packet, '半按快门', 0x101b63e6, bytes(pressed), [('scratch', 0)])
            packet = self.call(packet, '等待半按事件', 0x10170cca, bytes(8), [100])
            packet = self.call(packet, '释放半按快门', 0x101b63e6, original, [('scratch', 0)])
            if self.photo_liveview:
                self.update(message='正在返回取景')
                ended = call_fixture(self.remote, packet, 0x10525ae2, bytes(32),
                                     [('scratch', 0), 0, ('scratch', 16)])
                self.audit({'kind': 'assisted-end-liveview', 'result': ended,
                            'guest_restarted': False})
                packet = 'T05thread:'+ended['return_cpu']+';'
                if action_completed(ended):
                    pointer = int.from_bytes(self.remote.memory(0xc18fa968, 4), 'little')
                    version = self.remote.memory(pointer+0xbe014, 2) if pointer else None
                    self.audit({'kind': 'sensor-after-end', 'pointer': hex(pointer),
                                'version': version.hex() if version else None,
                                'capture': capture_health(self.remote, self.device_evidence)})
                    if pointer and version != bytes.fromhex('0370'):
                        assert self.remote.command(f'M{pointer+0xbe014:x},2:0370') == 'OK'
                        self.audit({'kind': 'sensor-version-fixture-reloaded',
                                    'before': version.hex(), 'diagnostic_only': True})
                    packet = self.call(packet, '返回拍摄模式', 0x1005d4c0, bytes(8),
                                       [0xc1819748, 0x05040016, 2])
                    packet = self.call(packet, '恢复拍摄参数', 0x1015beb2, bytes(8), [0x180c, 1])
                    packet = self.call(packet, '等待拍摄模式', 0x10170cca, bytes(8), [1000])
                    self.audit({'kind': 'return-liveview-application-ready',
                                'capture': capture_health(self.remote, self.device_evidence)})
                    self.audit({'kind': 'return-liveview-controller',
                                'state': self.remote.memory(0xc18b84e0, 48).hex()})
                    if os.environ.get('Z6_TRACE_RETURN_ERRORS'):
                        for address in (0x1005cbe8, 0x1005c59e, 0x1005c5a0):
                            if address not in probe.TRACE_CALL:
                                probe.TRACE_CALL.append(address)
                            probe.TRACE_REPEAT.add(address)
                        callback = int.from_bytes(self.remote.memory(0xc18b8504, 4), 'little') & ~1
                        if callback and callback not in probe.TRACE_CALL:
                            probe.TRACE_CALL.append(callback)
                            probe.TRACE_REPEAT.add(callback)
                    result = call_fixture(self.remote, packet, 0x10525a70, bytes(32),
                                          [('scratch', 0), 0, ('scratch', 16)])
                    self.audit({'kind': 'assisted-return-liveview', 'result': result,
                                'guest_restarted': False})
                    packet = 'T05thread:'+result['return_cpu']+';'
            return packet
        values = [0]*8
        index = KEYS[name]
        values[index//32] = 1 << (index%32)
        values[4] = 10   # Original AO press duration: 10*10 virtual milliseconds.
        packet = self.call(packet, '按键：'+LABELS[name], 0x10526d92,
                           struct.pack('<8I', *values), [('scratch', 0), 5, ('scratch', 20)])
        self.audit({'kind': 'key-release-observation', 'key': name, 'before': before,
                    'after': {'live': self.remote.memory(0xc1f90dfc, 4).hex(),
                              'sampled': self.remote.memory(0xc1f90cc0, 4).hex()}})
        return packet

    def boot(self, enter_menu=True, announce_ready=True):
        if os.environ.get('WSL_DISTRO_NAME') == 'ubuntu-noble':
            raise RuntimeError('Use the explicitly selected Nikon distribution')
        self.frame_spool = Path(tempfile.gettempdir())/'nikon-z6'/self.stamp
        self.frame_spool.mkdir(parents=True, exist_ok=True)
        self.boot_started = time.perf_counter()
        if self.raw_source:
            self.raw_source = RawSequence(self.raw_source.path)
            self.update(raw_input=self.raw_source.status())
        self.boot_count += 1
        self.shoulder_log_position = 0
        self.shoulder_log_tail = ''
        self.shoulder_packets = 0
        with self.lock:
            self.shoulder_png = None
            self.state['shoulder'].update(frame=0, packets=0)
        self.device_log_position = 0
        self.device_log_tail = ''
        self.preview_buffers.clear()
        self.device_evidence = {'experimental': True, 'bit_accurate': False,
            'raw_width': 2034, 'raw_height': 1434, 'raw_stride': 4080,
            'raw_bits': 12, 'raw_cfa': 'RGGB',
            'raw_batches': 0, 'isp_batches': 0, 'lcd_frames_observed': 0,
            'processed_buffer_scanned': False} if self.photo_liveview else {}
        self.update(phase='booting', message='正在加载原固件', busy=True, error=None, frame=0,
                    capture=None, exposure_probe_enabled=self.exposure_probe, profile=self.profile, idle_timeout_override=None,
                    device_evidence=dict(self.device_evidence), frame_sha256=None)
        with self.lock:
            self.png = self.previous_pixels = None
        build = json.loads((BUILD_MANIFEST).read_text())
        if hashlib.sha256(Path(build['binary']).read_bytes()).hexdigest() != build['binary_sha256']:
            raise RuntimeError('QEMU binary changed; rebuild first')
        for name, sha in build['sources'].items():
            if hashlib.sha256((PROJECT/name).read_bytes()).hexdigest() != sha:
                raise RuntimeError('QEMU source changed; rebuild first')
        payload = FIRMWARE
        firmware_sha256 = checked_firmware(payload, self.allow_modified_firmware,
                                           self.firmware_sha256)
        port, qmp = free_port(), free_port()
        command = [build['binary'], '-M', 'nikon-z6-display', '-smp', '2', '-display', 'none',
                   '-serial', 'none', '-monitor', 'none', '-nic', 'none', '-bios', str(payload),
                   '-device', 'loader,addr=0x10020000,cpu-num=0',
                   '-device', 'loader,addr=0x10020000,cpu-num=1',
                   '-S', '-gdb', f'tcp:127.0.0.1:{port}',
                   '-qmp', f'tcp:127.0.0.1:{qmp},server=on,wait=off',
                   '-accel', 'tcg,one-insn-per-tb='+('on' if self.one_insn_per_tb else 'off'), '-icount',
                   f'shift={getattr(self, "icount_shift", 6)},align=off,sleep=off']
        self.audit({'kind': 'boot', 'command': command, 'build': build,
                    'firmware_sha256': firmware_sha256,
                    'firmware_modified': firmware_sha256 != OFFICIAL_FIRMWARE_SHA256, 'guest_state_modified': True, 'camera_access': False})
        self.live_log = self.frame_spool/f'qemu-{self.boot_count}.log'
        self.console = self.live_log.open('w')
        env = dict(os.environ, Z6_MMIO_QUIET='1')
        if self.exposure_probe:
            env['Z6_TRACE_EXPOSURE'] = '1'
        env.pop('Z6_IMAGE_CONFIG_RECORD', None)
        env.pop('Z6_IMAGE_PROCESS_TEST', None)
        env.pop('Z6_ISP_DISABLE_CACHE', None)
        env.pop('Z6_VERIFY_CPSR_HFLAGS', None)
        if getattr(self, 'verify_cpsr_hflags', False):
            env['Z6_VERIFY_CPSR_HFLAGS'] = '1'
        if getattr(self, 'isp_disable_cache', False):
            env['Z6_ISP_DISABLE_CACHE'] = '1'
        env.pop('Z6_LCD_SCANOUT_TEST', None)
        env['Z6_LCD_SCANOUT_TEST'] = '1'
        if getattr(self, 'lcd_scanout_test', False):
            env['Z6_LCD_SCANOUT_TEST'] = '1'
        if getattr(self, 'image_process_test', False):
            env['Z6_IMAGE_PROCESS_TEST'] = '1'
        if getattr(self, 'image_config_record', False) or getattr(self, 'image_process_test', False):
            env['Z6_IMAGE_CONFIG_RECORD'] = '1'
        env.pop('Z6_CAPTURE_TRACE', None)
        if self.capture_trace:
            env['Z6_CAPTURE_TRACE'] = '1'
        env.pop('Z6_TG_TEST_PULSE', None)
        if self.tg_test_pulse:
            env['Z6_TG_TEST_PULSE'] = '1'
            self.audit({'kind': 'tg-test-pulse', 'diagnostic_only': True, 'raw_frames': 0})
        env.pop('Z6_EXMCU_TEST_DEVICE', None)
        env.pop('Z6_TG_PERIODIC_TEST', None)
        env.pop('Z6_TG_PAIRED_TEST', None)
        env.pop('Z6_TG_PERIOD_NS', None)
        if getattr(self, 'tg_period_ms', None):
            env['Z6_TG_PERIOD_NS'] = str(self.tg_period_ms * 1000000)
        if self.tg_paired_test:
            env['Z6_TG_PAIRED_TEST'] = '1'
        env.pop('Z6_RAW_INGRESS_TEST', None)
        env.pop('Z6_RAW_NATIVE0_TEST', None)
        env.pop('Z6_ISP_BOUNDARY_TEST', None)
        if self.isp_boundary_test:
            env['Z6_ISP_BOUNDARY_TEST'] = '1'
        if self.raw_ingress_test:
            env['Z6_RAW_INGRESS_TEST'] = str(self.raw_ingress_test)
            env['Z6_RAW_NATIVE0_TEST'] = str(active_ingress('native0'))
        if self.tg_periodic_test:
            env['Z6_TG_PERIODIC_TEST'] = '1'
            self.audit({'kind': 'tg-periodic-test', 'diagnostic_only': True,
                        'paired_edges': self.tg_paired_test, 'raw_frames': 0})
        env.pop('Z6_EXMCU_NO_LENS', None)
        env.pop('Z6_EXMCU_CAPTURE_SYNC_TEST', None)
        if self.photo_liveview:
            env['Z6_EXMCU_CAPTURE_SYNC_TEST'] = '1'
            self.audit({'kind': 'exmcu-capture-sync-test', 'diagnostic_only': True,
                        'request_gpio': '0x65', 'completion_gpio': '0x54', 'irq': 65})
        if self.exmcu_no_lens:
            env['Z6_EXMCU_NO_LENS'] = '1'
            self.audit({'kind': 'exmcu-no-lens', 'diagnostic_only': True})
        if self.exmcu_test_device:
            env['Z6_EXMCU_TEST_DEVICE'] = '1'
            self.audit({'kind': 'exmcu-test-device', 'diagnostic_only': True, 'capture_control_only': True})
        env.pop('Z6_GRAPHICS_DUMP_DIR', None)
        env.pop('Z6_GPU_ICON_DUMP_DIR', None)
        if getattr(self, 'gpu_icon_dump', None):
            env['Z6_GPU_ICON_DUMP_DIR'] = str(self.gpu_icon_dump)
        self.proc = subprocess.Popen(command, stdout=self.console, stderr=subprocess.STDOUT, env=env)
        self.remote = Remote(port)
        self.remote.command('qSupported:multiprocess+;xmlRegisters=arm')
        self.remote.command('qXfer:features:read:target.xml:0,fff')
        self.remote.command('Hg0'); self.remote.command('?')
        self.remote.sock.settimeout(30)
        self.monitor = QMP(qmp)
        self.update(message='初始化图像内存')
        packet = self.run_to(0x103fc996)
        packet = self.call(packet, '初始化图像内存', 0x10123560, bytes(12), [('scratch', 0)])
        packet = self.run_to(0x100531b8)
        packet = self.call(packet, '加载电源报告', 0x101fbb82, bytes(64), [0x43090010, ('scratch', 0)])
        packet = self.call(packet, '初始化系统状态', 0x10058b90, SYSTEM_REPORT, [0x03040002, ('scratch', 0)])
        packet = self.run_to(0x1026b558)
        power = bytearray(self.remote.memory(0xc1f90df8, 0x30))
        struct.pack_into('<I', power, 0, struct.unpack_from('<I', power)[0] | 0x200)
        packet = self.call(packet, '接通虚拟电源', 0x101b63e6, power, [('scratch', 0)])
        packet = self.run_to(0x100531bc)
        packet = self.call(packet, '等待应用服务', 0x1005cbf8, bytes(8), [0xc1819748, 0])
        packet = self.run_to(0x100531bc)
        packet = self.restore_grid_setting(packet)
        if enter_menu:
            self.key(packet, 'menu')
        self.continue_guest()
        if announce_ready:
            self.refresh()
            self.update(phase='running', busy=False, message='正在绘制界面')

    def preserve_grid_setting(self):
        """Carry the native grid switch across UI profile guest rebuilds."""
        if not self.proc or self.state['phase'] not in ('running', 'paused'):
            return
        if self.running:
            self.pause()
        packet = self.run_to(0x100531bc)
        result = call_fixture(self.remote, packet, 0x1015bebe, bytes(8), [0x102d])
        value = int(result['return_r0'], 16)
        if value not in (0, 1):
            raise RuntimeError('Native grid setting is outside On/Off range')
        self.session_grid_setting = value
        self.audit({'kind': 'grid-setting-preserved', 'setting': '0x102d',
                    'value': value, 'result': result, 'scope': 'this UI session'})

    def restore_grid_setting(self, packet):
        if self.session_grid_setting is None:
            return packet
        value = self.session_grid_setting
        result = call_fixture(self.remote, packet, 0x101d7f02, bytes(8), [0x102d, value])
        packet = 'T05thread:'+result['return_cpu']+';'
        checked = call_fixture(self.remote, packet, 0x1015bebe, bytes(8), [0x102d])
        self.audit({'kind': 'grid-setting-restored', 'setting': '0x102d',
                    'value': value, 'set': result, 'readback': checked})
        if int(result['return_r0'], 16) != 1 or int(checked['return_r0'], 16) != value:
            raise RuntimeError('Native grid setting did not restore')
        self.update(grid_setting=value)
        return 'T05thread:'+checked['return_cpu']+';'

    def set_fixed_orientation(self, packet):
        """Use the firmware override API; this is not a physical IMU model."""
        value = self.orientation_fixture
        if value is None:
            return packet, None
        fixture = {'orientation': value, 'override_selector': [1, 3, 4, 2][value],
                   'original_api': '101b4224', 'imu_model': False,
                   'initialization_before': self.remote.memory(0xc18b6230, 4).hex()}
        for name, function, arguments in [
            ('before', 0x101b4dc2, []),
            ('set', 0x101b5ccc, [fixture['override_selector']]),
            ('settle', 0x10170cca, [1000]),
            ('after', 0x101b4dc2, []),
        ]:
            result = call_fixture(self.remote, packet, function, bytes(8), arguments)
            fixture[name] = result
            packet = 'T05thread:'+result['return_cpu']+';'
        fixture['initialization_after'] = self.remote.memory(0xc18b6230, 4).hex()
        self.audit({'kind': 'fixed-orientation-fixture', **fixture})
        if int(fixture['after']['return_r0'], 16) != value:
            raise RuntimeError('Fixed orientation did not take effect')
        return packet, fixture

    def set_keep_awake(self, packet):
        """Disable the shooting idle timeout through the native session setting.

        10090c7c reads 1021 in this profile; enum 0 selects zero seconds,
        and 10090e30 then declines to arm AppC_Tim. No timer RAM is patched.
        """
        if not self.keep_awake:
            return packet, None
        record = {'setting': '0x1021', 'value': 0, 'persistent_save_requested': False,
                  'scope': 'shooting idle timer; not sensor initialization'}
        for name, function, arguments in [
            ('before', 0x1015bebe, [0x1021]),
            ('set', 0x101d7f02, [0x1021, 0]),
            ('after', 0x1015bebe, [0x1021]),
            ('calculated_seconds', 0x10090b00, []),
        ]:
            result = call_fixture(self.remote, packet, function, bytes(8), arguments)
            record[name] = result
            packet = 'T05thread:'+result['return_cpu']+';'
        self.audit({'kind': 'shooting-idle-timeout-override', **record})
        if (int(record['set']['return_r0'], 16) != 1 or
                int(record['after']['return_r0'], 16) != 0 or
                int(record['calculated_seconds']['return_r0'], 16) != 0):
            raise RuntimeError('Original shooting idle timeout did not disable')
        self.update(idle_timeout_override={'setting': '0x1021', 'value': 0,
                    'calculated_seconds': 0, 'persistent_save_requested': False})
        return packet, record

    def boot_shooting(self):
        """Original shooting UI with explicitly logged diagnostic startup inputs.

        The optional control test supplies a TG test pulse and two EX MCU
        control replies. It does not supply a complete sensor config or pixels.
        """
        self.focus_code = 0
        self.focus_rect = None
        self.boot(enter_menu=False, announce_ready=False)
        self.update(phase='booting', busy=True, message='正在启动拍摄界面')
        self.pause()
        packet = self.run_to(0x100531bc)
        if self.capture_control_test:
            early_pointer = int.from_bytes(self.remote.memory(0xc18fa968, 4), 'little')
            if early_pointer:
                before = self.remote.memory(early_pointer+0xbe014, 2)
                assert self.remote.command(f'M{early_pointer+0xbe014:x},2:0370') == 'OK'
                self.audit({'kind': 'early-sensor-version-fixture', 'address': hex(early_pointer+0xbe014),
                            'original_bytes': before.hex(), 'bytes': '0370', 'diagnostic_only': True})
        if self.photo_liveview:
            self.remote.sock.settimeout(60)
            # Stationary-photo profile: the auxiliary MVD engine (20201000)
            # is not modeled. Suppress its frame schedule before any capture
            # is allocated, instead of fabricating completion or clearing a
            # live record. Native 102063e0 reads these 16 period/phase pairs;
            # 102064aa defines period=0 as disabled. This is a RAM fixture,
            # not a stock camera setting or an implementation of MVD/AF.
            address = 0xc18fb73c
            before = self.remote.memory(address, 128)
            if hashlib.sha256(before).hexdigest() != '07c5a2c856f6ac38d3feb4caa3345703aca7d6b023204ad4cb23c68fbcfe47aa':
                raise RuntimeError('MVD schedule differs from the verified C 3.80 table')
            disabled = bytes(len(before))
            assert self.remote.command(f'M{address:x},{len(disabled):x}:' + disabled.hex()) == 'OK'
            assert self.remote.memory(address, len(disabled)) == disabled
            self.audit({'kind': 'stationary-photo-mvd-disabled', 'diagnostic_only': True,
                        'address': hex(address), 'before': before.hex(), 'after': disabled.hex(),
                        'firmware_code_modified': False, 'motion_detection_implemented': False,
                        'applied_before_capture': True})
            for offset in (0x3dc, 0x3dd):
                packet = self.call(packet, '加载取景诊断设置', 0x101cb766, bytes(8), [offset, 1])
        packet, _ = self.set_fixed_orientation(packet)
        self.audit({'kind': 'capture_diagnostic_assumptions',
                    'kept_data_ready_without_data': True,
                    'empty_correction_table': True, 'absent_sensor_calibration': True,
                    'photo_liveview_profile': self.photo_liveview,
                    'physical_sensor_configuration_verified': False})
        packet = self.call(packet, '加载校正设置', 0x101cb734, bytes(8), [0x29e])
        packet = self.call(packet, '选择空校正表', 0x101cb766, bytes(8), [0x29e, 1])
        packet = self.call(packet, '持久数据诊断通知', 0x101e4a52, bytes(8), [0x03020008, 0])
        packet = self.call(packet, '拍摄模式通知', 0x1005d4c0, bytes(8), [0xc1819748, 0x05040016, 2])
        packet = self.call(packet, '拍摄参数通知', 0x1015beb2, bytes(8), [0x180c, 1])
        for _ in range(16):
            packet = self.run_to(0x100531c2)
            packet = self.run_to(0x100531bc)
            state = capture_state(self.remote)
            if state['ready'] & 3 == 3 and state['stage'] == 0:
                break
        else:
            raise RuntimeError('拍摄应用未完成就绪处理')
        packet = self.call(packet, '使用缺省校准分支', 0x10122852, bytes(8), [0])
        if self.capture_control_test:
            pointer = int.from_bytes(self.remote.memory(0xc18fa968, 4), 'little')
            original = self.remote.memory(pointer+0xbe014, 2)
            assert self.remote.command(f'M{pointer+0xbe014:x},2:0370') == 'OK'
            self.audit({'kind': 'sensor-version-fixture', 'address': hex(pointer+0xbe014),
                        'original_bytes': original.hex(), 'bytes': '0370',
                        'complete_sensor_configuration': False, 'diagnostic_only': True})
        self.audit({'kind': 'initial-liveview-controller',
                    'state': self.remote.memory(0xc18b84e0, 48).hex(),
                    'capture': capture_health(self.remote, self.device_evidence)})
        result = call_fixture(self.remote, packet, 0x10525a70, bytes(32),
                              [('scratch', 0), 0, ('scratch', 16)])
        if action_completed(result):
            # StartLV acknowledgement can precede the original GUI's drawing.
            # Let guest tasks finish their first draw before publishing ready.
            packet = 'T05thread:'+result['return_cpu']+';'
            packet, _ = self.set_keep_awake(packet)
            mode_name = next(name for name, value in MODES.items()
                             if value == self.session_exposure_mode)
            packet = self.dial_or_mode(packet, mode_name)
            packet = self.call(packet, '等待原厂界面绘制', 0x10170cca, bytes(8), [5000])
        self.refresh_device_evidence()
        health = capture_health(self.remote, self.device_evidence or None)
        health['control_test'] = self.capture_control_test
        health['complete_sensor_configuration'] = False
        health['start_lv_action_completed'] = action_completed(result)
        self.audit({'kind': 'capture_start', 'result': result, 'health': health})
        if not health['start_lv_action_completed']:
            raise RuntimeError('StartLV 动作未完成；详见本次运行日志')
        self.update(capture=health,focus=dict(self.focus_state))
        if self.focus_state['enabled']:
            packet = focus_display.apply(self,packet)
        self.refresh()
        (self.directory/'shooting-entry.png').write_bytes(self.png)
        self.continue_guest()
        self.update(phase='running', busy=False, message=self.running_message())
        self.update(startup_seconds=round(time.perf_counter()-self.boot_started, 3))

    def running_message(self):
        if self.profile == 'shooting':
            if self.photo_liveview:
                e = self.device_evidence
                return f"取景实验 · RAW {e.get('raw_batches', 0)} 批 · 处理 {e.get('isp_batches', 0)} 批"
            return '控制链实验 · RAW 0 帧' if self.capture_control_test else '运行中 · CMOS 未就绪'
        return '运行中'

    def refresh_shoulder(self):
        if self.shoulder_renderer is None:
            return
        import re
        from shoulder_display import rgb
        with self.live_log.open('r') as stream:
            stream.seek(self.shoulder_log_position)
            data = self.shoulder_log_tail + stream.read()
            self.shoulder_log_position = stream.tell()
        lines = data.split('\n')
        self.shoulder_log_tail = lines.pop()
        packets = []
        for line in lines:
            match = re.fullmatch(r'Z6_SHOULDER_PACKET channel=8 length=112 sequence=(\d+) data=([0-9a-f]{224})', line)
            if match:
                packets.append((int(match[1]), bytes.fromhex(match[2])))
        if not packets:
            return
        self.shoulder_packets += len(packets)
        sequence, payload = packets[-1]
        try:
            frame = self.shoulder_renderer.receive(payload)
            png = rgb_png(128, 96, rgb(frame))
            (self.directory/'shoulder.bin').write_bytes(frame)
            (self.directory/'shoulder.png').write_bytes(png)
            (self.directory/'shoulder-payload.bin').write_bytes(payload)
            evidence = dict(available=True, frame=self.shoulder_packets,
                packets=self.shoulder_packets, sequence=sequence,
                message='原厂肩屏快照 → 原生 MCU 绘图',
                framebuffer_sha256=hashlib.sha256(frame).hexdigest(),
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                lit_pixels=sum(byte.bit_count() for byte in frame),
                **self.shoulder_renderer.evidence())
            with self.lock:
                self.shoulder_png = png
                self.state['shoulder'] = evidence
            (self.directory/'shoulder-evidence.json').write_text(json.dumps(evidence, indent=2))
        except Exception as exc:
            self.update(shoulder=dict(available=False, frame=0,
                        message='肩屏绘图失败：'+str(exc)))

    def refresh_device_evidence(self):
        """Read new device log lines only; counters never infer physical accuracy."""
        if not self.photo_liveview:
            return
        import re
        with self.live_log.open('r') as f:
            f.seek(self.device_log_position)
            data = self.device_log_tail + f.read()
            self.device_log_position = f.tell()
        lines = data.split('\n')
        self.device_log_tail = lines.pop()
        e = self.device_evidence
        for line in lines:
            m = re.match(r'Z6_RAW_NATIVE0_STREAM seq=(\d+)', line)
            if m: e['raw_batches'] = int(m[1])
            m = re.match(r'Z6_IMAGE_PROCESS_BATCH batches=(\d+)', line)
            if m: e['isp_batches'] = int(m[1])
            m = re.search(r' host_us=(\d+) cache_hits=(\d+) cache_misses=(\d+)', line)
            if m:
                e['isp_host_ms'] = int(m[1])/1000
                e['isp_cache_hits'], e['isp_cache_misses'] = int(m[2]), int(m[3])
            m = re.match(r'Z6_IMAGE_PROCESS_OUTPUT .* channel=4 y=(0x[0-9a-f]+) uv=(0x[0-9a-f]+)', line)
            if m: self.preview_buffers.add((m[1], m[2]))
            m = re.match(r'Z6_LCD_SCANOUT frame=(\d+) y=(0x[0-9a-f]+) uv=(0x[0-9a-f]+)', line)
            if m:
                e['lcd_frames_observed'] = int(m[1])
                e['lcd_y'], e['lcd_uv'] = m[2], m[3]
                if (m[2], m[3]) in self.preview_buffers:
                    e['processed_buffer_scanned'] = True
        values = {'device_evidence': dict(e)}
        if self.raw_source:
            raw = self.raw_source.status()
            raw.update(guest_frames_transferred=e['raw_batches']*4,
                       firmware_frames_consumed=None,
                       functional_isp_input_reads=e['isp_batches']*4,
                       cmos_input_connected=e['raw_batches'] > 0,
                       blocked_by=None if e['raw_batches'] else 'Waiting for native RAW descriptors')
            values['raw_input'] = raw
        if self.state.get('capture'):
            health = dict(self.state['capture'])
            health.update(cmos_input_connected=e['raw_batches'] > 0,
                          cmos_frames_injected=e['raw_batches']*4,
                          live_view_verified=None,
                          processed_source_scanout_observed=e['processed_buffer_scanned'],
                          image_evidence_scope='experimental device log; visual QA recorded separately')
            values['capture'] = health
        self.update(**values)

    def pause(self):
        if self.running:
            self.remote.sock.sendall(b'\x03')
            self.receive_stop()

    def refresh(self):
        refresh_started = time.perf_counter()
        if self.proc.poll() is not None:
            raise RuntimeError(f'QEMU 已退出（{self.proc.returncode}）')
        status = self.monitor.command('query-status')
        if self.running and not status['running']:
            raise RuntimeError('虚拟机已停止：'+status['status'])
        self.refresh_device_evidence()
        self.refresh_shoulder()
        if not self.running and self.state.get('capture') is not None:
            # Publish a fresh paused observation instead of retaining boot state.
            health = dict(self.state['capture'])
            health.update(capture_health(self.remote, self.device_evidence or None))
            self.update(capture=health)
        # High-frequency QMP scratch I/O stays on the Nikon Linux filesystem.
        # Only changed PNGs and audit evidence go to the shared project drive.
        path = self.frame_spool/'screen.ppm'
        self.monitor.command('screendump', {'filename': str(path)})
        w, h, pixels = ppm_pixels(path.read_bytes())
        sha = hashlib.sha256(pixels).hexdigest()
        changed = sha != self.previous_pixels
        png = rgb_png(w, h, pixels) if changed else None
        if changed:
            (self.directory/'screen.png').write_bytes(png)
            self.png_encodes += 1
        self.refresh_samples += 1
        self.refresh_seconds += time.perf_counter()-refresh_started
        with self.lock:
            if changed:
                self.previous_pixels = sha
                self.png = png
                self.state['frame'] += 1
                self.state['frame_sha256'] = sha
                self.state['updated_at'] = time.time()
            self.state['performance'] = dict(one_insn_per_tb=self.one_insn_per_tb,
                refresh_samples=self.refresh_samples, png_encodes=self.png_encodes,
                refresh_mean_ms=round(self.refresh_seconds*1000/self.refresh_samples, 3))
            self.state['heartbeat'] = time.time()
            if self.state['phase'] == 'running' and not self.state['busy']:
                self.state['message'] = self.running_message()

    def close_guest(self):
        for handle in (self.remote, self.monitor):
            if handle:
                try:
                    handle.sock.close() if isinstance(handle, Remote) else handle.close()
                except OSError:
                    pass
        self.remote = self.monitor = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait()
        self.proc = None
        if self.console:
            self.console.close(); self.console = None
        if hasattr(self, 'live_log'):
            if self.live_log.exists():
                shutil.copyfile(self.live_log, self.directory/self.live_log.name)
                self.live_log.unlink()
            del self.live_log
        self.running = False
        if hasattr(self, 'frame_spool'):
            (self.frame_spool/'screen.ppm').unlink(missing_ok=True)
            self.frame_spool.rmdir()
            del self.frame_spool

    def worker(self):
        restart = True
        while True:
            try:
                if restart:
                    self.close_guest()
                    if self.profile == 'shooting':
                        self.boot_shooting()
                    else:
                        self.boot()
                    restart = False
                item = None
                try:
                    item = self.requests.get(timeout=.08 if self.running else .5)
                except queue.Empty:
                    pass
                if item:
                    self.update(busy=True)
                    self.audit({'kind': 'browser_action', **item})
                    action = item['action']
                    if action == 'restart':
                        self.preserve_grid_setting()
                        restart = True
                    elif action in ('shooting', 'menu-profile'):
                        self.preserve_grid_setting()
                        self.profile = 'shooting' if action == 'shooting' else 'menu'
                        restart = True
                    elif action == 'stop':
                        self.close_guest()
                        self.update(phase='stopped', message='已停止，可以重新启动')
                    elif action == 'pause' and self.running:
                        self.pause(); self.update(phase='paused', message='已暂停')
                    elif action == 'resume' and self.proc and not self.running:
                        self.continue_guest()
                        self.update(phase='running', message='运行中')
                    elif action == 'key' and self.running:
                        self.pause()
                        packet = self.run_to(0x100531bc)
                        self.key(packet, item['key'])
                        self.continue_guest()
                        self.update(last_key=LABELS[item['key']], message='运行中')
                    if restart:
                        self.update(phase='booting', message='正在重新启动')
                    elif self.proc:
                        # Publish the final paused/drawn frame before acknowledging
                        # the action; otherwise clients can observe one stale frame.
                        self.refresh()
                    self.update(busy=restart, completed_action=item['id'])
                if self.proc and not restart and not item:
                    if self.running:
                        self.refresh()
                    elif self.proc.poll() is not None:
                        raise RuntimeError(f'QEMU 已退出（{self.proc.returncode}）')
            except Exception as error:
                self.audit({'kind': 'error', 'error': str(error), 'traceback': traceback.format_exc(), 'incomplete_fixture': probe.ACTIVE_FIXTURE})
                self.close_guest()
                self.update(phase='error', message='运行已停止', busy=False, error=str(error))
                restart = False
                # Keep the UI available so the user can review or restart.


def main():
    global FIRMWARE, BUILD_MANIFEST
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware', type=Path, required=True, help='Your locally obtained extracted Z6 C3.80 MAIN')
    p.add_argument('--companion-firmware', type=Path, help='Optional locally supplied verified companion-MCU image for shoulder display')
    p.add_argument('--build-manifest', type=Path, default=BUILD_MANIFEST)
    p.add_argument('--port', type=int, default=8787)
    p.add_argument('--one-insn-per-tb', action=argparse.BooleanOptionalAction, default=False,
                   help='Slow diagnostic translation mode; normal blocks are the interactive default')
    p.add_argument('--isp-disable-cache', action='store_true', help='Recompute ISP pixels for diagnostic comparisons')
    p.add_argument('--tg-period-ms', type=int, choices=range(17,101), default=None, help='Experimental TG edge interval, milliseconds')
    p.add_argument('--allow-modified-firmware', action='store_true', help='Permit a same-layout 33502842-byte Z6 C3.80 research MAIN; no compatibility guarantee')
    p.add_argument('--profile', choices=('menu','shooting'), default='menu')
    p.add_argument('--capture-control-test', action='store_true',
                   help='Enable experimental TG/EX MCU control inputs and a version-only RAM fixture; no RAW input')
    p.add_argument('--no-lens', action='store_true',
                   help='Simulate the lens-absent EX MCU controller; experimental, no CMOS samples')
    p.add_argument('--orientation-fixture', type=int, choices=range(4),
                   help='Fixed orientation through original firmware API; 0 is landscape, not an IMU model')
    p.add_argument('--keep-awake', action='store_true',
                   help='Disable shooting idle timeout through native setting 1021=0; session only')
    p.add_argument('--exposure-probe', action='store_true',
                   help='Enable physical full-release input and passive timing traces; no exposure completion fixture')
    p.add_argument('--no-current', action='store_true', help='Do not replace the primary session pointer')
    p.add_argument('--raw-source', type=Path,
                   help='Unpacked Bayer manifest; defaults to active_cmos.json')
    p.add_argument('--raw-ingress-test', action='store_true',
                   help='Transfer active packed CMOS source through the experimental native DMA channel')
    p.add_argument('--isp-boundary-test', action='store_true',
                   help='Experimental ISP interrupt routing after RAW DMA; not complete ISP emulation')
    p.add_argument('--photo-liveview', action='store_true',
                   help='Experimental Bayer input and ISP/LCD path, no lens and diagnostic calibration; Z6 live view is under validation')
    a = p.parse_args()
    if os.environ.get('Z6_TRACE_START_ERRORS'):
        import probe
        probe.TRACE_CALL.extend([0x101df6a2, 0x100bc712, 0x10122454, 0x100be8be, 0x100be3b8, 0x100bdbb0, 0x100bc450, 0x100bd7c4, 0x100bc762, 0x100bea12, 0x100be9ea, 0x100be9f2, 0x10105eae, 0x100d65a2, 0x100d65b4, 0x100d62e4, 0x100d59ac, 0x100f4a32, 0x1017c69c, 0x1017bfba])
        probe.TRACE_REPEAT.update([0x101df6a2, 0x100be8be, 0x100bc762, 0x100be9ea, 0x100be9f2, 0x10105eae, 0x100d65a2, 0x100d65b4, 0x100d62e4, 0x100d59ac, 0x100f4a32, 0x1017c69c, 0x1017bfba])
    if os.environ.get('Z6_TRACE_RETURN_ERRORS'):
        import probe
        points = [0x100bc712, 0x100bc762, 0x100be8be, 0x100f4a32,
                  0x101df6a2, 0x10122454, 0x1017c69c, 0x1017bfba,
                  0x101edbb0, 0x101edbe0, 0x101edc3e, 0x101eec0c]
        probe.TRACE_CALL.extend(points)
        probe.TRACE_REPEAT.update(points)
    FIRMWARE = a.firmware.resolve(strict=True)
    BUILD_MANIFEST = a.build_manifest.resolve(strict=True)
    try:
        firmware_sha256 = checked_firmware(FIRMWARE, a.allow_modified_firmware)
    except ValueError as exc:
        p.error(str(exc))
    if not a.photo_liveview and not a.raw_source:
        raw_default = None
    else:
        raw_default = a.raw_source or active_manifest('native0' if a.photo_liveview else 'unpacked')
    if a.photo_liveview and a.raw_source and a.raw_source.resolve() != active_manifest('native0'):
        p.error('--photo-liveview uses the checked active native0 source; regenerate tools/make_cmos.py inputs to replace it')
    if os.name == 'nt':
        p.error('Run this launcher in Linux or an explicitly selected WSL distribution; see docs/build.md')
    ingress = a.raw_ingress_test or a.photo_liveview
    camera = Camera(a.port, a.profile, capture_control_test=a.capture_control_test or a.photo_liveview,
                    raw_source=raw_default, exmcu_no_lens=a.no_lens or a.photo_liveview,
                    tg_periodic_test=ingress, tg_paired_test=ingress,
                    raw_ingress_test=active_ingress() if ingress else None,
                    isp_boundary_test=a.isp_boundary_test or a.photo_liveview,
                    orientation_fixture=0 if a.photo_liveview and a.orientation_fixture is None else a.orientation_fixture,
                    keep_awake=a.keep_awake or a.photo_liveview, photo_liveview=a.photo_liveview,
                    one_insn_per_tb=a.one_insn_per_tb,
                    allow_modified_firmware=a.allow_modified_firmware,
                    firmware_sha256=firmware_sha256, exposure_probe=a.exposure_probe,
                    companion_firmware=a.companion_firmware)
    camera.isp_disable_cache = a.isp_disable_cache
    camera.tg_period_ms = a.tg_period_ms
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, content, mime='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/':
                html = (ROOT/'interactive.html').read_text(encoding='utf-8').replace('__TOKEN__', camera.token)
                self.send(200, html.encode(), 'text/html; charset=utf-8')
            elif path == '/api/status':
                self.send(200, json.dumps(camera.snapshot(), ensure_ascii=False).encode())
            elif path == '/api/frame':
                with camera.lock:
                    png = camera.png
                self.send(200 if png else 503, png or b'Frame not ready', 'image/png' if png else 'text/plain')
            elif path == '/api/shoulder':
                with camera.lock:
                    png = camera.shoulder_png
                self.send(200 if png else 503, png or b'Shoulder not ready', 'image/png' if png else 'text/plain')
            elif path == '/favicon.ico':
                self.send(204, b'')
            else:
                self.send(404, b'Not found', 'text/plain')

        def do_POST(self):
            if self.path != '/api/action' or self.headers.get('X-Z6-Token') != camera.token:
                self.send(403, b'{"error":"Forbidden"}'); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(length))
                item = camera.submit(data.get('action'), data.get('key'))
                self.send(202, json.dumps(item).encode())
            except (ValueError, RuntimeError, queue.Full) as error:
                self.send(409, json.dumps({'error': str(error) or '操作队列已满'}, ensure_ascii=False).encode())

    server = http.server.ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    if not a.no_current:
        (PROJECT/'.local/sessions/current.json').write_text(json.dumps({
            'url': f'http://127.0.0.1:{a.port}', 'pid': os.getpid(), 'session': camera.stamp,
            'directory': str(camera.directory), 'profile': a.profile,
            'wsl_distribution': os.environ.get('WSL_DISTRO_NAME'),
            'raw_source': str(camera.raw_source.path) if camera.raw_source else None,
            'capture_control_test': camera.capture_control_test, 'no_lens_simulation': camera.exmcu_no_lens,
            'orientation_fixture': camera.orientation_fixture, 'keep_awake': camera.keep_awake,
            'photo_liveview': camera.photo_liveview, 'build': json.loads(
                (BUILD_MANIFEST).read_text())}, indent=2))
    threading.Thread(target=camera.worker, daemon=True).start()
    print(f'Z6 interactive UI: http://127.0.0.1:{a.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        camera.close_guest()


if __name__ == '__main__':
    main()
