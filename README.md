# EC Programmer

A Windows application and Raspberry Pi Pico firmware for **ITE and ENE embedded controllers**.
Read EC firmware, write an image with automatic erase and verification, or erase the flash.

## Manufacturers and families

The names below match the **Manufacturer** and **Model / Family** selectors in the GUI.

| Manufacturer | Model / family | Operations |
| --- | --- | --- |
| ITE | IT51xx | Identification |
| ITE | IT55xx | Identification |
| ITE | IT8xxx | Read, Write, Erase |
| ENE | KB9012QF | Read, Write, Erase — experimental |
| ENE | KB9022Q | Read, Write, Erase — experimental |
| ENE | KB9028Q | Read, Write, Erase — experimental |
| ENE | KB9052QD | Read, Write, Erase — experimental |

## Download and setup

1. Download the application and firmware from [GitHub Releases](https://github.com/raczzoli/EC-Programmer/releases).
2. Put your Pico into **BOOTSEL** mode and copy the UF2 for your board to its USB drive.
3. Connect the Pico through its USB data port and run **EC-Programmer.exe** from `app/`.

Firmware files are in `pico-firmwares/`. Builds are available for:

- **Raspberry Pi:** Pico, Pico W, Pico 2 and Pico 2 W. Header-equipped variants use the corresponding base-board firmware.
- **Waveshare:** RP2040-Zero, RP2350-Zero, RP2350-Tiny and RP2350-USB-A.
- **Seeed Studio:** XIAO RP2040 and XIAO RP2350.

See the [firmware map](docs/BOARD_FIRMWARES.md) for filenames and GPIO mappings.
The firmware uses USB CDC with the standard Windows serial driver. On the
Waveshare RP2350-USB-A, connect the PC to **USB-C**.

## Wiring

### ITE

| Pico | EC board |
| --- | --- |
| GP7 | SDA |
| GP6 | SCL |
| GND | GND |

SDA and SCL GPIOs can be changed in the GUI. Use the target board's schematic
to identify its EC programming signals. The interface uses 3.3 V logic;
power the EC from its board and connect a common ground.

![Waveshare RP2350-USB-A: GND on the left, GP6 for EC SCL and GP7 for EC SDA on the right](docs/images/waveshare-rp2350-usb-a-wiring.png)

### ENE

Select the exact ENE model in **Model / Family**. The GUI shows its physical
EC pin numbers below the selectors. The current catalog covers **LQFP-128**:

| Pico | EC pin (KB9012QF, KB9022Q, KB9028Q, KB9052QD) |
| --- | --- |
| GP4 | 62 |
| GP5 | 59 |
| GP6 | 60 |
| GP7 | 61 |
| GND | Board ground |

Connect **EC pin 42 (KSO3) to board ground before powering the target**.
Wire with all power disconnected, use common ground and power the EC from
its board. Numbers refer to the chip, **not the keyboard connector**.
See [pinout sources and package scope](docs/ENE_PINOUTS.md) and
[ENE protocol notes](docs/ENE.md).

## Using the application

1. Select the **COM port**, **Manufacturer** and **Model / Family**.
2. For ITE, set **SDA**, **SCL** and the numeric **Size** field. For ENE, Size is filled automatically and locked for the selected model.
3. Click **Connect to EC** and follow any power-cycle prompt.
4. Choose an operation:

   - **Read:** reads the flash, then opens a dialog to save the file.
   - **Write (Erase + Write):** opens an image file, erases the flash, writes the image and verifies every byte.
   - **Erase:** erases the flash.

The progress bar is **green for Read/Verify**, **red for Erase**, and
**orange for Programming**. Write changes color as each stage starts. Use **Read** first if
you want to keep a backup, and **Save log** to export the session log.

## Testing and feedback

Tested another EC or board? Share your result in [GitHub Issues](https://github.com/raczzoli/EC-Programmer/issues).
Include the EC marking, laptop or board model, Pico model, application and
firmware versions, operation performed and its log. Successful tests and
problem reports help expand compatibility.

## Build from source

Python 3.10+ on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
.\.venv\Scripts\python.exe -m app
```

For a complete package, install `requirements-release.txt` and
`requirements-test.txt`, the Raspberry Pi Pico SDK with submodules, CMake,
Ninja and the Arm GNU toolchain, then run:

```powershell
.\.venv\Scripts\python.exe devtools/build_release.py --sdk C:/path/to/pico-sdk
```

The builder runs the automated tests and creates the Windows application,
board-specific UF2 files and SHA-256 manifests in
`release/`.
See [build and release instructions](docs/RELEASING.md) and the
[code map](docs/ARCHITECTURE.md) for development details.

## License and credits

Project source is licensed under **GNU GPL v2 or later** (`GPL-2.0-or-later`);
see [LICENSE](LICENSE).

ITE implementation draws on Chromium OS EC `iteflash` and the entry waveform
from `I2C-Pico-USB-ITE-EC-prog`. ENE implementation draws on flashrom and
Jack O'Neo's extension with contributor reports. See [source attribution](docs/THIRD_PARTY.md).
Bundled libraries retain their own licenses; Qt/PySide6 notices are included
with the Windows application.

Software by **R89 Repairs** | [www.r89-repairs.ro](https://www.r89-repairs.ro)
