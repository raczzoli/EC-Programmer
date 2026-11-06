# Building and publishing a release

Set `VERSION` to the release version. Install `requirements-release.txt` and
`requirements-test.txt`, Pico SDK 2.3.1 with submodules, CMake, Ninja and an Arm
GNU toolchain (14.2 rel1 is used locally).

Run `python devtools/build_release.py --sdk C:/path/to/pico-sdk`.
Optional `--toolchain` and `--picotool` accept toolchain/configuration directories.
The builder runs the tests, compiles all ten board profiles, validates the UF2
board/family/build metadata and checks that the packaged GUI starts.

Output is updated directly in **release/app/** and **release/pico-firmwares/**.
No candidate folders are created. Close the GUI before replacing its executable.
The build manifest records the source ID and dependencies; it is not a claim of
physical validation for every board or EC. Describe actual hardware results in
release notes separately from automated tests.

Before publishing:

1. Review the source diff and run the builder successfully.
2. Commit source, tests, docs and VERSION; push the intended branch.
3. Create a version tag on that commit.
4. Package only app/, pico-firmwares/, README.txt, build-info.json and the hash
   manifest. Do not include older ZIPs or release notes from earlier builds.
5. Publish a normal GitHub Release and upload the package and checksum file.

The repository excludes release artifacts, local SDKs, research downloads and
hardware-specific repair data. Never distribute customer dumps, laptop BIOS/EC
images, driver installers or proprietary programming software with this project.
