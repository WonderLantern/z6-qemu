# Local firmware input

[Home](../README.md) · [Build](build.md) · [Usage](usage.md)

## Accepted official input

The interactive controller checks the extracted MAIN payload before starting the guest.

| Field | Required value |
| --- | --- |
| Model / version | Nikon Z6 / C 3.80 |
| Length | 33,502,842 bytes |
| SHA-256 | `1e6348d58750e67372d0a8e363932c57ee9c04d0eb8f62803bcd19812df0d25c` |
| Load address / initial PC | `0x10020000` |

An upgrade container is not this payload. Obtain the compatible extracted input independently and keep it local. This repository contains no firmware, keys or extraction service, and the tools do not download Nikon firmware.

## Check and select a local file

On Linux:

```sh
wc -c /path/to/z6-c380-main.bin
sha256sum /path/to/z6-c380-main.bin
python tools/interactive.py --firmware /path/to/z6-c380-main.bin --profile menu
```

The controller resolves the path, checks its length and hash, and checks the selected hash again during guest boot.

| Error | Check |
| --- | --- |
| `Requires the extracted Z6 C 3.80 MAIN, not the upgrade package` | File length and whether the file is MAIN |
| `Modified MAIN requires --allow-modified-firmware` | File hash; the default accepts only the official payload above |
| `Firmware payload hash changed after selection` | Whether the selected file changed while the server was running |

## Local modified input

`--allow-modified-firmware` disables the official-hash requirement while retaining the length check and subsequent selected-file hash check. This flag does not validate the modified file's instruction layout or behavior. The documented export smoke test used the official payload.

## Files produced locally

Build manifests, synthetic inputs and session records are generated under ignored `.local/`; compiled output is under `.build/`. The guest display and diagnostics can contain assets or bytes from the supplied firmware. They are separate from the source-only publication inventory.
