# WonderLantern Z6 QEMU

[中文](README.zh-CN.md) · [Build](docs/build.md) · [Firmware](docs/firmware.md) · [Architecture](docs/architecture.md) · [Usage](docs/usage.md) · [Debugging](docs/debugging.md) · [Testing](docs/testing.md) · [Publication](docs/publication.md)

Experimental Nikon Z6 C 3.80 machine for QEMU 10.2.4, with a local browser controller, firmware-rendered menus, synthetic RAW → functional ISP → LCD, native grid scanout and main/sub command-dial inputs.

**Bring your own firmware.** This source package contains no Nikon firmware, decrypted payload, camera dump, key, calibration, extracted fonts/icons or firmware-rendered screenshots. The tools do not download firmware.

## New display and counter support

This preview adds optional original companion-MCU shoulder rendering, S/L focus-frame diagnostics, native LCD second-plane composition and CAPTG counter tests. [Setup and scope](docs/display-counter.md) explains the optional firmware/dependency inputs and RAM helper build. Focus colors are injected diagnostic states; counter completion is not a completed photograph.

## Quick start

Linux or WSL, Python 3.12+:

```sh
git clone https://github.com/WonderLantern/z6-qemu.git
cd z6-qemu
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

The default profile has no lens. Selecting S currently still displays A and does not adjust Tv; use M for shutter tests. The cause is not fully traced. Sub-wheel input is connected, but aperture changes are unverified without a lens. Returning from menus to continuous live view still requires **Shooting start**, which recreates the guest. The server remembers mode/grid settings: grid is restored during guest recreation, and exposure mode is reapplied after shooting startup succeeds. Shutter settings are not retained across guest recreation.

This is an experimental functional model. It does not prove physical CMOS protocol, Nikon ISP algorithms, AF, physical exposure duration, photo saving, movie encoding or shutter-sound behavior. It runs on your computer and is not a camera-flashable package.

## Source and tests

- `qemu/`: Z6 board/profile, shared GPU/ISP and upstream integration.
- `tools/`: pinned build, browser controller, RSP and synthetic RAW generation.
- `tests/`: firmware-free RAW checks, ISP/grid sanitizers and QTest IRQ/MMIO.
- `docs/`: portable setup, implementation assumptions and validation.

```sh
sh tests/run.sh
python tests/test_irq99.py --qemu .build/build/qemu-system-arm
python tests/test_counter_timing.py --qemu .build/build/qemu-system-arm
python tools/verify_release.py
```

## Documentation map

| Guide | Contents |
| --- | --- |
| [Build](docs/build.md) | Dependencies, pinned archive, offline build, WSL and build errors |
| [Firmware input](docs/firmware.md) | Accepted MAIN, checks and modified-input flag |
| [Usage](docs/usage.md) | Launch profiles, keys, dials, scene replacement and session behavior |
| [Architecture](docs/architecture.md) | Z6 profile, assisted startup, image path, grid and upstream changes |
| [Debugging](docs/debugging.md) | Session status, diagnostic calls and capture evidence |
| [Display and counters](docs/display-counter.md) | Optional shoulder setup, AF helper and counter probes |
| [Testing](docs/testing.md) | Synthetic checks and dated export verification |
| [Publication](docs/publication.md) | Source inventory, local-output boundary and attribution |

## Acknowledgements

Thank you to [R3tr0ooo](https://github.com/R3tr0ooo), the author of [WonderLantern Z7 QEMU](https://github.com/WonderLantern/z7-qemu), and its contributors for publishing the experimental Nikon machine, graphics pipeline and research tools. Their work provided the starting point for this Z6 port. We retain the shared code's attribution and license notices while developing and validating the Z6-specific profile and interfaces separately.

[Contributing](CONTRIBUTING.md) · [Notice](NOTICE.md) · [GPL-2.0-or-later](COPYING)
