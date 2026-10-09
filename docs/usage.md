# Usage

Shooting: `--profile shooting --photo-liveview`. Menu only: `--profile menu` without live view. Open the server's printed127.0.0.1 address.

MENU=M; playback=P; i=I; arrows/Enter; Escape=left/back; Delete=delete. Main wheel=`[`/`]`, sub wheel=`{`/`}`. Buttons deliver one detent; wheel areas accept scrolling. Held-key repeats are ignored. DefaultM adjusts shutter using the main dial.

P/S/A/M buttons select original mode assets. The selection indicator reflects the native selection; the firmware LCD can show a different effective mode. Current no-lens S still shows A and does not adjust Tv. UseM; this limitation is not bypassed with direct Tv writes.

Pause/resume retains the guest; restart and menu/shooting start recreate it. Mode/grid are re-applied within the current server session, not saved as camera settings. Ignored `.local/sessions/` contains manifests, logs and local screenshots that may include proprietary material; do not publish it.

`--isp-disable-cache` recomputes output; `--one-insn-per-tb` is slower diagnostic translation; `Z6_TRACE_START_ERRORS=1` enables bounded original-function traces. See `python tools/interactive.py --help` for all options.
