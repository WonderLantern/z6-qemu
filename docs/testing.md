# Tests and export validation

The public export is validated separately from the working research directory. No original firmware or generated runtime output is part of the source inventory/ZIP.

## Recorded export verification

2026-10-09: the exported overlay was applied to a clean extraction of the hash-verified QEMU10.2.4 archive, configured and compiled in a separate build cache. All1363 build targets completed successfully. The input archive was supplied from a local cache; the download branch was not exercised in this run.

Firmware-free QTest passed all five checks: pending RAW IRQ99 enable/W1C behavior, SDES configuration readback, native grid-enable readback, Z6 memory profile isolation and independent machine registration. It used the newly built export binary, not the development binary.

`tests/run.sh` passed on Linux/Python3.12.3 with NumPy2.5.3 and Pillow12.3.0: three synthetic input test groups, the actual LCD grid function under ASan/UBSan, and593 functional ISP checks under ASan/UBSan. Default synthetic inputs were generated and packing round trips checked. Dependency wheels were obtained from PyPI and checked against its SHA256 metadata after a network download failed integrity checks; no TLS or hash checks were disabled.

The working baseline has shown original menus/live view/grid and M-mode Tv312→304→296, with display tuples(192,2496)→(192,2432)→(192,2368), corresponding to1/8000→1/6400→1/5000. The independent export binary also booted original live view, changed M-mode312→304 with its matching LCD1/6400, and entered the original playback menu. That smoke test used a local official firmware input; logs/screenshots remain outside the public inventory. It is separate from synthetic tests and CI, which never load Nikon firmware.

No physical camera, card, exposure duration, recording, AF, sound, movie encoder or complete hardware behavior is verified by these export tests. At the time of the original 2026-10-09 package preparation, the GitHub workflow had not been executed remotely. This dated record does not establish the current Actions status.

## Run the firmware-free checks

From the repository root with dependencies installed:

```sh
python tools/verify_release.py
sh tests/run.sh
python tools/make_cmos.py
python tests/test_irq99.py --qemu .build/build/qemu-system-arm
python tests/test_counter_timing.py --qemu .build/build/qemu-system-arm
```

The QTest command requires a built emulator. With a separate build cache, pass its `qemu-system-arm` path instead.

| Check | What it exercises |
| --- | --- |
| `verify_release.py` | Declared source inventory and byte hashes |
| `test_inputs.py` | Synthetic RAW input contracts |
| `test_lcd_grid.py` | Actual grid renderer under ASan/UBSan |
| `test_lcd_overlay.py` | Actual LCD region/bank composition under ASan/UBSan |
| `test_counter_timing.py` | Virtual counter terminal deadlines, cancellation and unknown-clock handling |
| `test_isp.c` through `run.sh` | Functional ISP pixel checks under ASan/UBSan |
| `make_cmos.py` | Generated Bayer packing round trips |
| `test_irq99.py` | Pending completion IRQ mask/W1C, SDES readback, grid enable and Z6 machine/memory isolation |

The GitHub workflow contains dependency installation, source checks, synthetic tests, input generation, a pinned QEMU build and QTest. It supplies no Nikon firmware.

## Firmware-dependent reproduction

The documented independent export smoke test used the accepted official MAIN, the exported binary and a local browser session. Its observed results were original live view, M-mode main-dial Tv312 to Tv304 with LCD 1/8000 to 1/6400, and entry into the original playback menu.

For comparison runs, record the firmware and binary hashes, profile, RAW manifest, mode, starting value, exact input and resulting native readback/display. A successful build or register assertion alone does not establish the displayed camera behavior.

The working-baseline results and independent-export results above have different scopes. The original local screenshots and logs remain outside the public source inventory.

## 2026-10-11 preview checks

The source-only candidate passed three synthetic input test groups, the actual grid renderer and LCD region/bank compositor under ASan/UBSan, and 593 ISP checks. The grid test's source extraction was updated to stop at the newly inserted overlay function; the asserted grid behavior was retained.

The portable AF builder reproduced the existing tested research helper byte-for-byte using the same ARM GNU toolchain. It accepts a toolchain directory or PATH instead of a private absolute path.

The candidate shoulder test executed native decompression, ingress, publication and rendering against a local identity-checked companion image: six pixel cases and four malformed-input rejections passed. The firmware and resulting images are not in this source package.

These candidate checks are separate from earlier development-guest visual records. The optional shoulder test loads proprietary firmware locally and is excluded from public CI.

The preview overlay was built from a separate extraction of the hash-verified QEMU 10.2.4 archive; all 1,363 build targets completed. The new binary passed the five existing machine/IRQ/readback checks and all seven CAPTG counter cases. The archive was supplied locally; this check did not exercise the download branch.

An independent candidate guest then passed the live shoulder test (native dial change/reversal and pause/resume), six AF display pixel cases, and restart recovery of AF state and shoulder pixels. Original MENU input also completed. Main LCD and shoulder snapshots were inspected locally; screenshots and session records are excluded from this source package. The owned review guest and launcher were closed after the checks.
