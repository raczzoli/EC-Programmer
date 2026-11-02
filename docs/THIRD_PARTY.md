# Source attribution

- The ITE DBGR register and SPI follow-mode sequences in `app/ec.py` and the
  algorithms in `firmware/ite_flash.c` and entry waveform in
  `firmware/ite_dbgr.c` were adapted from the Chromium OS EC
  `iteflash` implementation. Copyright The Chromium OS Authors. Its source
  and BSD-style license are available at
  [Chromium OS EC iteflash](https://chromium.googlesource.com/chromiumos/platform/ec/+/main/util/iteflash.cc)
  and [Chromium OS EC license](https://chromium.googlesource.com/chromiumos/platform/ec/+/main/LICENSE).
  A copy of the BSD license is included at
  [Chromium-OS-EC-BSD.txt](licenses/Chromium-OS-EC-BSD.txt).
- The DBGR entry pattern was also informed by
  [JohnDoe150489's I2C-Pico-USB-ITE-EC-prog](https://github.com/JohnDoe150489/I2C-Pico-USB-ITE-EC-prog),
  Copyright 2026 JohnDoe150489, MIT license. No GPIO or USB implementation
  from that fork is bundled here.
- That fork derives from
  [Daniel Quadros's I2C-Pico-USB](https://github.com/dquadros/I2C-Pico-USB).
  This project does not bundle its USB transport or firmware.
- ENE EDI register access and page erase/program/read sequences in
  `firmware/ene_edi.c` and `app/ene.py` were adapted from
  [flashrom edi.c](https://github.com/flashrom/flashrom/blob/main/edi.c) by
  Paul Kocialkowski, GPL-2.0-or-later. The KB9052B/D HWVERSION and EDIID
  pairs were published by [Jack O'Neo in his flashrom extension notes](https://eletronicabr.com/forums/topic/111881-ler-e-gravar-kbc-ene-kb90xx-com-o-gravador-ch341a-usando-flashrom-no-mint-linux/).

The Raspberry Pi Pico SDK, Arm toolchain, and local build caches are not
included in the source repository. UF2 binaries link Pico SDK and TinyUSB code;
the candidate builder includes their license texts under
`pico-firmwares/licenses/`. The packaged GUI
contains PySide6/Qt and PySerial. They retain their own licenses: Qt for
Python is offered under LGPLv3/GPLv3 or commercial terms, and PySerial 3.5
is BSD-3-Clause. The source repository and Windows release include the
applicable [LGPLv3](licenses/LGPL-3.0.txt),
[GPLv3](licenses/GPL-3.0.txt), and
[PySerial BSD](licenses/PySerial-BSD.txt) texts. Review the bundled Qt
component notices when publishing a new build.
