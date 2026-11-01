# Firmware files by board

The local release has `app/` for the Windows GUI and `pico-firmwares/` for
board-specific UF2 files. Choose one UF2 for the exact board:

| UF2 | Board and Pico SDK profile |
| --- | --- |
| `Pico-RP2040.uf2` | Raspberry Pi Pico / Pico H (`pico`) |
| `Pico-W-RP2040.uf2` | Raspberry Pi Pico W / Pico WH (`pico_w`) |
| `Pico-2-RP2350.uf2` | Raspberry Pi Pico 2 / Pico 2 with headers (`pico2`) |
| `Pico-2-W-RP2350.uf2` | Raspberry Pi Pico 2 W / Pico 2 W with headers (`pico2_w`) |
| `Waveshare-RP2350-USB-A.uf2` | Waveshare RP2350-USB-A (`waveshare_rp2350_usb_a`) |
| `Waveshare-RP2040-Zero.uf2` | Waveshare RP2040-Zero (`waveshare_rp2040_zero`) |
| `Waveshare-RP2350-Zero.uf2` | Waveshare RP2350-Zero (`waveshare_rp2350_zero`) |
| `Seeed-XIAO-RP2040.uf2` | Seeed Studio XIAO RP2040 (`seeed_xiao_rp2040`) |
| `Seeed-XIAO-RP2350.uf2` | Seeed Studio XIAO RP2350 (`seeed_xiao_rp2350`) |

All nine variants compile and have UF2 metadata matching their Pico SDK board
profile, RP2040/RP2350 family, and USB CDC console feature. That validates
the generated files; it cannot establish electrical operation on untested
boards. The board used during EC protocol development was the Waveshare
RP2350-USB-A. These exact release UF2s have not been tested on all boards.

The firmware defaults to **GP7 = EC SDA** and **GP6 = EC SCL**, plus common
GND. Use GPIO numbers rather than a board's printed I2C labels. On Seeed
XIAO RP2040/RP2350, D5 is GP7 and D4 is GP6, so D5 goes to EC SDA and D4
to EC SCL with the defaults. The GUI permits another adjacent GPIO pair.

The header-equipped Raspberry Pi Pico variants differ physically in their
headers and debug connector, so they use the base board UF2. See
[Raspberry Pi Pico board documentation](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html).
