#ifndef FUXI_TORCH_PULSE_H
#define FUXI_TORCH_PULSE_H
#include <stdint.h>

typedef struct {
    void *context;
    int (*read)(void *, unsigned, uint8_t *);
    int (*write)(void *, unsigned, uint8_t);
    void (*wait_us)(void *, unsigned);
} FuxiTorchIo;

static inline int fuxi_torch_pulse_level(const FuxiTorchIo *io, unsigned level)
{
    static const unsigned registers[] = {0x3e, 0x42, 0x49, 0x4a, 0x46, 0x4e};
    uint8_t saved[6], value = 0, type = 0, subtype = 0;
    int result = -1, enabled = 0, restored = 1, disabled = 0;
    if (!io || !io->read || !io->write || !io->wait_us || level < 1 || level > 4) return -1;
    if (io->read(io->context, 4, &type) || io->read(io->context, 5, &subtype) ||
        type != 0x18 || subtype != 7) return -1;
    for (unsigned index = 0; index < 6; index++) {
        if (io->read(io->context, registers[index], &saved[index])) return -1;
    }
    if ((saved[4] & 0x80) || saved[5]) return -2;
    for (unsigned index = 0; index < 3; index++) {
        const unsigned status[] = {6, 7, 9};
        if (io->read(io->context, status[index], &value) || value) return -2;
    }
    const uint8_t setup[] = {0x89, (uint8_t)(level * 4 - 1),
        (uint8_t)(saved[2] | 1), (uint8_t)((saved[3] & ~7u) | 1)};
    for (unsigned index = 0; index < 4; index++) {
        if (io->write(io->context, registers[index], setup[index]) ||
            io->read(io->context, registers[index], &value) || value != setup[index]) {
            result = -3;
            goto cleanup;
        }
    }
    if (io->write(io->context, 0x46, saved[4] | 0x80) ||
        io->read(io->context, 0x46, &value) || value != (uint8_t)(saved[4] | 0x80)) {
        result = -4;
        goto cleanup;
    }
    enabled = 1;
    if (io->write(io->context, 0x4e, 1) ||
        io->read(io->context, 0x4e, &value) || value != 1) {
        result = -4;
        goto cleanup;
    }
    io->wait_us(io->context, 80000);
    result = 0;
    for (unsigned index = 0; index < 3; index++) {
        const unsigned status[] = {6, 7, 9};
        if (io->read(io->context, status[index], &value) || value) result = -5;
    }
cleanup:
    if (io->write(io->context, 0x4e, 0)) restored = 0;
    if (io->write(io->context, 0x46, saved[4])) restored = 0;
    unsigned consecutive_off = 0;
    for (unsigned attempt = 0; attempt < 4; attempt++) {
        uint8_t channels = 0, module = 0;
        int channel_error = io->read(io->context, 0x4e, &channels);
        int module_error = io->read(io->context, 0x46, &module);
        if (channel_error || module_error) break;
        consecutive_off = !channels && module == saved[4] ? consecutive_off + 1 : 0;
        if (consecutive_off == 2) {
            disabled = 1;
            break;
        }
        if (attempt < 3) io->wait_us(io->context, 1000);
    }
    if (!disabled) {
        if (enabled) io->wait_us(io->context, 110000);
        return -6;
    }
    for (unsigned index = 0; index < 3; index++) {
        const unsigned status[] = {6, 7, 9};
        if (io->read(io->context, status[index], &value) || value) {
            if (!result) result = -5;
        }
    }
    for (unsigned index = 0; index < 4; index++) {
        if (io->write(io->context, registers[index], saved[index])) restored = 0;
    }
    for (unsigned index = 0; index < 6; index++) {
        if (io->read(io->context, registers[index], &value) || value != saved[index]) restored = 0;
    }
    return restored ? result : -6;
}

static inline int fuxi_torch_pulse(const FuxiTorchIo *io)
{
    return fuxi_torch_pulse_level(io, 2);
}
#endif
