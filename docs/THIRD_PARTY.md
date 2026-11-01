# Source attribution

- The ITE DBGR register and SPI follow-mode sequences in `app/ec.py` and the
  entry waveform in `firmware/main.c` were adapted from the Chromium OS EC
  `iteflash` implementation. Copyright The Chromium OS Authors. Its source
  and BSD-style license are available at
  [Chromium OS EC iteflash](https://chromium.googlesource.com/chromiumos/platform/ec/+/main/util/iteflash.cc)
  and [Chromium OS EC license](https://chromium.googlesource.com/chromiumos/platform/ec/+/main/LICENSE).
- The DBGR entry pattern was also informed by
  [JohnDoe150489's I2C-Pico-USB-ITE-EC-prog](https://github.com/JohnDoe150489/I2C-Pico-USB-ITE-EC-prog),
  Copyright 2026 JohnDoe150489, MIT license. No GPIO or USB implementation
  from that fork is bundled here.
- That fork derives from
  [Daniel Quadros's I2C-Pico-USB](https://github.com/dquadros/I2C-Pico-USB).
  This project does not bundle its USB transport or firmware.

The Raspberry Pi Pico SDK, Arm toolchain, and local build caches are not
included in the source repository or release artifacts. The packaged GUI
contains PySide6, PySerial, and their respective
redistributable dependencies; review their bundled license notices when
publishing a new build.
