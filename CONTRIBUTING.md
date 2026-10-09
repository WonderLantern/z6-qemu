# Contributing

## Reproduce before changing the model

Include the commit, launch command, selected profile and exact input sequence. Distinguish a synthetic test result, guest readback and visual observation. The supported firmware input is described in [firmware setup](docs/firmware.md).

For pixel or register changes, prefer a synthetic input or firmware-free test that demonstrates the behavior. Existing entry points are:

```sh
sh tests/run.sh
python tests/test_irq99.py --qemu .build/build/qemu-system-arm
python tools/verify_release.py
```

The second command requires a built emulator. See [testing](docs/testing.md) for what each check covers.

## Source and build changes

Keep Z6-specific geometry and memory choices in the Z6 profile. Shared GPU/ISP changes also affect their functional tests. After changing the overlay, rebuild before launching the guest so the build-manifest hashes match.

Review changed paths before refreshing the publication manifest. Preserve license notices and upstream attribution.

## Public reports and attachments

Use synthetic cases and your own source code. Do not attach Nikon firmware, camera dumps, calibration, extracted fonts/icons, guest-memory captures or proprietary screenshots. Local session files can also contain absolute paths; summarize the relevant observation instead.

[Architecture](docs/architecture.md) · [Debugging](docs/debugging.md) · [Publication inventory](docs/publication.md)
