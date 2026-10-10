# Display and counter additions

[Home](../README.md) · [Usage](usage.md) · [Testing](testing.md)

## Optional shoulder display

The main CPU's channel 8, tag 4 SPI snapshot is observed by the QEMU model. The controller passes its 112-byte payload to a bounded Unicorn harness which executes the original companion MCU receive, publication and compositor functions. The resulting 128 × 96, one-bit framebuffer is converted to PNG; host fonts or number formatting are not used.

The harness invokes the original decompressor at startup and checks both the supplied image and initialized data identities. The source package includes no companion firmware or decompressed assets.

Install the optional Python dependency in the environment that runs the controller:

```sh
python -m pip install -r requirements-shoulder.txt
python tools/interactive.py --firmware /path/to/z6-c380-main.bin \
    --companion-firmware /path/to/ex1620_037000.bi \
    --profile shooting --photo-liveview --port 8787
```

The accepted companion image has SHA-256:

```text
72f1fb29e24b36b872eec697a486abeff8bcef77f6020fa89473fd014aa18131
```

`--companion-firmware` is an explicit local input. Without it, or when dependency/identity checks fail, the main display remains available and shoulder status reports the reason. `/api/shoulder` serves the latest PNG when available.

The function harness substitutes an event-notification boundary and explicitly calls publication/composition. It is not a full companion RTOS or physical OLED bus model.

Run the optional firmware-dependent test locally:

```sh
python tests/test_shoulder_display.py --firmware /path/to/ex1620_037000.bi \
    --out .local/shoulder-test
```

Its output includes original rendered pixels and must remain local. This test is excluded from the firmware-free workflow.

## S/L focus display diagnostics

The browser's S/L controls use original geometry helpers and GPU drawing calls. The controls select a size, move the center by 12 source pixels, enable/disable the frame and inject white/green/red display states. These injected states are diagnostics, not optical focus results.

Build the RAM-only drawing helper before using those controls. It requires ARM GNU `arm-none-eabi-gcc`, `nm`, `objcopy` and `objdump`:

```sh
python tools/build_af_display.py
```

By default the script searches PATH. A separate installation can be selected explicitly:

```sh
python tools/build_af_display.py --toolchain-dir /path/to/arm-gnu/bin
```

The builder also accepts Windows executables in a selected directory. Output goes to `.local/af-display-build/`; no compiled helper is bundled. The controller verifies its source and binary hashes before using it. Without a built helper, AF drawing reports a build instruction; other controls remain separate.

The helper is allocated in guest RAM and calls the original GPU. It does not alter the supplied MAIN file. Within the server session, enabled frame state is reapplied on successful shooting startup.

The LCD model now supports the second overlay plane, region selection, color-bank addressing, alpha and clipping. In the explicit no-lens test profile, a second-plane frame with both zero ROI and zero center is omitted; valid ROI or nonzero-center frames remain on the original composition path.

## Counter model and opt-in probes

The CAPTG counter model schedules terminal events from initial/terminal count and the selected clock. Its firmware-free QTest covers short, 32/60/900-second counts, compensation, cancellation and unknown-clock handling:

```sh
python tests/test_counter_timing.py --qemu .build/build/qemu-system-arm
```

These are virtual counter deadlines. They do not establish sensor integration or a completed still photograph.

`--exposure-probe` exposes diagnostic full-release input and an original-converter/counter-driver check. It is off by default. The diagnostic driver check starts and stops its counter without waiting for a whole exposure interval.

The log summarizer keeps counter completion separate from sensor integration:

```sh
python tools/exposure_trace.py /path/to/local/qemu.log \
    --output .local/counter-report.json
```

Its report records trace truncation and leaves physical-tick, sensor-integration and firmware-capture verification false.

## Live display checks

With a running shooting session, generated RAW input, a built AF helper and the optional companion input, these checks operate through the local browser API:

```sh
python tests/test_shoulder_live.py --url http://127.0.0.1:8787 \
    --out .local/shoulder-live
python tests/test_af_display_live.py --url http://127.0.0.1:8787 \
    --out .local/af-live
```

Use the URL without a trailing slash when invoking the scripts, since they append endpoint paths. The shoulder test checks native dial changes/reversal and pause/resume. The AF test checks six display cases including the invalid corner frame, size changes, red state and clearing. Both save local firmware-rendered screenshots; neither is a firmware-free CI test.
