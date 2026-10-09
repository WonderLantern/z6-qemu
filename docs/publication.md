# Source-only publication inventory

[Home](../README.md) · [Contributing](../CONTRIBUTING.md)

## Included files

The published repository contains the Z6 machine overlay, shared pixel modules, build/controller tools, synthetic tests, documentation and license notices. `publication-manifest.json` lists their SHA-256 hashes, excluding itself.

The original package was copied into a separate publication checkout. Git normalized text to LF; the manifest was then updated to match the committed source bytes. This did not change executable source content beyond line endings.

## Local material kept outside the export

The source package contains no Nikon firmware or extracted MAIN, physical-camera dumps, credentials, calibration, extracted font/icon assets, firmware screenshots or generated memory captures. Local preparation evidence and validation runtime directories were not copied into this repository.

The simulator can produce screenshots and diagnostic captures when supplied with firmware. The source implementation of those tools is included; their runtime outputs are not included.

## Repeat the inventory check

```sh
python tools/verify_release.py
```

The checker walks the source tree while excluding `.git`, `.local`, `.build`, `.venv` and `__pycache__`. It rejects symlinks, selected non-source asset suffixes, non-UTF-8 content and mismatched inventories or hashes.

It is an inventory checker, not a comprehensive credential scanner. The package preparation additionally reviewed file contents and ZIP metadata for credentials, private paths, embedded data and unrelated private branch material.

After an intentional source or documentation change, review the changed paths before updating the manifest:

```sh
git diff --name-only
python tools/verify_release.py --refresh
python tools/verify_release.py
```

A refreshed manifest records the current files; it does not itself approve them for publication. Check the staged paths as well as the working tree.

## Attribution and licensing

The overlay, tools, tests and documentation use GPL-2.0-or-later as described in [COPYING](../COPYING). QEMU retains its per-file notices and [upstream license notice](../LICENSES/QEMU-LICENSE.txt).

The shared Nikon implementation originated from [WonderLantern Z7 QEMU](https://github.com/WonderLantern/z7-qemu), authored by [R3tr0ooo](https://github.com/R3tr0ooo). The Z6 profile and interfaces were developed and validated separately. The acknowledgement and attribution are retained in the README and [NOTICE](../NOTICE.md).
