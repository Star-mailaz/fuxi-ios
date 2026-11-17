#!/usr/bin/env python3
"""Compile and test the value-only five-clock lease ledger; no hardware I/O."""

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "xnu" / "fuxi-bt-clock-prep"
HARNESS = r'''
#include "fuxi_bt_clock_ledger.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

struct provider {
    unsigned refs[FUXI_BT_CLOCK_COUNT];
    unsigned acquired;
    unsigned released;
};

static void invariant(const struct fuxi_bt_clock_ledger *ledger)
{
    assert(!(ledger->acquired & ~FUXI_BT_CLOCK_ALL));
    assert(!(ledger->owned & ledger->released));
    assert((ledger->owned | ledger->released) == ledger->acquired);
    assert(ledger->retained == (ledger->owned | ledger->uncertain));
    assert(ledger->order_count <= FUXI_BT_CLOCK_COUNT);
    assert(ledger->survey_deferred);
    if (ledger->release_complete) {
        assert(!ledger->owned && !ledger->uncertain && !ledger->retained);
        assert(ledger->state == FUXI_BT_CLOCK_CLOSED);
    }
}

static void collect(struct fuxi_bt_clock_ledger *ledger, struct provider *provider,
    const enum fuxi_bt_clock_id *order, unsigned count)
{
    for (unsigned index = 0; index < count; index++) {
        enum fuxi_bt_clock_id clock = order[index];
        provider->refs[(unsigned)clock]++;
        provider->acquired++;
        assert(fuxi_bt_clock_ledger_acquire(ledger, clock, FUXI_BT_CLOCK_ACQUIRED,
            100u + (unsigned)clock, index + 1) == FUXI_BT_CLOCK_OK);
        invariant(ledger);
    }
}

static void release_all(struct fuxi_bt_clock_ledger *ledger, struct provider *provider, uint64_t now)
{
    enum fuxi_bt_clock_id clock;
    uint64_t token;
    assert(fuxi_bt_clock_ledger_release_begin(ledger, now) == FUXI_BT_CLOCK_OK);
    while (fuxi_bt_clock_ledger_next_release(ledger, &clock, &token) == FUXI_BT_CLOCK_AGAIN) {
        assert(token == 100u + (unsigned)clock);
        assert(provider->refs[(unsigned)clock]);
        provider->refs[(unsigned)clock]--;
        provider->released++;
        assert(fuxi_bt_clock_ledger_release(ledger, clock, FUXI_BT_CLOCK_RELEASED, ++now) == FUXI_BT_CLOCK_OK);
        invariant(ledger);
    }
    assert(ledger->release_complete && ledger->cleanup == FUXI_BT_CLOCK_OK);
}

static unsigned permutation_cases;

static void permutations(enum fuxi_bt_clock_id *order, unsigned count, uint32_t used)
{
    if (count != FUXI_BT_CLOCK_COUNT) {
        for (unsigned clock = 0; clock < FUXI_BT_CLOCK_COUNT; clock++) {
            if (!(used & (1u << clock))) {
                order[count] = (enum fuxi_bt_clock_id)clock;
                permutations(order, count + 1, used | (1u << clock));
            }
        }
        return;
    }
    for (unsigned foreign = 0; foreign < 8; foreign++) {
        struct provider provider = {0};
        struct fuxi_bt_clock_ledger ledger = {0};
        for (unsigned clock = 0; clock < FUXI_BT_CLOCK_COUNT; clock++) {
            provider.refs[clock] = foreign + clock;
        }
        assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
        collect(&ledger, &provider, order, FUXI_BT_CLOCK_COUNT);
        assert(ledger.state == FUXI_BT_CLOCK_READY);
        assert(fuxi_bt_clock_ledger_survey(&ledger) == FUXI_BT_CLOCK_DEFER);
        assert(fuxi_bt_clock_ledger_begin(&ledger, 0, 0) == FUXI_BT_CLOCK_BUSY);
        assert(fuxi_bt_clock_ledger_release_begin(&ledger, 10) == FUXI_BT_CLOCK_OK);
        for (unsigned index = FUXI_BT_CLOCK_COUNT; index; index--) {
            enum fuxi_bt_clock_id clock;
            uint64_t token;
            assert(fuxi_bt_clock_ledger_next_release(&ledger, &clock, &token) == FUXI_BT_CLOCK_AGAIN);
            assert(clock == order[index - 1] && token == 100u + (unsigned)clock);
            provider.refs[(unsigned)clock]--;
            provider.released++;
            assert(fuxi_bt_clock_ledger_release(&ledger, clock, FUXI_BT_CLOCK_RELEASED,
                20u - index) == FUXI_BT_CLOCK_OK);
            invariant(&ledger);
        }
        for (unsigned clock = 0; clock < FUXI_BT_CLOCK_COUNT; clock++) {
            assert(provider.refs[clock] == foreign + clock);
        }
        assert(provider.released == 5 && ledger.release_complete);
        assert(fuxi_bt_clock_ledger_release_begin(&ledger, 100) == FUXI_BT_CLOCK_OK);
        permutation_cases++;
    }
}

static void fault_cases(void)
{
    const enum fuxi_bt_clock_id order[] = {0, 1, 2, 3, 4};
    unsigned cases = 0;
    for (unsigned position = 0; position < FUXI_BT_CLOCK_COUNT; position++) {
        for (unsigned variant = 0; variant < 4; variant++) {
            struct fuxi_bt_clock_ledger ledger = {0};
            struct provider provider = {0};
            enum fuxi_bt_clock_acquire_result mode = variant < 2 ?
                (enum fuxi_bt_clock_acquire_result)(variant + 1) : FUXI_BT_CLOCK_ACQUIRE_AMBIGUOUS;
            assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
            collect(&ledger, &provider, order, position);
            if (mode == FUXI_BT_CLOCK_ACQUIRE_FAILED_HELD || variant == 3) {
                provider.refs[position]++;
                provider.acquired++;
            }
            assert(fuxi_bt_clock_ledger_acquire(&ledger, (enum fuxi_bt_clock_id)position,
                mode,
                mode == FUXI_BT_CLOCK_ACQUIRE_FAILED_HELD ? 100u + position : 0,
                position + 1) == (mode == FUXI_BT_CLOCK_ACQUIRE_AMBIGUOUS ? FUXI_BT_CLOCK_DEFER : FUXI_BT_CLOCK_IO));
            invariant(&ledger);
            if (mode == FUXI_BT_CLOCK_ACQUIRE_AMBIGUOUS) {
                assert(fuxi_bt_clock_ledger_release_begin(&ledger, 10) == FUXI_BT_CLOCK_DEFER);
                assert(ledger.state == FUXI_BT_CLOCK_RETAINED && !provider.released);
                assert(ledger.retained == ((1u << (position + 1)) - 1));
                for (unsigned clock = 0; clock < FUXI_BT_CLOCK_COUNT; clock++) {
                    assert(provider.refs[clock] == (unsigned)(clock < position || (clock == position && variant == 3)));
                }
            } else {
                release_all(&ledger, &provider, 10);
                assert(ledger.error == FUXI_BT_CLOCK_IO && provider.acquired == provider.released);
            }
            cases++;
        }
        for (unsigned variant = 0; variant < 3; variant++) {
            struct fuxi_bt_clock_ledger ledger = {0};
            struct provider provider = {0};
            enum fuxi_bt_clock_release_result mode = variant ?
                FUXI_BT_CLOCK_RELEASE_AMBIGUOUS : FUXI_BT_CLOCK_RELEASE_FAILED_HELD;
            enum fuxi_bt_clock_id clock;
            uint64_t token;
            assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
            collect(&ledger, &provider, order, FUXI_BT_CLOCK_COUNT);
            assert(fuxi_bt_clock_ledger_release_begin(&ledger, 10) == FUXI_BT_CLOCK_OK);
            for (unsigned index = 0; index < position; index++) {
                assert(fuxi_bt_clock_ledger_next_release(&ledger, &clock, &token) == FUXI_BT_CLOCK_AGAIN);
                provider.refs[(unsigned)clock]--;
                provider.released++;
                assert(fuxi_bt_clock_ledger_release(&ledger, clock, FUXI_BT_CLOCK_RELEASED, 11 + index) == FUXI_BT_CLOCK_OK);
            }
            assert(fuxi_bt_clock_ledger_next_release(&ledger, &clock, &token) == FUXI_BT_CLOCK_AGAIN);
            if (variant == 2) {
                provider.refs[(unsigned)clock]--;
                provider.released++;
            }
            assert(fuxi_bt_clock_ledger_release(&ledger, clock, mode,
                16) == (mode == FUXI_BT_CLOCK_RELEASE_AMBIGUOUS ? FUXI_BT_CLOCK_DEFER : FUXI_BT_CLOCK_IO));
            assert(ledger.state == FUXI_BT_CLOCK_RETAINED && !ledger.release_complete);
            assert(fuxi_bt_clock_ledger_next_release(&ledger, &clock, &token) == FUXI_BT_CLOCK_ARGUMENT);
            assert(provider.released == position + (unsigned)(variant == 2));
            assert(ledger.retained == ((1u << (FUXI_BT_CLOCK_COUNT - position)) - 1));
            assert(fuxi_bt_clock_ledger_release_begin(&ledger, 17) == FUXI_BT_CLOCK_ARGUMENT);
            invariant(&ledger);
            cases++;
        }
    }
    assert(cases == 35);
    puts("PASS 35 acquisition/release failure-position/effect cases; before/after ambiguity retains dependency refs without retry");
}

static void guards_and_budgets(void)
{
    struct fuxi_bt_clock_ledger ledger = {0};
    struct fuxi_bt_clock_ledger before;
    const enum fuxi_bt_clock_id order[] = {0, 1, 2, 3, 4};
    struct provider provider = {0};
    assert(fuxi_bt_clock_ledger_begin(NULL, 0, 0) == FUXI_BT_CLOCK_ARGUMENT);
    assert(fuxi_bt_clock_ledger_begin(&ledger, 0, 0) == FUXI_BT_CLOCK_OFF);
    assert(fuxi_bt_clock_ledger_survey(&ledger) == FUXI_BT_CLOCK_OFF);
    assert(fuxi_bt_clock_ledger_acquire(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_ACQUIRED,
        1, 0) == FUXI_BT_CLOCK_OFF);
    assert(fuxi_bt_clock_ledger_begin(&ledger, 2, 0) == FUXI_BT_CLOCK_ARGUMENT);
    assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
    collect(&ledger, &provider, order, 1);
    before = ledger;
    assert(fuxi_bt_clock_ledger_acquire(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_ACQUIRED,
        1, 1) == FUXI_BT_CLOCK_ARGUMENT);
    assert(!memcmp(&ledger, &before, sizeof(ledger)));
    assert(fuxi_bt_clock_ledger_acquire(&ledger, (enum fuxi_bt_clock_id)5, FUXI_BT_CLOCK_ACQUIRED,
        1, 1) == FUXI_BT_CLOCK_ARGUMENT);
    assert(fuxi_bt_clock_ledger_release_begin(&ledger, 10) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_release(&ledger, FUXI_BT_CLOCK_SE6, FUXI_BT_CLOCK_RELEASED,
        11) == FUXI_BT_CLOCK_ARGUMENT);
    assert(fuxi_bt_clock_ledger_release(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_RELEASED,
        11) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_release(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_RELEASED,
        12) == FUXI_BT_CLOCK_ARGUMENT);
    ledger = (struct fuxi_bt_clock_ledger){0};
    assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_acquire(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_ACQUIRED,
        100, 1) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_tick(&ledger, FUXI_BT_CLOCK_TIMEOUT_US) == FUXI_BT_CLOCK_TIMEOUT);
    release_all(&ledger, &provider, FUXI_BT_CLOCK_TIMEOUT_US);
    assert(ledger.error == FUXI_BT_CLOCK_TIMEOUT);
    assert(fuxi_bt_clock_ledger_begin(&ledger, 1, UINT64_MAX - 50) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_tick(&ledger, UINT64_MAX) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_tick(&ledger, 0) == FUXI_BT_CLOCK_TIME_REVERSED);
    assert(fuxi_bt_clock_ledger_release_begin(&ledger, 0) == FUXI_BT_CLOCK_TIME_REVERSED);
    assert(!ledger.release_complete);
    ledger = (struct fuxi_bt_clock_ledger){0};
    assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
    for (unsigned index = 1; index < FUXI_BT_CLOCK_MAX_STEPS; index++) {
        assert(fuxi_bt_clock_ledger_tick(&ledger, 0) == FUXI_BT_CLOCK_OK);
    }
    assert(fuxi_bt_clock_ledger_tick(&ledger, 0) == FUXI_BT_CLOCK_TIMEOUT);
    assert(fuxi_bt_clock_ledger_release_begin(&ledger, 0) == FUXI_BT_CLOCK_OK && ledger.release_complete);
    ledger = (struct fuxi_bt_clock_ledger){0};
    assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_acquire(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_ACQUIRED,
        100, FUXI_BT_CLOCK_TIMEOUT_US) == FUXI_BT_CLOCK_TIMEOUT);
    assert(ledger.owned == 1 && ledger.tokens[0] == 100);
    assert(fuxi_bt_clock_ledger_release_begin(&ledger, FUXI_BT_CLOCK_TIMEOUT_US) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_release(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_RELEASED,
        2u * FUXI_BT_CLOCK_TIMEOUT_US) == FUXI_BT_CLOCK_TIMEOUT);
    assert(!ledger.owned && ledger.released == 1 && !ledger.release_complete);
    assert(ledger.state == FUXI_BT_CLOCK_RETAINED);
    ledger = (struct fuxi_bt_clock_ledger){0};
    assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_acquire(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_ACQUIRED,
        0, 1) == FUXI_BT_CLOCK_DEFER);
    assert(ledger.acquired == 1 && ledger.uncertain == 1);
    assert(fuxi_bt_clock_ledger_release_begin(&ledger, 1) == FUXI_BT_CLOCK_DEFER);
    invariant(&ledger);
    ledger = (struct fuxi_bt_clock_ledger){0};
    assert(fuxi_bt_clock_ledger_begin(&ledger, 1, 0) == FUXI_BT_CLOCK_OK);
    assert(fuxi_bt_clock_ledger_acquire(&ledger, FUXI_BT_CLOCK_CORE, FUXI_BT_CLOCK_ACQUIRE_FAILED_NONE,
        777, 1) == FUXI_BT_CLOCK_DEFER);
    assert(ledger.tokens[0] == 777 && !ledger.acquired && ledger.uncertain == 1);
    assert(fuxi_bt_clock_ledger_release_begin(&ledger, 1) == FUXI_BT_CLOCK_DEFER);
    invariant(&ledger);
    puts("PASS default-off, duplicate/out-of-range guards, elapsed/frozen/backwards time and late side-effect accounting");
}

static void transition_cases(void)
{
    struct fuxi_bt_clock_ledger ledger = {0};
    uint32_t random = 0x85507850u;
    uint64_t now = 0;
    assert(fuxi_bt_clock_ledger_begin(&ledger, 0, 0) == FUXI_BT_CLOCK_OFF);
    for (unsigned step = 0; step < 100000; step++) {
        enum fuxi_bt_clock_id clock;
        uint64_t token;
        if (!(step % 32u)) {
            ledger = (struct fuxi_bt_clock_ledger){0};
            assert(fuxi_bt_clock_ledger_begin(&ledger, 1, now) == FUXI_BT_CLOCK_OK);
        }
        random = random * 1664525u + 1013904223u;
        now += random & 1023u;
        switch ((random >> 16) % 7u) {
        case 0:
            (void)fuxi_bt_clock_ledger_begin(&ledger, (random >> 8) % 3u, now);
            break;
        case 1:
            (void)fuxi_bt_clock_ledger_tick(&ledger, random & 0x10000u ? 0 : now);
            break;
        case 2:
            (void)fuxi_bt_clock_ledger_acquire(&ledger, (enum fuxi_bt_clock_id)((random >> 8) % 8u),
                (enum fuxi_bt_clock_acquire_result)((random >> 12) % 6u), random & 1u ? random : 0, now);
            break;
        case 3:
            (void)fuxi_bt_clock_ledger_survey(&ledger);
            break;
        case 4:
            (void)fuxi_bt_clock_ledger_release_begin(&ledger, now);
            break;
        case 5:
            (void)fuxi_bt_clock_ledger_next_release(&ledger, &clock, &token);
            break;
        case 6:
            (void)fuxi_bt_clock_ledger_release(&ledger, (enum fuxi_bt_clock_id)((random >> 8) % 8u),
                (enum fuxi_bt_clock_release_result)((random >> 12) % 5u), now);
            break;
        }
        invariant(&ledger);
    }
    puts("PASS 100000 deterministic API/state transitions with malformed IDs/results and monotonic/rollback times");
}

int main(void)
{
    enum fuxi_bt_clock_id order[FUXI_BT_CLOCK_COUNT];
    permutations(order, 0, 0);
    assert(permutation_cases == 960);
    puts("PASS 960 order/foreign-owner combinations; reverse own-lease release leaves shared refs unchanged");
    fault_cases();
    guards_and_budgets();
    transition_cases();
    puts("PASS value-only clock ledger; engine survey is always deferred, no MMIO or resource callbacks exist");
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--cc", nargs="+")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    specification = importlib.util.spec_from_file_location(
        "fuxi_bt_clock_host_compiler", ROOT / "tools" / "test-fuxi-bluetooth.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    compiler, environment = module.compiler_configuration(args.cc)
    msvc = Path(compiler[0]).name.lower() in ("cl", "cl.exe")
    if msvc and args.sanitize:
        raise SystemExit("--sanitize requires Clang/GCC ASan and UBSan.")
    with tempfile.TemporaryDirectory(prefix="fuxi-bt-clock-") as temporary:
        directory = Path(temporary)
        harness = directory / "ledger-model.c"
        harness.write_text(HARNESS, encoding="utf-8")
        executable = directory / ("ledger-model.exe" if os.name == "nt" else "ledger-model")
        if msvc:
            command = compiler + ["/nologo", "/std:c11", "/W4", "/WX", "/Od",
                f"/I{SOURCE}", str(SOURCE / "fuxi_bt_clock_ledger.c"), str(harness), f"/Fe{executable}"]
        else:
            command = compiler + ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-I", str(SOURCE), str(SOURCE / "fuxi_bt_clock_ledger.c"), str(harness), "-o", str(executable)]
            if args.sanitize:
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        subprocess.run(command, cwd=directory, env=environment, check=True, timeout=120)
        subprocess.run([str(executable)], cwd=directory, env=environment, check=True, timeout=30)
        print(f"Compiler {compiler[0]}; sanitizers {'ASan/UBSan' if args.sanitize else 'disabled'}")


if __name__ == "__main__":
    main()
