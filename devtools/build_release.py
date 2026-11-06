# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Build the current release in release/. No USB devices are accessed."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BOARDS = {
    "pico": "Pico-RP2040.uf2",
    "pico_w": "Pico-W-RP2040.uf2",
    "pico2": "Pico-2-RP2350.uf2",
    "pico2_w": "Pico-2-W-RP2350.uf2",
    "waveshare_rp2040_zero": "Waveshare-RP2040-Zero.uf2",
    "waveshare_rp2350_tiny": "Waveshare-RP2350-Tiny.uf2",
    "waveshare_rp2350_zero": "Waveshare-RP2350-Zero.uf2",
    "waveshare_rp2350_usb_a": "Waveshare-RP2350-USB-A.uf2",
    "seeed_xiao_rp2040": "Seeed-XIAO-RP2040.uf2",
    "seeed_xiao_rp2350": "Seeed-XIAO-RP2350.uf2",
}


def source_identity():
    files = [ROOT / "VERSION", ROOT / "EC-Programmer.spec", ROOT / "run_gui.py",
             ROOT / "requirements-release.txt"]
    for folder in ("app", "firmware", "devtools", "tests"):
        files += [p for p in (ROOT / folder).rglob("*") if p.is_file()
                  and not any(part.startswith("build") or part == "__pycache__"
                              for part in p.relative_to(ROOT / folder).parts[:-1])
                  and p.suffix in (".py", ".c", ".h", ".in", ".pio", ".txt", ".png", ".json")]
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        data = path.read_bytes()
        digest.update(data if path.suffix == ".png" else data.replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return {"version": (ROOT / "VERSION").read_text().strip(),
            "build_id": digest.hexdigest()[:12], "source_sha256": digest.hexdigest(),
            "hardware_validation": "pending"}


def run(args, **kwargs):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True, **kwargs)


def executable(name):
    local = Path(sys.executable).parent / (name + (".exe" if os.name == "nt" else ""))
    return str(local) if local.exists() else shutil.which(name) or name


def check_uf2(path, board, build_id):
    data = path.read_bytes()
    if not data or len(data) % 512:
        raise ValueError(f"Invalid UF2 size: {path}")
    families, payload = set(), bytearray()
    for offset in range(0, len(data), 512):
        first, second, flags, address, size, index, count, family = struct.unpack_from("<8I", data, offset)
        if (first, second) != (0x0A324655, 0x9E5D5157) or size > 476:
            raise ValueError(f"Invalid UF2 header: {path}")
        if struct.unpack_from("<I", data, offset + 508)[0] != 0x0AB16F30 or not flags & 0x2000:
            raise ValueError(f"Invalid UF2 family/footer: {path}")
        families.add(family)
        payload.extend(data[offset+32:offset+32+size])
    rp2350 = "2350" in board or board.startswith("pico2")
    expected = {0xE48BFF57, 0xE48BFF59} if rp2350 else {0xE48BFF56}
    if families != expected or board.encode() + b"\0" not in payload or build_id.encode() not in payload:
        raise ValueError(f"UF2 board/family/build mismatch: {path}")


def build_firmware(board, sdk, identity, output, toolchain=None, picotool=None):
    build = ROOT / "firmware" / ("build-" + board.replace("_", "-"))
    args = [executable("cmake"), "-S", "firmware", "-B", build, "-G", "Ninja",
            f"-DPICO_SDK_PATH={sdk.as_posix()}", f"-DPICO_BOARD={board}",
            f"-DEC_BUILD_ID={identity['build_id']}", "-DCMAKE_BUILD_TYPE=Release",
            f"-DCMAKE_MAKE_PROGRAM={executable('ninja')}"]
    if toolchain:
        args.append(f"-DPICO_TOOLCHAIN_PATH={Path(toolchain).resolve().as_posix()}")
    if picotool:
        args.append(f"-Dpicotool_DIR={Path(picotool).resolve().as_posix()}")
    run(args)
    run([executable("cmake"), "--build", build, "--parallel", "4"])
    source = build / "pico_ec_probe.uf2"
    check_uf2(source, board, identity["build_id"])
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output / BOARDS[board])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", choices=["all", *BOARDS], default="all")
    parser.add_argument("--sdk", type=Path, default=os.environ.get("PICO_SDK_PATH", ROOT / "vendor/pico-sdk"))
    parser.add_argument("--toolchain", help="Arm GNU toolchain root, if not on PATH")
    parser.add_argument("--picotool", help="Directory containing picotoolConfig.cmake")
    parser.add_argument("--firmware-only", action="store_true")
    args = parser.parse_args()
    if not args.firmware_only and os.name != "nt":
        parser.error("Build the Windows GUI on Windows, or use --firmware-only")
    if not (args.sdk / "external/pico_sdk_import.cmake").is_file():
        parser.error("Pico SDK missing; provide --sdk or PICO_SDK_PATH")
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    identity = source_identity()
    output = ROOT / "release"
    output.mkdir(parents=True, exist_ok=True)
    print(f"Release: {output}", flush=True)
    boards = list(BOARDS) if args.board == "all" else [args.board]
    for board in boards:
        print(f"Building {board}", flush=True)
        build_firmware(board, args.sdk.resolve(), identity, output / "pico-firmwares", args.toolchain, args.picotool)
    firmware_licenses = output / "pico-firmwares/licenses"
    firmware_licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", output / "pico-firmwares/LICENSE.txt")
    shutil.copy2(ROOT / "docs/THIRD_PARTY.md", output / "pico-firmwares/THIRD_PARTY.txt")
    shutil.copy2(ROOT / "docs/licenses/Chromium-OS-EC-BSD.txt", firmware_licenses)
    shutil.copy2(args.sdk / "LICENSE.TXT", firmware_licenses / "Raspberry-Pi-Pico-SDK.txt")
    shutil.copy2(args.sdk / "lib/tinyusb/LICENSE", firmware_licenses / "TinyUSB-MIT.txt")
    if not args.firmware_only:
        metadata = ROOT / "build/package_metadata/build-info.json"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps(identity, indent=2) + "\n")
        env = dict(os.environ, EC_BUILD_INFO_FILE=str(metadata))
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", output / "app",
             "EC-Programmer.spec"], env=env)
        run([output / "app/EC-Programmer.exe", "--smoke-test"],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), timeout=60)
        shutil.copy2(ROOT / "LICENSE", output / "app/LICENSE.txt")
        shutil.copy2(ROOT / "docs/THIRD_PARTY.md", output / "app/THIRD_PARTY.txt")
        shutil.copytree(ROOT / "docs/licenses", output / "app/licenses", dirs_exist_ok=True)
    if source_identity()["build_id"] != identity["build_id"]:
        raise RuntimeError("Source changed during the build; rebuild the release")
    identity["boards"] = [board for board, filename in BOARDS.items()
                          if (output / "pico-firmwares" / filename).exists()]
    identity["python"] = sys.version.split()[0]
    identity["packages"] = {name: importlib.metadata.version(name)
                            for name in ("PySide6", "pyserial", "pyinstaller")}
    (output / "build-info.json").write_text(json.dumps(identity, indent=2) + "\n")
    (output / "README.txt").write_text(
        f"EC Programmer {identity['version']} / {identity['build_id']}\n\n"
        "Automated tests passed. See docs/ENE.md for hardware validation status.\n"
        "app/ contains the Windows GUI; pico-firmwares/ contains board-specific UF2 files.\n"
        "Install only the UF2 matching your board. Pico 2 H uses Pico-2-RP2350.uf2.\n"
        "Default ITE pins: GP7 SDA, GP6 SCL, common GND. Default timing is unchanged.\n"
        "Read saves after completion. Write erases, programs and verifies; no automatic backup.\n"
        "Size: numeric/manual for ITE (64/128/192/256 KiB); automatic and locked for ENE.\n"
        "ENE is experimental. GP4 DO, GP5 CS, GP6 CLK, GP7 DI, common GND; confirm target strap/pins.\n"
        "ENE models: KB9012QF, KB9022Q, KB9028Q, KB9052QD (128 KiB).\n"
        "Source and instructions: https://github.com/raczzoli/EC-Programmer\n"
    )
    entries = []
    release_files = [output / "README.txt", output / "build-info.json"]
    for folder in ("app", "pico-firmwares"):
        release_files.extend((output / folder).rglob("*"))
    for path in sorted(release_files):
        if path.is_file():
            entries.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS.txt").write_text("\n".join(entries) + "\n")
    print(f"Release ready: {output}", flush=True)


if __name__ == "__main__":
    main()
