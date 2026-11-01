/* Hand-encoded one-instruction PIO program; see dbgr_open_drain.pio.
 * Avoids requiring a host pioasm compiler for this small firmware.
 */
#pragma once
#include "hardware/pio.h"

static const uint16_t dbgr_open_drain_instructions[] = {
    0x6000u | ((pio_pindirs & 7u) << 5) | 2u /* out pindirs, 2 */
};

static const struct pio_program dbgr_open_drain_program = {
    .instructions = dbgr_open_drain_instructions,
    .length = 1,
    .origin = -1,
    .pio_version = 0
};

static inline pio_sm_config dbgr_open_drain_program_get_default_config(uint offset) {
    pio_sm_config cfg = pio_get_default_sm_config();
    sm_config_set_wrap(&cfg, offset, offset);
    return cfg;
}
