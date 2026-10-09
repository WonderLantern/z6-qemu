# Running and controlling the guest

[Home](../README.md) · [Build](build.md) · [Debugging](debugging.md)

Run the following commands from the repository root, with the virtual environment active and the emulator already built.

## Shooting view

```sh
python tools/make_cmos.py
python tools/interactive.py --firmware /path/to/z6-c380-main.bin \
    --profile shooting --photo-liveview --port 8787
```

Open `http://127.0.0.1:8787/`. The default shooting mode is M. The controller provides startup assistance through original firmware functions; the displayed camera menus and shooting UI are rendered by the supplied firmware.

## Menu session

```sh
python tools/interactive.py --firmware /path/to/z6-c380-main.bin \
    --profile menu --port 8787
```

The menu profile does not require generated RAW inputs when `--photo-liveview` and `--raw-source` are omitted.

## Controls

| Browser control | Keyboard |
| --- | --- |
| MENU | `M` |
| Playback | `P` |
| i menu | `I` |
| Direction pad | Arrow keys |
| OK | Enter |
| Left / back | Escape |
| Delete | Delete |
| Main dial | `[` / `]` |
| Sub dial | `{` / `}` |

The main and sub dial areas also accept mouse scrolling. Each dial button sends one signed detent through the original firmware report interface. Held-key repeats are ignored. P/S/A/M buttons use the original mode-selection interface.

M-mode main-dial input changed the firmware LCD from 1/8000 to 1/6400 in the independent export smoke test. The working baseline also reached 1/5000 and restored earlier values with reverse input.

## Session controls

Pause and resume retain the current guest. Restart, Shooting start and Menu start recreate it. Returning from menus to continuous live view uses Shooting start in the documented baseline.

Within the same server session, the grid setting is restored during guest recreation. The selected exposure mode is remembered and reapplied after shooting startup succeeds; menu-only startup does not reapply it. Shutter settings are not retained across recreation. The current no-lens profile selects S but still displays A and does not adjust Tv; use M for the documented shutter test.

## Replace the synthetic scene

```sh
python tools/make_cmos.py --image /path/to/your/image.jpg
```

The generator applies image orientation, converts to RGB, creates three Bayer layouts and writes a new active configuration under `.local/cmos/`. Restart the guest after generating the replacement so its input is reloaded.

| Layout | Dimensions | Row stride | Storage |
| --- | --- | --- | --- |
| unpacked | 640 × 480 | 1,280 bytes | Little-endian uint16 |
| ingress | 1,380 × 918 | 2,080 bytes | Two 12-bit samples in three bytes |
| native0 | 2,034 × 1,434 | 4,080 bytes | Little-endian uint16 |

All use RGGB, black level 64 and white level 4095. Packing is checked by decoding and comparing samples before the input is activated. These are emulator input layouts.

`--photo-liveview` uses the active native0 input. A different `--raw-source` is rejected in that mode; use the generator to replace the scene.

## Implemented launch options

| Option | Behavior in the controller |
| --- | --- |
| `--port N` | Change the local HTTP port; default 8787 |
| `--build-manifest PATH` | Select a build manifest |
| `--no-current` | Leave the primary session pointer unchanged |
| `--one-insn-per-tb` | Use slower single-instruction translation blocks for diagnostics |
| `--isp-disable-cache` | Recompute ISP output rather than reuse cached pixels |

Use `python tools/interactive.py --help` for the complete parser. Diagnostic switches are implementations, not additional device validation results.

The HTTP server, GDB endpoint and QMP endpoint bind to `127.0.0.1`. Stop the launcher with Ctrl+C; its shutdown path closes the guest.
