# Experimental Z6 machine and image pipeline

[Home](../README.md) · [Debugging](debugging.md) · [Testing](testing.md)

## Components

| Source | Responsibility |
| --- | --- |
| `qemu/nikon-z6.c` | Machine registration, memory, selected peripherals and LCD integration |
| `qemu/nikon-z6-profile.h` | Z6 memory windows, MAIN placement, RAW geometry and functional timing |
| `qemu/nikon-model-config.h` | Shared geometry and timing types |
| `qemu/nikon-gpu.h` | Selected graphics commands and pixel composition |
| `qemu/nikon-functional-isp.h` | Functional image-processing control |
| `qemu/nikon-isp-pixels.h` | Pixel conversion helpers |
| `tools/interactive.py` | Guest lifecycle, assisted startup, controls and browser server |
| `tools/rsp.py`, `tools/probe.py` | Remote protocol and diagnostic guest calls |

Only `nikon-z6-display` is registered. The Z6 machine initializes its own profile directly, without inheriting a Z7 machine class. Shared Nikon GPU/ISP code retains its attribution.

## CPU and memory profile

The execution model uses two Cortex-A15 CPUs and a GIC. MAIN begins at `0x10020000`; the profile declares 33,502,842 bytes and a 48 MHz timer. RAM windows are listed explicitly in `nikon-z6-profile.h` rather than supplied as one broad backing range.

The profile comments distinguish software-interface evidence from execution choices: Cortex-A15, CBAR, GIC revision and functional completion timing are model choices. They are not identified silicon specifications.

## Assisted startup

The controller starts QEMU paused, connects RSP and QMP, and invokes original guest functions to establish a usable menu or shooting session. The stationary-photo profile uses diagnostic no-lens, orientation and control inputs, and disables unsupported MVD scheduling in guest RAM.

`probe.call_fixture` saves the selected task's register context and scratch bytes, calls a guest function, follows scheduler migration on return and restores the saved context. Startup and input calls therefore change guest state; they are not passive observations. The default official firmware's instruction bytes are not patched by these calls.

## Image path

```text
Generated or locally supplied RGB image
    -> RGGB 12-bit samples in a local RAW file
    -> experimental RAW transfer / guest-selected buffers
    -> functional ISP / NV12 output
    -> guest graphics commands and UI composition
    -> LCD scanout
    -> QMP screenshot -> browser PNG
```

The photo-liveview profile uses 2,034 × 1,434 samples with a 4,080-byte stride. It tracks RAW batches, ISP batches, LCD observations and whether a processed buffer was scanned. The synthetic scene supplies image pixels; it does not draw a replacement camera menu over the browser display.

The browser receives QEMU screenshots. P6 screenshot pixels are converted to PNG using the Python standard library.

## Native grid

The LCD model handles the dedicated grid register plane at offsets `0x1600` through `0x1620`, with bounded, clipped repeated rectangles. This is separate from browser HTML. The controller preserves the original `0x102D` grid setting across guest recreation within its session.

The firmware-free tests exercise the actual grid renderer and enable-register readback. Original d9 grid display was also observed in the working baseline.

## Dial and mode input

The controller snapshots the original 48-byte report through `0x101B640C`, clears four signed movement fields and writes a signed detent at `+0x10` for the main dial or `+0x14` for the sub dial. It submits the report through `0x101B63E6`. The original firmware changes the shutter value; the controller does not directly write Tv setting `0x204`.

Mode selection calls `0x101D7F02` with DSID 0 and checks native readback at `0x136F`. The mapping is P=0, A=1, S=2, M=3. These interfaces are tied to the supported Z6 MAIN layout.

## Upstream integration

`qemu/prepare_source.py` copies the overlay and adds the machine to ARM Meson, Kconfig and the default device configuration. It also adjusts three upstream core files:

| File | Adjustment |
| --- | --- |
| `hw/intc/arm_gic.c` | CPU-less diagnostic reads use bank 0 rather than dereference a missing current CPU |
| `target/arm/helper.c` | Rebuild CPSR-dependent hflags when relevant M/E/IL state actually changes |
| `target/arm/tcg/op_helper.c` | Remove the duplicate unconditional rebuild and provide optional shadow recomputation |

The optional `Z6_VERIFY_CPSR_HFLAGS` path compares cached flags with a full recomputation and asserts equality. The source adjustments describe emulator behavior; the export validation is recorded separately in [testing](testing.md).
