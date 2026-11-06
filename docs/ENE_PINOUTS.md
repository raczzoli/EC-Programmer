# ENE model pinouts

The GUI lists physical models, while EDI protocol code remains shared by family.
Only the packages below have catalog entries. A similar part number or a shared
protocol does not establish the same physical pinout.

| GUI model | Package | Internal protocol | HW / EDI | Capacity |
| --- | --- | --- | --- | --- |
| KB9012QF | LQFP-128 | KB901x | C3 / 04 | 128 KiB |
| KB9022Q | LQFP-128 | KB902x | B1 / 07 | 128 KiB |
| KB9028Q | LQFP-128 (documented C revision) | KB902x | C0 / 07 | 128 KiB |
| KB9052QD | LQFP-128 (Q-D) | KB9052 | D0 / 0B | 128 KiB |

These entries share this physical EDI wiring:

| Pico | Physical EC pin | Signal |
| --- | --- | --- |
| GP4 | 62 | KSI7 / EDI DO |
| GP5 | 59 | KSI4 / EDI CS |
| GP6 | 60 | KSI5 / EDI CLK |
| GP7 | 61 | KSI6 / EDI DI |
| GND | Board ground | Common ground |
| Board ground | 42 | KSO3 programming strap |

Disconnect target power and Pico USB before wiring. Ground KSO3 before powering
the target, and power the EC from its board. Locate the chip's pin-1 mark and
count pins counterclockwise viewed from above. Do not use these numbers for a
keyboard connector or a BGA package. Disconnect the keyboard while using its
matrix signals for programming. Do not ground KSO2 as an additional strap.

## Pinout evidence

- **KB9012QF:** [ENE KB9012 datasheet](https://www.eliptor.pl/pub/pdf/ene/KB9012.pdf),
  section 2.1, printed page 8 / PDF page 18, LQFP-128 pin diagram. The same
  datasheet also describes a BGA package; that ball map is not this entry.
- **KB9022Q:** [Compal LA-E892P rev 1A schematic](https://www.oldergeeks.com/downloads/files/Acer%20Aspire%20A515-51G%20Compal%20LA-E892P%20C5V01%20r1A.pdf),
  sheet 37, UB1 marked KB9022QD_LQFP128_14X14. Direct EC-pin wiring returned
  HW=B1 / EDI=07 with this project. That is identification evidence, not a
  completed erase/write/verify test.
- **KB9028Q:** [MSI MS-16K2/17B1 rev 0B schematic](https://manualmachine.com/msi/ms16k2/24376601-schematics/),
  U25 marked KB9028Q-C-RH: KSI4-7 at 59-62, KSO3 at 42.
- **KB9052QD:** [Compal FH5LI LA-J801P rev 1.0 schematic](https://pdfcoffee.com/acer-aspire-ene-kb9052-compal-la-j801p-fh5li-pdf-free.html),
  EC_ENE KB9052Q sheet, part KB9052Q-D_LQFP128_14X14: KSI4-7 at 59-62,
  KSO3 at 42. The Q-D schematic marking is displayed as KB9052QD.

Protocol identities and capacities come from the separate references in
[ENE.md](ENE.md). Pinout documentation does not establish hardware-tested
read/write support. The other listed models still need physical validation.

KB9542GF remains implemented internally, but is absent from the GUI until its
exact package pinout is documented. A KB9542Q schematic does not establish the
GF package. Other members of KB901x/KB902x and KB9052 B are likewise not exposed
merely by extrapolating their family name.

Add models to `app/ene_models.py` with a source, package, allowed identity and
physical mapping. Reuse the protocol groups in `app/ene_families.py`.
