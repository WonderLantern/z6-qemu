# Build and environment

[Home](../README.md) · [Firmware input](firmware.md) · [Usage](usage.md)

## Environment

The builder runs on Linux. On Windows, run it inside an explicitly selected WSL distribution. Python 3.12 or newer is required by the archive extraction API used here.

Install the compiler and libraries, then create a virtual environment from the repository root:

```sh
git clone https://github.com/WonderLantern/z6-qemu.git
cd z6-qemu
sudo apt-get update
sudo apt-get install build-essential ninja-build pkg-config python3-venv \
    libglib2.0-dev libpixman-1-dev zlib1g-dev libfdt-dev
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

NumPy and Pillow are used to generate image inputs and run input tests. The browser server and RSP transport use Python's standard library.

## Build the pinned upstream release

```sh
python tools/build.py --jobs 4
```

The builder downloads QEMU 10.2.4 from `https://download.qemu.org/qemu-10.2.4.tar.xz`. Before extraction it requires this SHA-256:

```text
821b545b92f165e57dddccac5077d76d4d436a226595b8813ad59306bbfd0746
```

It applies `qemu/prepare_source.py`, configures `arm-softmmu` with TCG, and builds `qemu-system-arm`. GTK, SDL, VNC and OpenGL are disabled; the browser controller obtains screenshots through QMP.

Default generated locations:

| Path | Contents |
| --- | --- |
| `.build/qemu-10.2.4/` | Extracted upstream source with the overlay applied |
| `.build/build/qemu-system-arm` | Compiled emulator |
| `.local/build-manifest.json` | Binary path/hash, overlay hashes, configuration and adjusted core-source hashes |

The manifest contains absolute local paths. Generate it on the computer where the emulator will run. Before each guest boot, the controller checks the binary and overlay hashes against this manifest.

## Offline archive and separate build cache

```sh
python tools/build.py --archive /path/to/qemu-10.2.4.tar.xz --jobs 4
python tools/build.py --work-dir /path/to/build-cache --jobs 4
```

The supplied archive must match the same pinned hash. `--jobs` accepts 1 through 64; its default is 4. The manifest remains in this repository's `.local/` even when the build cache is elsewhere.

## Windows and WSL paths

From PowerShell, enter your selected distribution:

```powershell
wsl -d <distribution-name>
```

Inside WSL, use Linux paths and quote paths containing spaces. For example, a file on drive D can be passed as `/mnt/d/your-folder/main.bin`. Both the builder and interactive launcher reject native Windows execution.

## Reported failures

| Message or symptom | Meaning and action |
| --- | --- |
| `Upstream QEMU archive SHA-256 mismatch` | The archive does not match the pinned release; obtain the matching original archive |
| `Requested archive does not exist` | Check the path supplied to `--archive` |
| `Unexpected ... source` during preparation | The expected upstream source fragment was absent; use the pinned QEMU version |
| `QEMU binary changed; rebuild first` | Run the builder to regenerate the binary manifest |
| `QEMU source changed; rebuild first` | Rebuild after changing the overlay |

See [testing](testing.md) for the clean-export build that was actually run.
