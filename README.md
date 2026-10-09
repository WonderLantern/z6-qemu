# WonderLantern Z6 QEMU

[中文](README.zh-CN.md) · [Build](docs/build.md) · [Firmware](docs/firmware.md) · [Architecture](docs/architecture.md) · [Testing](docs/testing.md)

Experimental Nikon Z6 C 3.80 machine for QEMU 10.2.4, with a local browser controller, firmware-rendered menus, synthetic RAW → functional ISP → LCD, native grid scanout and main/sub command-dial inputs.

**Bring your own firmware.** This source package contains no Nikon firmware, decrypted payload, camera dump, key, calibration, extracted fonts/icons or firmware-rendered screenshots. The tools do not download firmware.

## Quick start

Linux or WSL, Python 3.12+:

```sh
sudo apt-get update
sudo apt-get install build-essential ninja-build pkg-config python3-venv libglib2.0-dev libpixman-1-dev zlib1g-dev libfdt-dev
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python tools/build.py --jobs 4
python tools/make_cmos.py
python tools/interactive.py --firmware /path/to/your/z6-c380-main.bin --profile shooting --photo-liveview --port 8787
```

Open http://127.0.0.1:8787/ . Default shooting mode is M. Use main-wheel buttons or `[` / `]` to adjust shutter speed through the original firmware input path. Sub-wheel keys are `{` / `}`; wheel areas also accept mouse scrolling. Startup is assisted through original firmware calls, rather than natural camera power-on.

Compatible input is the extracted Z6 C 3.80 MAIN: **33,502,842 bytes**, SHA-256 `1e6348d58750e67372d0a8e363932c57ee9c04d0eb8f62803bcd19812df0d25c`. An upgrade container cannot substitute. See [firmware input](docs/firmware.md).

## Status and limits

The local baseline has shown original 1024×682 menus, continuous synthetic RAW/ISP/LCD output, d9 grid lines and M-mode shutter changes 1/8000 → 1/6400 → 1/5000, with reverse input restoring the previous value. The export is tested separately; see [testing](docs/testing.md).

The default profile has no lens. Selecting S currently still displays A and does not adjust Tv; use M for shutter tests. The cause is not fully traced. Sub-wheel input is connected, but aperture changes are unverified without a lens. Returning from menus to continuous live view still requires **Shooting start**, which recreates the guest. Mode/grid settings are retained within the server session; shutter settings are not retained across guest recreation.

This is an experimental functional model. It does not prove physical CMOS protocol, Nikon ISP algorithms, AF, physical exposure duration, photo saving, movie encoding or shutter-sound behavior. It runs on your computer and is not a camera-flashable package.

## Source and tests

- `qemu/`: Z6 board/profile, shared GPU/ISP and upstream integration.
- `tools/`: pinned build, browser controller, RSP and synthetic RAW generation.
- `tests/`: firmware-free RAW checks, ISP/grid sanitizers and QTest IRQ/MMIO.
- `docs/`: portable setup, implementation assumptions and validation.

```sh
sh tests/run.sh
python tests/test_irq99.py --qemu .build/build/qemu-system-arm
python tools/verify_release.py
```

## Acknowledgements

Thank you to [R3tr0ooo](https://github.com/R3tr0ooo), the author of [WonderLantern Z7 QEMU](https://github.com/WonderLantern/z7-qemu), and its contributors for publishing the experimental Nikon machine, graphics pipeline and research tools. Their work provided the starting point for this Z6 port. We retain the shared code's attribution and license notices while developing and validating the Z6-specific profile and interfaces separately.

[Contributing](CONTRIBUTING.md) · [Notice](NOTICE.md) · [GPL-2.0-or-later](COPYING)
