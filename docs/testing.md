# Validation of this export

The public export is validated separately from the working research directory. No original firmware or generated runtime output is part of the source inventory/ZIP.

2026-10-09: the exported overlay was applied to a clean extraction of the hash-verified QEMU10.2.4 archive, configured and compiled in a separate build cache. All1363 build targets completed successfully. The input archive was supplied from a local cache; the download branch was not exercised in this run.

Firmware-free QTest passed all five checks: pending RAW IRQ99 enable/W1C behavior, SDES configuration readback, native grid-enable readback, Z6 memory profile isolation and independent machine registration. It used the newly built export binary, not the development binary.

`tests/run.sh` passed on Linux/Python3.12.3 with NumPy2.5.3 and Pillow12.3.0: three synthetic input test groups, the actual LCD grid function under ASan/UBSan, and593 functional ISP checks under ASan/UBSan. Default synthetic inputs were generated and packing round trips checked. Dependency wheels were obtained from PyPI and checked against its SHA256 metadata after a network download failed integrity checks; no TLS or hash checks were disabled.

The working baseline has shown original menus/live view/grid and M-mode Tv312→304→296, with display tuples(192,2496)→(192,2432)→(192,2368), corresponding to1/8000→1/6400→1/5000. The independent export binary also booted original live view, changed M-mode312→304 with its matching LCD1/6400, and entered the original playback menu. That smoke test used a local official firmware input; logs/screenshots remain outside the public inventory. It is separate from synthetic tests and CI, which never load Nikon firmware.

No physical camera, card, exposure duration, recording, AF, sound, movie encoder or complete hardware behavior is verified by these export tests. The GitHub workflow is provided but has not been executed remotely as part of preparing this package.
