# EC Programmer

A Windows GUI and Raspberry Pi Pico firmware for ITE DBGR and ENE EDI access.
The application identifies an EC, reads its flash, and enables erase/write
only when the supported flash protocol has been identified.

## Current support

The manufacturer selector contains **ITE** and **ENE**. For ITE, the family selector contains
**IT51xx**, **IT55xx**, and **IT8xxx**. IT51xx and IT55xx are discovery entries;
their read/write protocols have not been implemented. IT8xxx supports DBGR
identification and page reads up to 256 KiB. Family selection alone does not
prove that a particular EC accepts this protocol or has that capacity.

For IT8xxx, Write and Erase support selected sizes of **64, 128, 192, and 256 KiB**
with two flash command sets recognized by flash ID: eFlash 8315 (`FF FF FE`,
1 KiB sector erase) and KGD (`C8` or `EF` first ID byte, 4 KiB sector erase).
CHIPVER selects legacy AAI, newer AAI, or KGD page program. The existing
legacy 8315 path has completed a physical erase, full image write, and
byte-for-byte verify on one EC. The newer AAI path has also completed one full
write and verify on hardware using 64-byte Pico blocks. Its 256-byte Pico block
optimization and the KGD path have automated tests but still need physical
validation. The application refuses destructive operations when the
flash command set cannot be identified. The selected size controls the range;
it is not a capacity measurement from the EC.

ENE currently has an **experimental KB90xx EDI** family entry. It accepts only the
published KB9052B/D EDI identification pairs (`B0/0B` or `D0/0B`) and a
128 KiB image. Read, page erase, page write, and full read-back verification
are implemented, but this path has **not yet been tested on a physical KB9052QD**.
Do not assume that the printed suffix alone proves its EDI identity.

## Download and run

The local `release/` directory is a release staging area and is excluded from
Git. Its `app/` folder contains the Windows EXE; `pico-firmwares/` contains
board-specific UF2 files. Download the GitHub Release, flash the UF2 matching
your board through BOOTSEL, connect its USB data port to Windows, and run the
EXE. The firmware uses USB CDC; Windows 10/11 normally supplies the serial
driver. Zadig/libusbK is not used by this build.

Board-specific UF2 files are compiled from the same source. The release has
builds for Raspberry Pi Pico, Pico W, Pico 2, Pico 2 W; Waveshare RP2040-Zero,
RP2350-Zero, RP2350-USB-A; and Seeed XIAO RP2040 and RP2350. Header-equipped
Pico variants use the UF2 of their corresponding base model. A compiled UF2
does not prove that a board or EC has been physically tested. Use the board's
USB **device** port; on the Waveshare RP2350-USB-A board this is USB-C, not
its USB-A host connector. See the [board firmware map](docs/BOARD_FIRMWARES.md)
for exact filenames and wiring notes.

## Wiring and use

### ITE wiring on Waveshare RP2350-USB-A

![Waveshare RP2350-USB-A: GND on the left, GP6 for EC SCL and GP7 for EC SDA on the right](docs/images/waveshare-rp2350-usb-a-wiring.png)

With the board oriented as shown, connect **GND** to the EC board ground,
**GP6** to EC SCL, and **GP7** to EC SDA. The photo marks GPIO numbers; the
target board's EC pins must be identified separately.

See [Wiring and operation](docs/HARDWARE.md). The Pico needs EC SDA, EC SCL,
and a shared ground. Identify the target board's actual EC programming pins
from its schematic or measured netlist. The GUI defaults to GP7 for SDA and
GP6 for SCL, but both are selectable. The EC side must use 3.3 V logic and
have pull-ups; Pico pins are open drain during the entry waveform.

Select the COM port, manufacturer, family, SDA and SCL pins, and **Size**
(64, 128, 192, or 256 KiB), then click **Connect to EC**. Read becomes
available after the EC connects and reads that many bytes from address 0.
Select the size for the physical EC. A recognized flash command set enables
Write and Erase for that selected size. **Read** opens a save dialog when it finishes.
**Write** asks for an image, erases the EC, programs it, and
verifies every byte. **Erase** only erases. There is no automatic backup before
Write; use Read first if you want one. If the EC cannot enter debug mode while
powered, the app arms the Pico and asks you to cycle the target's power.

### ENE KB9052QD EDI wiring

The ENE path uses SPI0 with fixed Pico GPIOs: **GP4 = EDI DO / KSI7**,
**GP5 = EDI CS / KSI4**, **GP6 = EDI CLK / KSI5**, and
**GP7 = EDI DI / KSI6**. Connect a common Pico/target **GND**; the ENE
EDI test input **KSO3** must also be held low as specified by the target
board's programming wiring. The EC must receive its normal 3.3 V power
from the target board. Identify the actual keyboard connector pins from
that board's schematic; the ITE SDA/SCL wiring does not apply to ENE.

In the GUI choose ENE / KB90xx EDI, connect, then read and save two dumps
before considering erase or write. The ENE path selects its documented
128 KiB range automatically. It does not use the ITE power-cycle waveform.

## Build from source

The ITE refactor is currently **0.3.0-dev**. New candidates go into
`release-candidate/<version>-<build-id>/`; the previous `release/` is preserved.
Candidates have automated regression coverage but still require physical ITE
validation before replacing the tested release. ENE support is unchanged.

Python 3.10+ on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
.\.venv\Scripts\python.exe -m app
```

Build a Windows EXE with:

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm EC-Programmer.spec
```

For UF2 builds, install the Raspberry Pi Pico SDK (including submodules),
CMake, Ninja, and the Arm GNU toolchain. Run, for example:

```powershell
cmake -S firmware -B firmware/build-pico -G Ninja -DPICO_SDK_PATH=C:/path/to/pico-sdk -DPICO_BOARD=pico
cmake --build firmware/build-pico
```

Replace `pico` with any board name in the
[firmware map](docs/BOARD_FIRMWARES.md); use a separate build directory for
each board.
The output is `pico_ec_probe.uf2`. See [release preparation](docs/RELEASING.md)
for the complete board list and staging checklist.

For the automated candidate build, install `requirements-release.txt` and
`requirements-test.txt`, then run:

```powershell
.\.venv\Scripts\python.exe devtools/build_release.py --sdk C:/path/to/pico-sdk
```

This runs host and native firmware tests, builds nine UF2 variants and the Windows
EXE, checks application startup, and writes SHA-256 manifests. It does not flash
hardware or publish anything. Use `--board pico2 --firmware-only` to build only
the Pico 2 / Pico 2 H candidate. See the [code map](docs/ARCHITECTURE.md) for module
boundaries and details of the regression tests.

## License and credits

Project source is licensed under the GNU General Public License, version 2
or any later version (`GPL-2.0-or-later`); see [LICENSE](LICENSE).
DBGR and SPI follow-mode sequences draw on Chromium OS EC `iteflash`;
the entry waveform is informed by
`I2C-Pico-USB-ITE-EC-prog`. See [source attribution](docs/THIRD_PARTY.md).
The ENE EDI register and flash sequence is adapted from flashrom `edi.c`
(GPL-2.0-or-later); KB9052B/D interface IDs are from Jack O'Neo's
flashrom extension.
Bundled libraries retain their own licenses. In particular, the Windows GUI
uses Qt/PySide6 components with LGPLv3/GPLv3 terms; the project source permits
GPLv3 use when those components require it.
No laptop BIOS, EC image, vendor application, or customer dump is distributed.
