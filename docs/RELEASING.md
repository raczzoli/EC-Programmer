# Preparing a release

The source repository intentionally excludes `release/`, local SDK copies,
build directories, vendor applications, target firmware images, and EC reads.

1. Run `python -m unittest discover -s tests`.
2. Install `requirements-release.txt` and build the GUI from
   `EC-Programmer.spec` in a clean Python environment.
3. Build UF2 files separately for `pico`, `pico_w`, `pico2`, `pico2_w`,
   `waveshare_rp2040_zero`, `waveshare_rp2350_zero`,
   `waveshare_rp2350_usb_a`, `seeed_xiao_rp2040`, and `seeed_xiao_rp2350`.
4. Stage only the Windows EXE and license notices under `release/app/`, the UF2
   files under `release/pico-firmwares/`, and `README.txt` plus
   `SHA256SUMS.txt` at the release root.
5. Check the EXE opens, inspect each UF2 with `picotool info -a`, and verify
   the firmware answers `HELLO` on any board available for physical testing.
   Label every other board build as untested on hardware.
6. Review `git status --short` and the staged file list before pushing.
7. Zip the contents of `release/` with `app/` and `pico-firmwares/` at the
   archive root. Upload that ZIP as a GitHub Release asset. Do not commit
   `release/`.

Never distribute EC reads, laptop BIOS/EC images, driver installers, or
proprietary programming software as part of this project.
