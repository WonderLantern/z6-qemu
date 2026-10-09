# Local firmware input

Only an independently obtained extracted Nikon Z6 C3.80 MAIN is supported:

- Length: 33,502,842 bytes.
- SHA256: `1e6348d58750e67372d0a8e363932c57ee9c04d0eb8f62803bcd19812df0d25c`.
- Load address and initial PC: `0x10020000`.

Pass `--firmware /absolute/path/to/main.bin`. The upgrade container, another model or another version cannot substitute. Length/hash checks run before boot. No keys, extraction service or Nikon firmware download is provided.

`--allow-modified-firmware` permits a same-length local research MAIN, without a layout/compatibility guarantee. Keep firmware, dumps, logs and camera screenshots local. Generated files belong in ignored `.local/`; compiled output belongs in `.build/`.
