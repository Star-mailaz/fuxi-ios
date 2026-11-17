#ifndef FUXI_TORCH_STEADY_H
#define FUXI_TORCH_STEADY_H
#include "fuxi_torch_pulse.h"

typedef struct {
    uint8_t saved[6];
    unsigned prepared;
    unsigned level;
    unsigned failed;
} FuxiTorchSteady;

static inline int fuxi_torch_steady_faults(const FuxiTorchIo *io)
{
    static const unsigned offsets[] = {6, 7, 9};
    for (unsigned index = 0; index < 3; index++) {
        uint8_t value = 0;
        if (io->read(io->context, offsets[index], &value) || value) return -5;
    }
    return 0;
}

static inline int fuxi_torch_steady_write(const FuxiTorchIo *io, unsigned offset, uint8_t expected)
{
    uint8_t value = 0;
    if (io->write(io->context, offset, expected) ||
        io->read(io->context, offset, &value) || value != expected) return -3;
    return 0;
}

static inline int fuxi_torch_steady_stop(const FuxiTorchIo *io, FuxiTorchSteady *state)
{
    static const unsigned offsets[] = {0x3e, 0x42, 0x49, 0x4a, 0x46, 0x4e};
    if (!state->prepared) return 0;
    int result = 0;
    if (io->write(io->context, 0x4e, 0)) result = -6;
    if (io->write(io->context, 0x46, state->saved[4])) result = -6;
    unsigned consecutive = 0, disabled = 0;
    for (unsigned attempt = 0; attempt < 4; attempt++) {
        uint8_t channels = 0, module = 0;
        int channel_error = io->read(io->context, 0x4e, &channels);
        int module_error = io->read(io->context, 0x46, &module);
        if (channel_error || module_error) break;
        consecutive = !channels && module == state->saved[4] ? consecutive + 1 : 0;
        if (consecutive == 2) {
            disabled = 1;
            break;
        }
        if (attempt < 3) io->wait_us(io->context, 1000);
    }
    if (!disabled) return -6;
    state->level = 0;
    if (fuxi_torch_steady_faults(io) && !result) result = -5;
    for (unsigned index = 0; index < 4; index++) {
        if (io->write(io->context, offsets[index], state->saved[index])) result = -6;
    }
    for (unsigned index = 0; index < 6; index++) {
        uint8_t value = 0;
        if (io->read(io->context, offsets[index], &value) ||
            value != state->saved[index]) result = -6;
    }
    if (!result) state->prepared = 0;
    return result;
}

static inline int fuxi_torch_steady_start(const FuxiTorchIo *io, FuxiTorchSteady *state,
    unsigned level)
{
    static const unsigned offsets[] = {0x3e, 0x42, 0x49, 0x4a, 0x46, 0x4e};
    uint8_t type = 0, subtype = 0;
    if (io->read(io->context, 4, &type) || io->read(io->context, 5, &subtype) ||
        type != 0x18 || subtype != 7) return -1;
    for (unsigned index = 0; index < 6; index++) {
        if (io->read(io->context, offsets[index], &state->saved[index])) return -1;
    }
    if ((state->saved[4] & 0x80) || state->saved[5]) return -2;
    if (fuxi_torch_steady_faults(io)) return -5;
    state->prepared = 1;
    const uint8_t setup[] = {0, (uint8_t)(level * 4 - 1),
        (uint8_t)(state->saved[2] | 1), (uint8_t)((state->saved[3] & ~7u) | 1)};
    for (unsigned index = 0; index < 4; index++) {
        if (fuxi_torch_steady_write(io, offsets[index], setup[index])) return -3;
    }
    if (fuxi_torch_steady_write(io, 0x46, (uint8_t)(state->saved[4] | 0x80)) ||
        fuxi_torch_steady_write(io, 0x4e, 1)) return -4;
    state->level = level;
    return fuxi_torch_steady_faults(io);
}

static inline int fuxi_torch_steady_check(const FuxiTorchIo *io, const FuxiTorchSteady *state)
{
    static const unsigned offsets[] = {0x3e, 0x42, 0x49, 0x4a, 0x46, 0x4e};
    const uint8_t expected[] = {0, (uint8_t)(state->level * 4 - 1),
        (uint8_t)(state->saved[2] | 1), (uint8_t)((state->saved[3] & ~7u) | 1),
        (uint8_t)(state->saved[4] | 0x80), 1};
    if (fuxi_torch_steady_faults(io)) return -5;
    for (unsigned index = 0; index < 6; index++) {
        uint8_t value = 0;
        if (io->read(io->context, offsets[index], &value) || value != expected[index]) return -5;
    }
    return 0;
}

static inline int fuxi_torch_steady_step(const FuxiTorchIo *io, FuxiTorchSteady *state,
    unsigned level)
{
    if (!io || !io->read || !io->write || !io->wait_us || !state ||
        level > 4 || state->failed) return -1;
    int result = 0, cleanup = 0;
    if (!level) {
        result = fuxi_torch_steady_stop(io, state);
    } else if (state->prepared) {
        result = fuxi_torch_steady_check(io, state);
        cleanup = 1;
        if (!result && state->level != level) {
            result = fuxi_torch_steady_write(io, 0x42, (uint8_t)(level * 4 - 1));
            if (!result) {
                state->level = level;
                result = fuxi_torch_steady_check(io, state);
            }
        }
    } else {
        result = fuxi_torch_steady_start(io, state, level);
        cleanup = 1;
    }
    if (result) {
        if (state->prepared && cleanup) {
            int stopped = fuxi_torch_steady_stop(io, state);
            if (stopped == -6) result = stopped;
        }
        state->failed = 1;
    }
    return result;
}
#endif
