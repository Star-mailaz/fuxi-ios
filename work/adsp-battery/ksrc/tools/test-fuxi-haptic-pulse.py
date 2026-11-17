import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "fuxi_haptic_pulse.h"

struct model {
    uint8_t registers[768], original[768];
    unsigned owners[3], reads, writes, owner_reads;
    unsigned fail_read, corrupt_read, fail_write, drop_write, fail_owner;
    unsigned quarantine, dead_mask, write_after_error, drop_stop, stuck_hpwr;
    unsigned stop_read_error, lying_play, fault, change_owner, mutate_staged;
    unsigned now, end, pulses, expired, peak_vmax, restored_writes;
    unsigned addresses[256], values[256];
    FuxiHapticState state;
};

static unsigned slot(unsigned address)
{
    assert(address >= 0xf000 && address <= 0xf2ff);
    return address - 0xf000;
}

static int active(const struct model *state)
{
    return !state->expired && (state->registers[0x46] & 0x80) &&
        (state->registers[0x4c] & 0x80);
}

static int owner(void *context, unsigned peripheral, unsigned *value)
{
    struct model *state = context;
    assert(peripheral >= 0xf0 && peripheral <= 0xf2);
    if (++state->owner_reads == state->fail_owner) return -1;
    *value = state->owners[peripheral - 0xf0];
    if (state->change_owner && state->pulses && peripheral == 0xf0) *value = 3;
    return 0;
}

static int read_register(void *context, unsigned address, uint8_t *value)
{
    struct model *state = context;
    unsigned offset = slot(address);
    if (++state->reads == state->fail_read || (state->dead_mask & (1u << (offset >> 8))))
        return -1;
    if (state->stop_read_error && state->pulses && address == 0xf04c &&
        !(state->registers[0x4c] & 0x80)) return -1;
    if (state->mutate_staged && state->writes == 32 && address == 0xf046) {
        state->registers[0x13b] ^= 1;
        state->mutate_staged = 0;
    }
    *value = state->registers[offset];
    if (address == 0xf00b) {
        *value = active(state) || (state->stuck_hpwr && state->pulses) ? 3 :
            state->registers[offset];
    }
    if (state->fault && state->pulses && address == 0xf00c) *value = 4;
    if (state->lying_play && state->pulses && address == 0xf04c) *value = 2;
    if (state->reads == state->corrupt_read) *value ^= 1;
    return 0;
}

static void validate_start(struct model *state)
{
    assert(state->registers[0x46] & 0x80);
    assert(state->registers[0x48] == FUXI_HAPTIC_VMAX_CODE);
    assert(state->registers[0x4b] & 0x10);
    assert(!(state->registers[0x4e] & 0xc0));
    assert(!(state->registers[0x63] & 0x80));
    unsigned period = (((unsigned)state->registers[0x130] & 15u) * 256u +
        state->registers[0x131]) * 5u;
    unsigned calibrated = (((unsigned)state->registers[0x5c] & 15u) * 256u +
        state->registers[0x5d]) * 5u;
    assert(period == calibrated && period == state->state.period_us && period);
    for (unsigned index = 0; index < 8; index++) {
        assert(state->registers[0x134 + index * 3] == 0);
        assert(state->registers[0x135 + index * 3] == 0);
        assert(state->registers[0x136 + index * 3] == (index < 4 ? 64 : 0));
    }
    state->peak_vmax = state->registers[0x48] * 50u;
    state->end = state->now + period * 8u;
    state->expired = 0;
    state->pulses++;
    assert(state->pulses == 1 && state->peak_vmax <= 1200);
}

static int write_register(void *context, unsigned address, uint8_t value)
{
    struct model *state = context;
    unsigned offset = slot(address);
    assert(fuxi_haptic_writable(address));
    assert(address < 0xf200 && state->owners[offset >> 8] == 0);
    assert(!(state->change_owner && state->pulses && address < 0xf100));
    assert(state->writes < 256);
    state->addresses[state->writes] = address;
    state->values[state->writes++] = value;
    if (state->dead_mask & (1u << (offset >> 8))) return -1;
    int fail = state->writes == state->fail_write;
    if (fail && !state->write_after_error) {
        if (state->quarantine) state->dead_mask |= 1u << (offset >> 8);
        return -1;
    }
    int stop = state->pulses && ((address == 0xf04c && value == 2) ||
        (address == 0xf046 && !(value & 0x80)));
    if (state->writes != state->drop_write && !(state->drop_stop && stop)) {
        if (address != 0xf046 && address != 0xf04c) assert(!active(state));
        if (state->state.stopped && address != 0xf046) {
            assert(!(state->registers[0x46] & 0x80));
            state->restored_writes++;
        }
        if (address == 0xf04c && (value & 0x80)) {
            assert(value == 0x82);
            validate_start(state);
        }
        state->registers[offset] = value;
    }
    if (fail) {
        if (state->quarantine) state->dead_mask |= 1u << (offset >> 8);
        return -1;
    }
    return 0;
}

static void wait_us(void *context, unsigned microseconds)
{
    struct model *state = context;
    assert(microseconds <= 173800);
    state->now += microseconds;
    if (state->pulses && state->now >= state->end) state->expired = 1;
}

static void fixture(struct model *state)
{
    memset(state, 0, sizeof(*state));
    state->owners[2] = 3;
    state->registers[0x01] = 4;
    state->registers[0x04] = 0x15;
    state->registers[0x05] = 0x0a;
    state->registers[0x101] = 4;
    state->registers[0x104] = 0x15;
    state->registers[0x105] = 0x0b;
    state->registers[0x200] = 2;
    state->registers[0x204] = 0x31;
    state->registers[0x205] = 1;
    state->registers[0x241] = 0xe0;
    state->registers[0x46] = 0x80;
    state->registers[0x48] = 0x1c;
    state->registers[0x49] = 1;
    state->registers[0x4a] = 0x84;
    state->registers[0x4b] = 4;
    state->registers[0x4c] = 1;
    state->registers[0x4d] = 0xc8;
    state->registers[0x4e] = 0xe0;
    state->registers[0x5c] = 4;
    state->registers[0x5d] = 0x76;
    state->registers[0x63] = 0x89;
    state->registers[0x67] = 10;
    state->registers[0x68] = 0x54;
    state->registers[0x130] = 2;
    state->registers[0x131] = 0x21;
    for (unsigned index = 0; index < 24; index++) state->registers[0x134 + index] = (uint8_t)(index + 17);
    memcpy(state->original, state->registers, sizeof(state->registers));
}

static int run(struct model *state)
{
    uint8_t boost_before[256];
    uint8_t tlra_high = state->registers[0x5c], tlra_low = state->registers[0x5d];
    memcpy(boost_before, state->registers + 0x200, sizeof(boost_before));
    FuxiHapticIo io = {state, owner, read_register, write_register, wait_us, 1};
    int result = fuxi_haptic_pulse(&io, &state->state);
    assert(state->pulses <= 1);
    assert(!state->pulses || !active(state));
    assert(!memcmp(state->registers + 0x200, boost_before, sizeof(boost_before)));
    assert(state->registers[0x5c] == tlra_high);
    assert(state->registers[0x5d] == tlra_low);
    if (!result) {
        assert(state->state.started && state->state.stopped && state->state.restored);
        assert(!state->state.failed);
        assert(!memcmp(state->registers, state->original, sizeof(state->registers)));
    } else assert(state->state.failed);
    return result;
}

static void assert_latched(struct model *state)
{
    unsigned reads = state->reads, writes = state->writes, owners = state->owner_reads;
    FuxiHapticIo io = {state, owner, read_register, write_register, wait_us, 1};
    assert(fuxi_haptic_pulse(&io, &state->state) == FUXI_HAPTIC_LOCKED);
    assert(state->reads == reads && state->writes == writes && state->owner_reads == owners);
}

static void assert_retained(struct model *state)
{
    assert(state->state.failed && !state->state.stopped && !state->state.restored);
    assert(state->registers[0x48] == 24 && !state->restored_writes);
    assert(state->registers[0x130] == 4 && state->registers[0x131] == 0x76);
    for (unsigned index = 0; index < 8; index++) {
        assert(state->registers[0x134 + index * 3] == 0);
        assert(state->registers[0x135 + index * 3] == 0);
        assert(state->registers[0x136 + index * 3] == (index < 4 ? 64 : 0));
    }
    assert_latched(state);
}

int main(void)
{
    struct model state;
    fixture(&state);
    assert(run(&state) == 0);
    assert(state.pulses == 1 && state.state.period_us == 5710);
    assert(state.now == 56680 && state.writes == 68);
    unsigned reads = state.reads, writes = state.writes, owners = state.owner_reads;
    FuxiHapticIo once = {&state, owner, read_register, write_register, wait_us, 1};
    assert(fuxi_haptic_pulse(&once, &state.state) == FUXI_HAPTIC_ONCE);
    assert(state.reads == reads && state.writes == writes && state.owner_reads == owners);
    fixture(&state);
    FuxiHapticIo probe = {&state, owner, read_register, write_register, wait_us, 0};
    assert(fuxi_haptic_pulse(&probe, &state.state) == FUXI_HAPTIC_FINITE_UNVERIFIED);
    assert(state.state.probed && state.state.period_us == 5710);
    assert(!state.writes && !state.pulses && !state.state.start_attempted);
    assert(!memcmp(state.registers, state.original, sizeof(state.registers)));
    assert_latched(&state);

    static const unsigned identities[] = {1, 4, 5, 0x101, 0x104, 0x105, 0x200, 0x201, 0x204, 0x205};
    for (unsigned index = 0; index < sizeof(identities) / sizeof(identities[0]); index++) {
        fixture(&state);
        state.registers[identities[index]] ^= 1;
        assert(run(&state) == FUXI_HAPTIC_HARDWARE && !state.writes);
        assert_latched(&state);
    }
    for (unsigned index = 0; index < 3; index++) {
        fixture(&state);
        state.owners[index] ^= 1;
        assert(run(&state) == FUXI_HAPTIC_HARDWARE && !state.writes);
    }
    static const unsigned busy_registers[] = {0x0b, 0x4c, 0x246, 0x20b};
    static const uint8_t busy_values[] = {1, 0x81, 0x80, 1};
    for (unsigned index = 0; index < 4; index++) {
        fixture(&state);
        state.registers[busy_registers[index]] = busy_values[index];
        assert(run(&state) == FUXI_HAPTIC_BUSY && !state.writes);
    }
    fixture(&state);
    state.registers[0x0c] = 4;
    assert(run(&state) == FUXI_HAPTIC_FAULT && !state.writes);
    for (unsigned bit = 0x20; bit <= 0x80; bit <<= 1) {
        fixture(&state);
        state.registers[0x241] &= (uint8_t)~bit;
        assert(run(&state) == FUXI_HAPTIC_HARDWARE && !state.writes);
    }
    fixture(&state);
    state.registers[0x68] |= 3;
    assert(run(&state) == FUXI_HAPTIC_HARDWARE && !state.writes);
    fixture(&state);
    state.registers[0x49] = 0x11;
    assert(run(&state) == FUXI_HAPTIC_HARDWARE && !state.writes);
    fixture(&state);
    state.registers[0x5c] = state.registers[0x5d] = 0;
    assert(run(&state) == FUXI_HAPTIC_HARDWARE && !state.writes);

    for (unsigned index = 1; index <= reads; index++) {
        fixture(&state);
        state.fail_read = index;
        assert(run(&state) < 0);
        assert_latched(&state);
        fixture(&state);
        state.corrupt_read = index;
        run(&state);
        if (state.state.failed) assert_latched(&state);
    }
    for (unsigned index = 1; index <= writes; index++) {
        fixture(&state);
        state.fail_write = index;
        assert(run(&state) < 0);
        assert_latched(&state);
        fixture(&state);
        state.drop_write = index;
        run(&state);
        if (state.state.failed) assert_latched(&state);
        fixture(&state);
        state.fail_write = index;
        state.write_after_error = 1;
        assert(run(&state) < 0);
        fixture(&state);
        state.fail_write = index;
        state.quarantine = 1;
        assert(run(&state) < 0);
        fixture(&state);
        state.fail_write = index;
        state.quarantine = state.write_after_error = 1;
        assert(run(&state) < 0);
    }
    for (unsigned index = 1; index <= owners; index++) {
        fixture(&state);
        state.fail_owner = index;
        assert(run(&state) < 0);
    }
    fixture(&state);
    state.drop_stop = 1;
    assert(run(&state) == FUXI_HAPTIC_TIMEOUT && state.expired);
    assert_retained(&state);
    fixture(&state);
    state.drop_stop = state.lying_play = 1;
    assert(run(&state) == FUXI_HAPTIC_TIMEOUT);
    assert_retained(&state);
    fixture(&state);
    state.stuck_hpwr = 1;
    assert(run(&state) == FUXI_HAPTIC_TIMEOUT);
    assert_retained(&state);
    fixture(&state);
    state.stop_read_error = 1;
    assert(run(&state) == FUXI_HAPTIC_TIMEOUT);
    assert_retained(&state);
    fixture(&state);
    state.change_owner = 1;
    assert(run(&state) == FUXI_HAPTIC_TIMEOUT);
    assert_retained(&state);
    fixture(&state);
    state.fault = 1;
    assert(run(&state) == FUXI_HAPTIC_FAULT && state.state.restored);
    assert_latched(&state);
    fixture(&state);
    state.mutate_staged = 1;
    assert(run(&state) == FUXI_HAPTIC_VERIFY && !state.pulses);
    for (unsigned units = 1; units <= 4095; units += 4094) {
        fixture(&state);
        state.registers[0x5c] = (uint8_t)(units >> 8);
        state.registers[0x5d] = (uint8_t)units;
        memcpy(state.original, state.registers, sizeof(state.registers));
        assert(run(&state) == 0 && state.state.period_us == units * 5);
    }
    fixture(&state);
    state.registers[0x46] = 0;
    memcpy(state.original, state.registers, sizeof(state.registers));
    assert(run(&state) == 0);
    fixture(&state);
    state.registers[0x5c] |= 0xa0;
    memcpy(state.original, state.registers, sizeof(state.registers));
    assert(run(&state) == 0);
    assert(fuxi_haptic_pulse(NULL, &state.state) == FUXI_HAPTIC_INVALID);
    assert(fuxi_haptic_pulse(&once, NULL) == FUXI_HAPTIC_INVALID);
    printf("PASS: production HAP525 PATTERN1 helper; %u read points, %u write points, %u ownership points; "
        "dropped writes, corrupt reads, ambiguous timeouts, APID quarantine, finite expiry, "
        "stop proof, retained limits, restoration, one-shot failure latch and read-only production gate\n", reads, writes, owners);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--syntax-only', action='store_true')
    parser.add_argument('--target', default='arm64-apple-darwin')
    args = parser.parse_args()
    compiler = os.environ.get('CC') or next(
        (found for name in ('cc', 'clang', 'gcc', 'cl') if (found := shutil.which(name))), None
    )
    if not compiler:
        raise SystemExit('Host C compiler unavailable. Run this production-helper test in CI with CC=clang.')
    microsoft = Path(compiler).name.lower() in ('cl', 'cl.exe')
    with tempfile.TemporaryDirectory(prefix='fuxi-haptic-pulse-') as temporary:
        directory = Path(temporary)
        cfile = directory / 'pulse.c'
        binary = directory / ('pulse.exe' if os.name == 'nt' else 'pulse')
        include = ROOT / 'xnu/fuxi-adsp'
        if args.syntax_only:
            if microsoft:
                raise SystemExit('ARM64 freestanding syntax checking requires clang. Host tests support MSVC.')
            cfile.write_text('#include "fuxi_haptic_pulse.h"\n'
                             'int check_pulse(const FuxiHapticIo *io, FuxiHapticState *state) {\n'
                             '    return fuxi_haptic_pulse(io, state);\n}\n', encoding='utf-8')
            subprocess.run([compiler, '-target', args.target, '-ffreestanding', '-std=c11',
                            '-Wall', '-Wextra', '-Werror', '-fsyntax-only', '-I' + str(include),
                            str(cfile)], check=True)
            print('PASS: production haptic helper ARM64 freestanding syntax')
            return
        cfile.write_text(SOURCE, encoding='utf-8')
        if microsoft:
            command = [compiler, '/nologo', '/std:c11', '/W4', '/WX', '/TC', '/I' + str(include),
                       '/Fo' + str(directory / 'pulse.obj'), '/Fe' + str(binary), str(cfile)]
        else:
            command = [compiler, '-std=c11', '-g', '-Wall', '-Wextra', '-Werror',
                       '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                       '-I' + str(include), str(cfile), '-o', str(binary)]
        subprocess.run(command, check=True, cwd=directory)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
