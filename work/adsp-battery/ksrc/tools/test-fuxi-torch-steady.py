import argparse
import os
from pathlib import Path
import runpy
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fuxi_torch_steady.h"
#include "fuxi_torch_runtime.h"
static unsigned checks;
#define CHECK(test) do { checks++; if (!(test)) { fprintf(stderr, "line %d: %s\n", __LINE__, #test); exit(1); } } while (0)
typedef struct {
    uint8_t registers[256], original[256];
    unsigned reads, writes, fail_read, fail_write, drop_write, fail_after_write;
    unsigned starts, stops, holding, live_updates, corrupt_after_update;
    uint64_t now_us, drop_mask;
} Model;
static unsigned active(const Model *model) {
    return !!((model->registers[0x46] & 0x80) && model->registers[0x4e]);
}
static int read_register(void *context, unsigned offset, uint8_t *value) {
    Model *model = context;
    CHECK(offset < 256 && value);
    if (++model->reads == model->fail_read) return -1;
    *value = model->registers[offset];
    return 0;
}
static int write_register(void *context, unsigned offset, uint8_t value) {
    Model *model = context;
    CHECK(offset == 0x3e || offset == 0x42 || offset == 0x49 ||
        offset == 0x4a || offset == 0x46 || offset == 0x4e);
    CHECK(!model->holding);
    model->writes++;
    if (model->writes == model->fail_write && !model->fail_after_write) return -1;
    unsigned before = active(model);
    if (model->writes != model->drop_write &&
        !(model->writes < 64 && (model->drop_mask & (UINT64_C(1) << model->writes)))) {
        if (before) CHECK(offset == 0x42 || offset == 0x46 || offset == 0x4e);
        if (before && offset == 0x42) {
            CHECK(value <= 15 && (value & 3) == 3);
            model->live_updates++;
        }
        model->registers[offset] = value;
        if (before && offset == 0x42 && model->corrupt_after_update)
            model->registers[model->corrupt_after_update] ^= 1;
    }
    unsigned after = active(model);
    if (!before && after) {
        CHECK(!model->registers[0x3e] && (model->registers[0x49] & 1));
        CHECK((model->registers[0x4a] & 7) == 1);
        CHECK(model->registers[0x42] <= 15 && (model->registers[0x42] & 3) == 3);
        model->starts++;
    }
    if (before && !after) model->stops++;
    return model->writes == model->fail_write ? -1 : 0;
}
static void wait_us(void *context, unsigned duration) {
    Model *model = context;
    CHECK(duration == 1000);
    model->now_us += duration;
}
static void fixture(Model *model, FuxiTorchSteady *state) {
    memset(model, 0, sizeof(*model));
    memset(state, 0, sizeof(*state));
    model->registers[4] = 0x18;
    model->registers[5] = 7;
    model->registers[0x3e] = 0x89;
    model->registers[0x42] = 23;
    model->registers[0x49] = 0x0a;
    model->registers[0x4a] = 4;
    model->registers[0x46] = 0x20;
    memcpy(model->original, model->registers, sizeof(model->original));
}
static FuxiTorchIo io_for(Model *model) {
    FuxiTorchIo io = {model, read_register, write_register, wait_us};
    return io;
}
static void steady_output(void) {
    for (unsigned level = 1; level <= 4; level++) {
        Model model;
        FuxiTorchSteady state;
        FuxiTorchRuntime runtime = {0};
        fixture(&model, &state);
        FuxiTorchIo io = io_for(&model);
        CHECK(!fuxi_torch_request(&runtime, level, 0));
        for (unsigned tick = 0; tick < 6000; tick++) {
            uint64_t now = (uint64_t)tick * 20000000;
            if (!(tick % 25)) CHECK(!fuxi_torch_request(&runtime, level, now));
            model.holding = tick != 0;
            CHECK(!fuxi_torch_steady_step(&io, &state, fuxi_torch_requested(&runtime, now)));
            CHECK(active(&model) && state.level == level);
            CHECK(model.starts == 1 && !model.stops && model.writes == 6);
            model.now_us += 20000;
        }
        model.holding = 0;
        CHECK(!fuxi_torch_request(&runtime, 0, 120000000000));
        CHECK(!fuxi_torch_steady_step(&io, &state, fuxi_torch_requested(&runtime, 120000000000)));
        CHECK(!active(&model) && !state.prepared && !state.failed);
        CHECK(model.starts == 1 && model.stops == 1 && model.writes == 12);
        CHECK(!memcmp(model.registers, model.original, sizeof(model.original)));
        unsigned writes = model.writes;
        CHECK(!fuxi_torch_steady_step(&io, &state, 0) && model.writes == writes);
    }
}
static void transitions_and_expiry(void) {
    Model model;
    FuxiTorchSteady state;
    FuxiTorchRuntime runtime = {0};
    fixture(&model, &state);
    FuxiTorchIo io = io_for(&model);
    static const unsigned levels[] = {1, 2, 3, 4, 3, 2};
    for (unsigned round = 0; round < 100; round++) {
        unsigned level = levels[round % 6];
        CHECK(!fuxi_torch_steady_step(&io, &state, level));
        CHECK(active(&model) && state.level == level && !state.failed);
        CHECK(!memcmp(state.saved, (uint8_t[]){0x89, 23, 0x0a, 4, 0x20, 0}, 6));
    }
    CHECK(model.starts == 1 && !model.stops && model.live_updates == 99 && model.writes == 105);
    CHECK(!fuxi_torch_request(&runtime, 4, 0));
    CHECK(fuxi_torch_requested(&runtime, 1999999999) == 4);
    CHECK(!fuxi_torch_requested(&runtime, 2000000000));
    CHECK(!fuxi_torch_steady_step(&io, &state, 0));
    CHECK(!active(&model) && model.stops == 1 && !state.prepared && model.writes == 111);
    CHECK(!memcmp(model.registers, model.original, sizeof(model.original)));
}
static void latched_off(Model *model, FuxiTorchIo *io, FuxiTorchSteady *state) {
    CHECK(state->failed && !active(model) && model->starts == 1 && model->stops == 1);
    unsigned reads = model->reads, writes = model->writes;
    for (unsigned level = 0; level <= 4; level++)
        CHECK(fuxi_torch_steady_step(io, state, level) < 0);
    CHECK(model->reads == reads && model->writes == writes);
}
static void live_current_changes(void) {
    static const unsigned observed[] = {0x3e, 0x42, 0x49, 0x4a, 0x46, 0x4e, 6, 7, 9};
    for (unsigned previous = 1; previous <= 4; previous++) {
        for (unsigned level = 1; level <= 4; level++) {
            Model model;
            FuxiTorchSteady state;
            fixture(&model, &state);
            FuxiTorchIo io = io_for(&model);
            CHECK(!fuxi_torch_steady_step(&io, &state, previous));
            uint8_t enabled[256], saved[6];
            memcpy(enabled, model.registers, sizeof(enabled));
            memcpy(saved, state.saved, sizeof(saved));
            unsigned reads = model.reads, writes = model.writes;
            model.holding = previous == level;
            CHECK(!fuxi_torch_steady_step(&io, &state, level));
            unsigned update_reads = model.reads - reads, update_writes = model.writes - writes;
            CHECK(model.starts == 1 && !model.stops && active(&model) && state.level == level);
            CHECK(update_writes == (previous != level ? 1u : 0u));
            CHECK(model.live_updates == (previous != level ? 1u : 0u));
            CHECK(!memcmp(saved, state.saved, sizeof(saved)));
            enabled[0x42] = (uint8_t)(level * 4 - 1);
            CHECK(!memcmp(enabled, model.registers, sizeof(enabled)));
            model.holding = 0;
            CHECK(!fuxi_torch_steady_step(&io, &state, 0));
            CHECK(model.starts == 1 && model.stops == 1 && !state.prepared);
            CHECK(!memcmp(model.registers, model.original, sizeof(model.original)));
            if (previous == level) continue;
            for (unsigned index = 1; index <= update_reads; index++) {
                fixture(&model, &state);
                CHECK(!fuxi_torch_steady_step(&io, &state, previous));
                model.fail_read = model.reads + index;
                CHECK(fuxi_torch_steady_step(&io, &state, level) < 0);
                latched_off(&model, &io, &state);
            }
            for (unsigned after = 0; after <= 1; after++) {
                fixture(&model, &state);
                CHECK(!fuxi_torch_steady_step(&io, &state, previous));
                model.fail_write = model.writes + 1;
                model.fail_after_write = after;
                CHECK(fuxi_torch_steady_step(&io, &state, level) < 0);
                latched_off(&model, &io, &state);
            }
            fixture(&model, &state);
            CHECK(!fuxi_torch_steady_step(&io, &state, previous));
            model.drop_write = model.writes + 1;
            CHECK(fuxi_torch_steady_step(&io, &state, level) < 0);
            latched_off(&model, &io, &state);
            for (unsigned index = 0; index < sizeof(observed) / sizeof(observed[0]); index++) {
                fixture(&model, &state);
                CHECK(!fuxi_torch_steady_step(&io, &state, previous));
                unsigned enabled_before = active(&model);
                model.registers[observed[index]] ^= 1;
                if (enabled_before && !active(&model)) model.stops++;
                CHECK(fuxi_torch_steady_step(&io, &state, level) < 0);
                latched_off(&model, &io, &state);
                CHECK(!model.live_updates);
                fixture(&model, &state);
                CHECK(!fuxi_torch_steady_step(&io, &state, previous));
                model.corrupt_after_update = observed[index];
                CHECK(fuxi_torch_steady_step(&io, &state, level) < 0);
                latched_off(&model, &io, &state);
                CHECK(model.live_updates == 1);
            }
        }
    }
}
static void failures(void) {
    Model model;
    FuxiTorchSteady state;
    fixture(&model, &state);
    FuxiTorchIo io = io_for(&model);
    CHECK(!fuxi_torch_steady_step(&io, &state, 4));
    unsigned start_reads = model.reads, start_writes = model.writes;
    CHECK(!fuxi_torch_steady_step(&io, &state, 0));
    unsigned stop_reads = model.reads - start_reads, stop_writes = model.writes - start_writes;
    for (unsigned index = 1; index <= start_reads; index++) {
        fixture(&model, &state); model.fail_read = index;
        CHECK(fuxi_torch_steady_step(&io, &state, 4) < 0 && state.failed);
        CHECK(!active(&model));
        unsigned writes = model.writes;
        CHECK(fuxi_torch_steady_step(&io, &state, 4) < 0 && model.writes == writes);
    }
    for (unsigned index = 1; index <= start_writes; index++) {
        for (unsigned after = 0; after <= 1; after++) {
            fixture(&model, &state); model.fail_write = index; model.fail_after_write = after;
            CHECK(fuxi_torch_steady_step(&io, &state, 4) < 0 && state.failed);
            CHECK(!active(&model));
        }
        fixture(&model, &state); model.drop_write = index;
        CHECK(fuxi_torch_steady_step(&io, &state, 4) < 0 && state.failed && !active(&model));
    }
    for (unsigned index = 1; index <= 9; index++) {
        fixture(&model, &state);
        CHECK(!fuxi_torch_steady_step(&io, &state, 4));
        model.fail_read = model.reads + index;
        CHECK(fuxi_torch_steady_step(&io, &state, 4) < 0 && state.failed && !active(&model));
    }
    for (unsigned index = 1; index <= stop_reads; index++) {
        fixture(&model, &state);
        CHECK(!fuxi_torch_steady_step(&io, &state, 4));
        model.fail_read = model.reads + index;
        CHECK(fuxi_torch_steady_step(&io, &state, 0) < 0 && state.failed && !active(&model));
    }
    for (unsigned index = 1; index <= stop_writes; index++) {
        fixture(&model, &state);
        CHECK(!fuxi_torch_steady_step(&io, &state, 4));
        model.fail_write = model.writes + index;
        CHECK(fuxi_torch_steady_step(&io, &state, 0) < 0 && state.failed && !active(&model));
    }
    static const unsigned faults[] = {6, 7, 9};
    for (unsigned index = 0; index < 3; index++) {
        fixture(&model, &state); model.registers[faults[index]] = 1;
        CHECK(fuxi_torch_steady_step(&io, &state, 1) < 0 && state.failed && !model.writes);
        fixture(&model, &state);
        CHECK(!fuxi_torch_steady_step(&io, &state, 4));
        model.registers[faults[index]] = 1;
        CHECK(fuxi_torch_steady_step(&io, &state, 4) < 0 && state.failed && !active(&model));
    }
    fixture(&model, &state); model.registers[0x46] |= 0x80;
    CHECK(fuxi_torch_steady_step(&io, &state, 4) == -2 && !model.writes);
    fixture(&model, &state); model.registers[0x4e] = 2;
    CHECK(fuxi_torch_steady_step(&io, &state, 4) == -2 && !model.writes);
    fixture(&model, &state); model.registers[4] = 0;
    CHECK(fuxi_torch_steady_step(&io, &state, 4) < 0 && !model.writes);
    fixture(&model, &state);
    CHECK(!fuxi_torch_steady_step(&io, &state, 4));
    model.drop_mask = (UINT64_C(1) << 7) | (UINT64_C(1) << 8);
    CHECK(fuxi_torch_steady_step(&io, &state, 0) == -6 && state.failed && active(&model));
    CHECK(model.writes == 8 && state.prepared);
    CHECK(fuxi_torch_steady_step(&io, &state, 4) < 0 && model.writes == 8);
}
int main(void) {
    steady_output();
    transitions_and_expiry();
    live_current_changes();
    failures();
    printf("PASS steady torch: %u checks; four 120s modeled holds and all level pairs without disable/re-enable; stop, lease expiry and injected failures\n", checks);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sanitize', action='store_true')
    arguments = parser.parse_args()
    tools = runpy.run_path(str(ROOT / 'tools/test-fuxi-audio-prep.py'))
    compiler, environment = tools['compiler_environment']()
    microsoft = Path(compiler[0].strip('"')).name.lower() in ('cl', 'cl.exe')
    with tempfile.TemporaryDirectory(prefix='fuxi-torch-steady-') as temporary:
        directory = Path(temporary)
        source = directory / 'steady.c'
        source.write_text(SOURCE, encoding='utf-8', newline='\n')
        binary = directory / ('steady.exe' if os.name == 'nt' else 'steady')
        if microsoft:
            flags = ['/nologo', '/std:c11', '/W4', '/WX', '/Zi', '/Od', '/MD']
            if arguments.sanitize:
                flags.append('/fsanitize=address')
            command = compiler + flags + [f'/I{ROOT / "xnu/fuxi-adsp"}', str(source), f'/Fe:{binary}']
        else:
            flags = ['-std=c11', '-g', '-Wall', '-Wextra', '-Werror', '-O1']
            if arguments.sanitize:
                flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            command = compiler + flags + ['-I', str(ROOT / 'xnu/fuxi-adsp'), str(source), '-o', str(binary)]
        subprocess.run(command, cwd=directory, env=environment, check=True, timeout=120)
        subprocess.run([str(binary)], cwd=directory, env=environment, check=True, timeout=60)


if __name__ == '__main__':
    main()
