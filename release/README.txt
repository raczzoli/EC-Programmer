EC Programmer 0.4.0 / 5ee6bf7a2a21

Automated tests passed. See docs/ENE.md for hardware validation status.
app/ contains the Windows GUI; pico-firmwares/ contains board-specific UF2 files.
Install only the UF2 matching your board. Pico 2 H uses Pico-2-RP2350.uf2.
Default ITE pins: GP7 SDA, GP6 SCL, common GND. Default timing is unchanged.
Read saves after completion. Write erases, programs and verifies; no automatic backup.
Size: numeric/manual for ITE (64/128/192/256 KiB); automatic and locked for ENE.
ENE is experimental. GP4 DO, GP5 CS, GP6 CLK, GP7 DI, common GND; confirm target strap/pins.
ENE models: KB9012QF, KB9022Q, KB9028Q, KB902FQ C (provisional), KB9052QD (128 KiB).
Source and instructions: https://github.com/raczzoli/EC-Programmer
