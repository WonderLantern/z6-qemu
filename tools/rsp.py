# SPDX-License-Identifier: GPL-2.0-or-later
"""Small ARM QEMU RSP client; localhost connections only."""
import socket
import time

class Remote:
    def __init__(self, port):
        end = time.monotonic()+5
        while True:
            try:
                self.sock = socket.create_connection(('127.0.0.1',port),.2)
                break
            except OSError:
                if time.monotonic()>end: raise
                time.sleep(.05)
        self.sock.settimeout(5)
        self.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.buffer=bytearray()
    def byte(self):
        if not self.buffer:
            self.buffer.extend(self.sock.recv(65536))
            if not self.buffer: raise EOFError('QEMU closed remote connection')
        c=self.buffer[0]; del self.buffer[0]
        return c
    def receive(self):
        while True:
            if self.byte() == ord('$'): break
        raw = bytearray()
        while True:
            c = self.byte()
            if c==ord('#'): break
            raw.append(c)
        check=bytes([self.byte(),self.byte()])
        if sum(raw)%256!=int(check,16): raise ValueError('RSP checksum')
        self.sock.sendall(b'+')
        # These commands request only ASCII hex / stop replies, no binary data.
        out=bytearray(); it=iter(raw)
        for c in it:
            if c==ord('*'): out.extend(bytes([out[-1]])*(next(it)-29))
            elif c==ord('}'): out.append(next(it)^0x20)
            else: out.append(c)
        return out.decode()
    def send(self, text):
        raw=text.encode()
        self.sock.sendall(b'$'+raw+b'#'+f'{sum(raw)%256:02x}'.encode())
    def command(self, text):
        self.send(text)
        return self.receive()
    def registers(self):
        # QEMU may suppress p packets before XML negotiation; g is always available.
        raw=self.command('g')
        b=bytes.fromhex(raw)
        regs={f'r{i}':f'0x{int.from_bytes(b[i*4:i*4+4],"little"):08x}' for i in range(16)}
        # Legacy ARM layout includes 8 FPA registers and FPS before CPSR.
        offset=64 if len(b)==68 else 164
        regs['cpsr']=f'0x{int.from_bytes(b[offset:offset+4],"little"):08x}' if len(b)>=offset+4 else None
        regs['packet_bytes']=len(b)
        return regs
    def memory(self,address,length):
        out=bytearray()
        while len(out)<length:
            n=min(4096,length-len(out))
            raw=self.command(f'm{address+len(out):x},{n:x}')
            if raw.startswith('E'): raise ValueError(f'RSP memory {address:#x}: {raw}')
            part=bytes.fromhex(raw)
            if len(part)!=n: raise ValueError('Short RSP memory response')
            out.extend(part)
        return bytes(out)
