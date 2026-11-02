# Preparing a release

The source repository intentionally excludes `release/`, local SDK copies,
build directories, vendor applications, target firmware images, and EC reads.

## Candidate builds

Set the version in `VERSION`. Install `requirements-release.txt` and
`requirements-test.txt`. Provide Pico SDK **2.3.1** (with submodules), CMake, Ninja
and an Arm GNU toolchain. The locally validated toolchain is **14.2 rel1**.

Run `python devtools/build_release.py --sdk C:/path/to/pico-sdk`. Optional
`--toolchain` and `--picotool` arguments accept an Arm toolchain root and a
directory containing `picotoolConfig.cmake`. Otherwise tools must be discoverable
by CMake/PATH. Firmware build directories are reused for incremental compilation.

The script runs tests before building and stages a versioned candidate under
`release-candidate/`. A source-content identifier is embedded in the GUI and
every UF2 (`INFO` also reports the board). The manifest records hashes, dependency
versions and pending hardware validation. The source hash is a traceability aid,
not a claim of byte-identical builds across operating systems/toolchains.

The existing release is never overwritten. Before promoting a candidate, check
on a physical ITE target: connect, two matching reads, write and full verify,
then boot the target with the programmer detached. Verify recovery after a normal
disconnect, and retain the previous UF2/EXE for rollback. Other board profiles
remain compile-tested unless physically exercised. Do not interrupt a real write
just to exercise error handling; simulated tests cover that case.

## Publishing a tested candidate

1. Run `python -m unittest discover -s tests` (includes native C regression tests).
2. Install `requirements-release.txt` and build the GUI from
   `EC-Programmer.spec` in a clean Python environment.
3. Build UF2 files separately for `pico`, `pico_w`, `pico2`, `pico2_w`,
   `waveshare_rp2040_zero`, `waveshare_rp2350_zero`,
   `waveshare_rp2350_usb_a`, `seeed_xiao_rp2040`, and `seeed_xiao_rp2350`.
4. Stage only the Windows EXE and GPL v2 license under `release/app/`, the
   dependency notices and license texts under `release/app/licenses/`, the UF2
   files under `release/pico-firmwares/`, and `README.txt` plus
   `SHA256SUMS.txt` at the release root.
5. Check the EXE opens, confirm all source files carry
   `SPDX-License-Identifier: GPL-2.0-or-later`, inspect each UF2 with
   `picotool info -a`, and verify
   the firmware answers `HELLO` on any board available for physical testing.
   Label every other board build as untested on hardware.
6. Review `git status --short` and the staged file list before pushing.
7. Zip the contents of `release/` with `app/` and `pico-firmwares/` at the
   archive root. Upload that ZIP as a GitHub Release asset. Do not commit
   `release/`.

Never distribute EC reads, laptop BIOS/EC images, driver installers, or
proprietary programming software as part of this project.
