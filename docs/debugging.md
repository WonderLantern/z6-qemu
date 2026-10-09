# Debugging and local evidence

[Usage](usage.md) 路 [Architecture](architecture.md) 路 [Testing](testing.md)

## Start with the current session

The controller creates `.local/sessions/<session-id>/`. Unless `--no-current` is set, `.local/sessions/current.json` records the server URL, process ID, session directory, selected profile and build information.

The local browser provides status and the latest display. For a default-port session, the same read-only endpoints can be inspected with:

```sh
curl http://127.0.0.1:8787/api/status
curl http://127.0.0.1:8787/api/frame -o .local/frame.png
```

`/api/frame` returns HTTP 503 until a frame is available. `/api/status` is a snapshot rather than a continuous sensor monitor. An accepted UI request is queued; it does not establish that the guest operation succeeded.

## Boot and build checks

Confirm the firmware length/hash first, then run the source inventory check:

```sh
python tools/verify_release.py
```

The controller separately checks the built binary and overlay source hashes from `.local/build-manifest.json` before boot. Rebuild when it reports a changed binary or source. Changing documentation does not invalidate the build's overlay source hashes.

## RSP and diagnostic calls

Only the controller worker owns its QMP/RSP connections. HTTP requests enqueue named actions. The QEMU command recorded by the controller contains the selected local endpoints and launch arguments.

`tools/rsp.py` implements the transport; `tools/probe.py` provides calls into the paused guest. Its call fixture requires a 68-byte ARM register report and restores saved scratch memory and registers after return. It records call and return CPUs because a guest function can return on a different scheduled CPU.

Service interception and observation breakpoints cannot overlap. Repeated breakpoints are stepped over before reinstallation. These details matter when interpreting a trace as a diagnostic interaction with the guest.

## Capture observations

`tools/capture_diagnostics.py` reads capture stage, readiness, error flags, active inhibit IDs, parameter initialization state and sensor-resource version from the paused guest.

An AutoOperation reply acknowledges a request, including a failed capture start. To establish the image path, examine RAW transfer evidence, ISP processing and processed-buffer scanout, then inspect the displayed frame. The diagnostics explicitly label their evidence as experimental and separate visual review.

## Implemented trace controls

`Z6_TRACE_START_ERRORS=1` enables selected startup-call traces. `Z6_TRACE_RETURN_ERRORS=1` enables selected return/error traces. Both are read by the launcher and populate the diagnostic observation points.

```sh
Z6_TRACE_START_ERRORS=1 python tools/interactive.py \
    --firmware /path/to/z6-c380-main.bin --profile shooting --photo-liveview
```

`--one-insn-per-tb` selects slower diagnostic translation, and `--isp-disable-cache` recomputes pixels for comparison. These switches change the diagnostic run; record them when comparing results.

## Keep records scoped

For a reproducible issue, record the repository commit, Python version, build-manifest hashes, firmware hash, command, profile, input manifest and exact control sequence. Report whether the result concerns a host test, a guest readback or the displayed image.

Session records, memory observations and screenshots can include local paths or proprietary material from the supplied firmware. Public reports can use synthetic reproductions and concise observations without attaching those local artifacts.
