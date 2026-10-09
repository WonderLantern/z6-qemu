# Build

Use Linux with Python3.12+, GCC/Clang, Ninja, pkg-config, GLib, Pixman, zlib and libfdt development headers. NumPy/Pillow are needed for RAW generation; the HTTP server uses Python's standard library.

`python tools/build.py --jobs 4` fetches QEMU10.2.4 from download.qemu.org and verifies SHA256 `821b545b92f165e57dddccac5077d76d4d436a226595b8813ad59306bbfd0746`. It applies this overlay and builds ARM TCG. Generated absolute binary paths go into ignored `.local/build-manifest.json`; build a new manifest on each computer.

Offline: `python tools/build.py --archive /path/to/qemu-10.2.4.tar.xz --jobs 4`. Alternate cache: `--work-dir /path/to/cache`. The archive must still match the pinned digest. Allow several GB of disk space; build duration varies with CPU and parallelism.

Windows: enter your selected WSL distribution with `wsl -d <name>`, then use the Linux commands. Quote paths with spaces. The package does not install/select a distribution or access a physical camera.
