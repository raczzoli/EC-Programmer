# Experimental ENE EDI support

ENE uses a common SPI EDI register transport and a shared eFlash page engine.
The GUI lists documented physical models from [ENE_PINOUTS.md](ENE_PINOUTS.md);
compatible models share the protocol groups below.
All groups below are implemented and simulator-tested. KB9022Q identification
has succeeded on hardware; complete physical read/write validation is pending. Existing ITE algorithms are separate.

| Internal protocol group | Documented examples | HWVERSION / EDIID | Full range used by reference implementations |
| --- | --- | --- | --- |
| KB901x | KB9010, KB9012, KB9016, KB9018 | C3 / 04 | 128 KiB |
| KB902x | KB9022; KB9028 | B1 / 07; C0 / 07 | 128 KiB |
| KB9052 (B/D) | KB9052 interface variants B and D | B0 / 0B; D0 / 0B | 128 KiB |
| KB9542GF | upstream KB9542GF; community KB9542 revision | F0 / 07; A0 / 07 | 160 KiB |

The group names do not claim support for every possible matching model number.
The two ID bytes select a documented interface variant; they do not identify
the motherboard firmware, and an EDI response alone does not prove flash compatibility.
The community A0/07 signature is published as KB9542, without establishing
that all package suffixes are equivalent. It shares the KB9542GF GUI group
but retains its own entry behavior.

## Size and operations

**Size is filled automatically and disabled for the selected ENE model.** KB901x,
KB902x and KB9052 (B/D) use 128 KiB; KB9542GF uses the full 160 KiB range.
The GUI labels this as a family value, not a capacity measured from the chip.
The application rejects partial images. The internal KB9542GF engine retains
160 KiB support, but that model is not exposed without a verified pinout.
For ITE, the numeric Size field remains editable.

All supported variants use 128-byte pages and erase to **00**, not FF.
Read starts at zero and offers Save after completion. Write erases the full
family range, programs it, then verifies every byte. Erase only erases that
range. There is no automatic backup or separate erased-flash scan.
The host checks the family range and image length before destructive operations;
firmware rejects unaligned or out-of-range page commands.

## Session variants

The common engine uses EDI register read/write commands 30/40, eFlash registers
FEA8-FEAD and PXCFG FF14 bit 0 to hold the 8051 in reset. Flash commands are
03 (read), 20 (page erase), 80 (clear latch), 02 (latch byte), 70 (program page).
Entry runs SPI0 in mode 0 at 2 MHz, with a dummy read to activate EDI and
bounded retries while the EC firmware is still running.

Only **F0/07** uses the upstream hardware-tested WDTCFG FE80 = 48 sequence.
This value is not applied to A0/07 or the KB90xx groups. The upstream source
notes a different watchdog-disable value for KB9010; therefore EDIID alone
must not select a watchdog write. Other groups retain the base entry sequence.
CPU reset is confirmed before a session is accepted. Page operations check
that CPU reset and flash command enable remain asserted. Failures attempt
flash disable and session cleanup; close returns the GPIOs to inputs even
if the EC does not acknowledge CPU release. A physical reset may still be
needed after a communication failure.

## Firmware and wiring

Use the new matching UF2: the GUI requires capability **ENE_EDI_V2** and sends
`ENEOPEN KB901X`, `ENEOPEN KB902X`, `ENEOPEN KB9052`, or `ENEOPEN KB9542GF`.
The original bare `ENEOPEN` remains a KB9052-only command for old clients.
The reply remains `ENEOPEN HW=xx EDI=xx`; page command formats are unchanged.
An older UF2 is rejected before opening an ENE session. No ITE waveform or
SDA/SCL pin selection is used for ENE.

| Pico GPIO | EC signal |
| --- | --- |
| GP4 | EDI DO / MISO (KSI7 on the documented KB9012 interface) |
| GP5 | EDI CS (KSI4) |
| GP6 | EDI CLK (KSI5) |
| GP7 | EDI DI / MOSI (KSI6) |
| GND | Target ground |

Confirm the EC-side pins, programming-mode strap (for example KSO3), and
power rails from the target schematic. Package pin numbers and connector
positions are not universal. The target supplies its normal 3.3 V power;
Pico is the SPI transport. Not every Pico variant exposes all four GPIOs.

## Evidence and validation

- [flashrom ENE definitions](https://github.com/flashrom/flashrom/blob/0bc4b2ddb0f83e3829e8fad840ece804640c37f3/flashchips/ene.c)
  define KB9012 at 128 KiB and KB9542GF at 160 KiB, both with 128-byte pages
  and the same read/write/erase functions.
- [flashrom EDI implementation](https://github.com/flashrom/flashrom/blob/0bc4b2ddb0f83e3829e8fad840ece804640c37f3/edi.c)
  and [ENE register definitions](https://github.com/flashrom/flashrom/blob/0bc4b2ddb0f83e3829e8fad840ece804640c37f3/include/ene.h)
  supply the base engine, F0/07 identity and its watchdog handling.
- [Jack O'Neo's flashrom extension and contributor reports](https://eletronicabr.com/forums/topic/111881-ler-e-gravar-kbc-ene-kb90xx-com-o-gravador-ch341a-usando-flashrom-no-mint-linux/)
  supply the KB9010/16/18 grouping and KB9022/28, KB9052 B/D and KB9542 A0/07
  signatures. These reports are not a substitute for local hardware validation.
- [ENE KB9012 datasheet](https://www.eliptor.pl/pub/pdf/ene/KB9012.pdf)
  documents the EDI interface and the KB9012 signal mapping.

Native tests compile the production ENE C module against a register-level EC
simulator. They check all listed signatures, 64/128 KiB address crossings,
the final 160 KiB page, erase/program/read sequences, busy/ready framing,
wrong-family rejection, session loss, timeout and cleanup. Python tests cover
USB command construction, selected ranges, full verification, worker and GUI
integration. Existing ITE traces are tested separately.

Physical validation still needs repeated matching reads and a complete
erase/write/verify on representative boards, followed by a boot test with the
programmer disconnected. Timing, board wiring and real watchdog behavior
cannot be established by simulation.
