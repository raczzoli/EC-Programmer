# Code map and regression checks

The supported ITE flash algorithms are selected from numeric EC revision and
flash-command signatures in `app/flash_protocols.py`. There is no whitelist of
laptop boards or individual ITE part numbers. Capacity remains a user selection.

## Host

- `app/gui.py`: widgets, progress, save/open dialogs and UI state.
- `app/operations.py`: a worker owns an entire connect/read/erase/write operation,
  including USB cleanup. It emits one terminal result. Cleanup warnings do not
  replace a successful verification or hide an earlier programming error.
- `app/session.py`: connection, existing-session reuse, power-cycle recovery,
  identity checks and background keepalive. No Qt widgets.
- `app/transport.py`: USB CDC framing, capability negotiation, response validation
  and command timeouts. New firmware supports request IDs; replies from an older
  request are ignored. After a timeout, this connection sends no more commands.
- `app/ec.py`: ITE operations and compatibility paths for older Pico firmware.
- `app/geometry.py`: common supported capacities and page geometry.
- `app/ene.py`: common experimental ENE EDI flash engine; compatibility groups
  and selected ranges are in `app/ene_families.py`. Physical models, pinouts and
  identity restrictions are in `app/ene_models.py`. See [ENE](ENE.md).

The worker negotiates required capabilities before erase. Write remains
erase → program → full verification, without an automatic backup or erased-flash
scan. Keepalive and disconnect run on the worker thread. Failed operations clear
the GUI's connected state; a completed read remains available even if cleanup fails.
Flash operations selected in a file/confirmation dialog wait for any in-flight
keepalive before acquiring USB.

## Firmware

- `main.c`, `line_reader.h`: USB input loop; discard an oversized command through
  its newline so its trailing text cannot become a second command.
- `usb_commands.c`, `usb_output.c`: command parsing, tagged replies and metadata.
- `ite_bus.c`: open-drain GPIO/I²C and bounded clock stretching.
- `ite_dbgr.c`: waveform, GPIO mapping, reset-time entry and register access.
- `ite_session.c`: watchdog hold, expiry and register-cursor restoration.
- `ite_flash.c`: page reads, sector erase, legacy AAI, newer AAI and page program.
- `ene_edi.c`: common EDI transport/page engine, with hardware revision
  parameters for capacity bounds and entry/watchdog behavior.

The PIO tail wait includes all 16 states that can remain after its FIFO empties.
Waveform contents, rates and SDA/SCL mapping are preserved. I²C retains the
validated 5 µs delays. `I2CTIMING 3` and `I2CTIMING 2` are developer-only experiments;
the GUI explicitly selects 5. Faster timing is not enabled or claimed tested.

Atomic `REGREAD`, `REGWRITE`, `FLASHID`, `SPISTATUS` and `ERASESECTOR` reduce USB
round trips and prevent idle watchdog work from interrupting these sequences.
The watchdog also restores the selected register for legacy split commands.
`RELEASE` frees the bus while keeping the timed debug hold; `ENDSESSION` stops
feeding it when the GUI closes. It does not itself reset or boot the target EC.

## Verification limits

`python -m unittest discover -s tests -v` runs host tests and compiles actual C
flash/session/parser code against a recording bus. Install `requirements-test.txt`
on Windows or provide a native C compiler. No test opens a real serial port.

`tests/fixtures/ite_flash_traces.json` records 18 command traces produced by the
pre-refactor C functions: legacy AAI 64/256, newer AAI 64/256, page program 64 and
page read, with success and injected write failures. The fixture records the
original source SHA-256. The harness fixes time/status responses; this protects
transaction ordering, not electrical timing or actual flash behavior. Separate
tests exercise watchdog cursor restoration, parser rejection, overflow recovery,
tagged output and atomic sector erase.

The CI builds all nine board profiles and checks UF2 metadata. A successful
compile or simulation is not hardware validation. A candidate stays separate
from the existing release until it has been exercised on a physical ITE target.
