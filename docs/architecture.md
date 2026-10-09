# Architecture

One machine, `nikon-z6-display`, is integrated into QEMU10.2.4. `nikon-z6.c` initializes the Z6 profile directly, without inheriting a Z7 machine class. Two Cortex-A15 CPUs, GIC, inferred RAM windows and selected EX MCU/TG/SDES/GPU/ISP/LCD interfaces are functional research models. CPU choice and peripheral timing are assumptions, rather than a complete hardware specification.

`nikon-z6-profile.h` owns Z6 memory and RAW geometry. Shared Nikon GPU/ISP modules execute a command subset and functional pixel conversion. Generated RGGB/u16 2034×1434 RAW, stride4080, enters guest-selected buffers; original firmware submits NV12 outputs and draws UI before LCD scanout. The synthetic image does not replace the menu with a mock interface.

The d9 grid uses a dedicated display register plane at offsets1600..1620 with bounded clipped repeated rectangles. The controller restores native102D across guest recreation.

Dial input snapshots the original48-byte report (101B640C), clears four signed movement fields, writes main+10 or sub+14 as ±1, and submits101B63E6. Original firmware changes Tv; the controller does not write Tv204 directly. Mode selection uses101D7F02 with DSID0 and verifies0/136F. DefaultM supports shutter adjustment in the no-lens profile.

Upstream core adjustments affect three files: CPU-less GIC debug reads choose bank0; CPSR hflags rebuilds are reduced to relevant changes; optional Z6_VERIFY_CPSR_HFLAGS shadow checks compare caches against full recomputation. These are source adjustments, not hardware validation.

Startup uses RSP calls to original firmware functions. The stationary profile disables unsupported MVD scheduling in guest RAM and uses diagnostic no-lens/control/calibration inputs. Default official firmware code is not patched. Real sensor calibration, physical CMOS timing, EXPEED algorithms, storage and unassisted boot remain outside the verified scope.
