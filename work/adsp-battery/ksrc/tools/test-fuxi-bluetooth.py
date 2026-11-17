#!/usr/bin/env python3
"""Compile and run the production BT protocol and snapshot with synthetic I/O."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "xnu" / "fuxi-bluetooth"

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "fuxi_bt.h"

static const uint8_t good_reply[] = {
    4, 0x0e, 18, 1, 0, 0xfc, 0, 0x19, 0,
    0x78, 0x56, 0x34, 0x12, 0xbc, 0x9a, 0x20, 0,
    0x44, 0x33, 0x22, 0x11
};
static const uint8_t good_command[] = {1, 0, 0xfc, 1, 0x19};

struct fake_uart {
    struct fuxi_bt_uart_ops ops;
    uint8_t response[8192];
    size_t response_size;
    size_t response_offset;
    unsigned chunk;
    unsigned tx_chunk;
    unsigned acquisitions;
    unsigned releases;
    unsigned writes;
    unsigned reads;
    unsigned waits;
    unsigned drained;
    unsigned stale_size;
    unsigned stale_offset;
    unsigned tx_size;
    uint8_t tx[5];
    uint64_t clock;
    uint64_t read_delay;
    uint64_t acquire_delay;
    enum fuxi_bt_status acquire_status;
    enum fuxi_bt_status read_status;
    enum fuxi_bt_status write_status;
    enum fuxi_bt_status release_status;
    bool stuck_clock;
    bool backwards_clock;
    bool over_read;
    bool over_write;
    bool error_count;
    bool tx_stalled;
    bool continuous_stale;
};

static enum fuxi_bt_status fake_acquire(void *context, unsigned baud)
{
    struct fake_uart *uart = context;
    assert(baud == 115200);
    uart->acquisitions++;
    uart->clock += uart->acquire_delay;
    return uart->acquire_status;
}

static enum fuxi_bt_status fake_release(void *context)
{
    struct fake_uart *uart = context;
    uart->releases++;
    return uart->release_status;
}

static enum fuxi_bt_status fake_write(void *context, const uint8_t *bytes,
    size_t capacity, size_t *count)
{
    struct fake_uart *uart = context;
    uart->writes++;
    if (uart->over_write) {
        *count = capacity + 1;
        return FUXI_BT_OK;
    }
    if (uart->write_status != FUXI_BT_OK) {
        *count = uart->error_count ? 1 : 0;
        return uart->write_status;
    }
    if (uart->tx_stalled) {
        *count = 0;
        return FUXI_BT_OK;
    }
    *count = capacity < uart->tx_chunk ? capacity : uart->tx_chunk;
    assert(*count <= sizeof(uart->tx) - uart->tx_size);
    memcpy(uart->tx + uart->tx_size, bytes, *count);
    uart->tx_size += (unsigned)*count;
    assert(!memcmp(uart->tx, good_command, uart->tx_size));
    return FUXI_BT_OK;
}

static enum fuxi_bt_status fake_read(void *context, uint8_t *bytes,
    size_t capacity, size_t *count)
{
    struct fake_uart *uart = context;
    uart->reads++;
    if (uart->tx_size != sizeof(good_command)) {
        size_t stale = uart->stale_size - uart->stale_offset;
        if (uart->continuous_stale) {
            stale = capacity;
        }
        *count = stale < capacity ? stale : capacity;
        memset(bytes, 0xfe, *count);
        uart->stale_offset += (unsigned)*count;
        if (uart->continuous_stale) {
            uart->stale_size = uart->stale_offset;
        }
        uart->drained += (unsigned)*count;
        return FUXI_BT_OK;
    }
    uart->clock += uart->read_delay;
    if (uart->over_read) {
        *count = capacity + 1;
        return FUXI_BT_OK;
    }
    if (uart->read_status != FUXI_BT_OK) {
        *count = uart->error_count ? 1 : 0;
        return uart->read_status;
    }
    *count = uart->response_size - uart->response_offset;
    if (*count > uart->chunk) {
        *count = uart->chunk;
    }
    if (*count > capacity) {
        *count = capacity;
    }
    memcpy(bytes, uart->response + uart->response_offset, *count);
    uart->response_offset += *count;
    return FUXI_BT_OK;
}

static uint64_t fake_now(void *context)
{
    struct fake_uart *uart = context;
    return uart->clock;
}

static void fake_wait(void *context, unsigned usec)
{
    struct fake_uart *uart = context;
    assert(usec == 1000);
    uart->waits++;
    if (uart->backwards_clock) {
        uart->clock--;
    } else if (!uart->stuck_clock) {
        uart->clock += usec;
    }
}

static void fake_init(struct fake_uart *uart)
{
    memset(uart, 0, sizeof(*uart));
    uart->ops.context = uart;
    uart->ops.acquire = fake_acquire;
    uart->ops.release = fake_release;
    uart->ops.write = fake_write;
    uart->ops.read = fake_read;
    uart->ops.now_us = fake_now;
    uart->ops.wait_us = fake_wait;
    uart->chunk = 64;
    uart->tx_chunk = 5;
    uart->clock = 100;
    memcpy(uart->response, good_reply, sizeof(good_reply));
    uart->response_size = sizeof(good_reply);
}

static void expect_probe(struct fake_uart *uart, enum fuxi_bt_status expected,
    struct fuxi_bt_result *result)
{
    const enum fuxi_bt_status actual = fuxi_bt_probe_run(1, &uart->ops, result);
    if (actual != expected) {
        fprintf(stderr, "expected=%s actual=%s rx_chunk=%u tx_chunk=%u response_size=%zu rx=%u tx=%u drained=%u polls=%u\n",
            fuxi_bt_status_name(expected), fuxi_bt_status_name(actual),
            uart->chunk, uart->tx_chunk, uart->response_size,
            result->rx_bytes, result->tx_bytes, result->drained_bytes, result->polls);
    }
    assert(actual == expected);
    assert(result->status == expected);
    assert(uart->acquisitions == 1 && uart->releases == 1);
    assert(result->tx_bytes <= 5);
    assert(result->rx_bytes <= FUXI_BT_MAX_RX);
    assert(result->drained_bytes <= FUXI_BT_MAX_DRAIN);
    assert(result->polls <= FUXI_BT_MAX_POLLS);
}

static void test_protocol(void)
{
    struct fake_uart uart;
    struct fuxi_bt_result result;
    fake_init(&uart);
    assert(fuxi_bt_probe_run(0, &uart.ops, &result) == FUXI_BT_OFF);
    assert(!uart.acquisitions && !uart.reads && !uart.writes && !uart.releases);
    assert(fuxi_bt_probe_run(2, &uart.ops, &result) == FUXI_BT_ARGUMENT);
    assert(fuxi_bt_probe_run(1, NULL, &result) == FUXI_BT_NO_UART);
    assert(fuxi_bt_probe_run(1, &uart.ops, NULL) == FUXI_BT_ARGUMENT);
    uart.ops.wait_us = NULL;
    assert(fuxi_bt_probe_run(1, &uart.ops, &result) == FUXI_BT_NO_UART);
    assert(!uart.acquisitions);

    for (unsigned chunk = 1; chunk <= 64; chunk++) {
        for (unsigned tx_chunk = 1; tx_chunk <= 5; tx_chunk++) {
            fake_init(&uart);
            uart.chunk = chunk;
            uart.tx_chunk = tx_chunk;
            expect_probe(&uart, FUXI_BT_OK, &result);
            assert(result.version_valid && result.tx_bytes == 5);
            assert(result.version.product == 0x12345678);
            assert(result.version.soc == 0x11223344);
            assert(result.version.patch == 0x9abc && result.version.rom == 0x20);
            assert(result.reply_size == 21 && !memcmp(result.reply, good_reply, 21));
        }
    }
    for (unsigned length = 0; length < sizeof(good_reply); length++) {
        fake_init(&uart);
        uart.response_size = length;
        expect_probe(&uart, FUXI_BT_TIMEOUT, &result);
        assert(!result.version_valid);
    }
    /* event[8] follows Linux btqca and is skipped: the WCN7850 sends 0x0c, and no value changes the version. */
    for (unsigned value = 0; value < 256; value += 0x0c) {
        fake_init(&uart);
        uart.response[8] = (uint8_t)value;
        expect_probe(&uart, FUXI_BT_OK, &result);
        assert(result.version_valid && result.controller_status == 0);
        assert(result.version.product == 0x12345678 && result.version.soc == 0x11223344);
        assert(result.reply_size == 21 && result.reply[8] == value);
    }
    for (unsigned field = 6; field <= 7; field++) {
        fake_init(&uart);
        uart.response[field] ^= 1;
        expect_probe(&uart, FUXI_BT_PROTOCOL, &result);
    }
    fake_init(&uart);
    uart.response[2] = 17;
    uart.response_size = 20;
    expect_probe(&uart, FUXI_BT_PROTOCOL, &result);
    fake_init(&uart);
    memset(uart.response + 17, 0, 4);
    expect_probe(&uart, FUXI_BT_VERSION, &result);
    fake_init(&uart);
    memset(uart.response + 15, 0, 2);
    expect_probe(&uart, FUXI_BT_VERSION, &result);
    fake_init(&uart);
    uart.response[4] = 3;
    expect_probe(&uart, FUXI_BT_TIMEOUT, &result);
    assert(result.ignored_frames == 1);
    fake_init(&uart);
    memcpy(uart.response, (uint8_t[]){4, 0x0f, 4, 0x12, 1, 0, 0xfc}, 7);
    uart.response_size = 7;
    expect_probe(&uart, FUXI_BT_CONTROLLER, &result);
    assert(result.controller_status == 0x12);
    fake_init(&uart);
    memmove(uart.response + 7, uart.response, uart.response_size);
    memcpy(uart.response, (uint8_t[]){4, 0x0f, 4, 0, 1, 0, 0xfc}, 7);
    uart.response_size += 7;
    uart.chunk = 1;
    expect_probe(&uart, FUXI_BT_OK, &result);
    assert(result.frames == 2 && result.ignored_frames == 1);
    fake_init(&uart);
    memcpy(uart.response, (uint8_t[]){4, 0x0e, 4, 1, 0, 0xfc, 1}, 7);
    uart.response_size = 7;
    expect_probe(&uart, FUXI_BT_CONTROLLER, &result);
    fake_init(&uart);
    memcpy(uart.response, (uint8_t[]){4, 0xff, 2, 0, 2}, 5);
    uart.response_size = 5;
    expect_probe(&uart, FUXI_BT_LEGACY, &result);
    for (unsigned byte = 0xfc; byte <= 0xfe; byte++) {
        fake_init(&uart);
        uart.response[0] = (uint8_t)byte;
        uart.response_size = 1;
        expect_probe(&uart, FUXI_BT_IBS, &result);
    }
    fake_init(&uart);
    uart.response[0] = 0;
    expect_probe(&uart, FUXI_BT_PROTOCOL, &result);
    fake_init(&uart);
    memmove(uart.response + 18, uart.response, uart.response_size);
    memcpy(uart.response, (uint8_t[]){
        2, 1, 0, 2, 0, 0xfd, 4,
        3, 1, 0, 1, 0xfc,
        5, 1, 0, 1, 0xc0, 0xfe
    }, 18);
    uart.response_size += 18;
    uart.chunk = 1;
    expect_probe(&uart, FUXI_BT_OK, &result);
    assert(result.frames == 4 && result.ignored_frames == 3);
    fake_init(&uart);
    memcpy(uart.response, (uint8_t[]){2, 1, 0, 0xff, 0xff}, 5);
    uart.response_size = 5;
    expect_probe(&uart, FUXI_BT_BUDGET, &result);
    fake_init(&uart);
    for (unsigned frame = 0; frame < 65; frame++) {
        memcpy(uart.response + frame * 3, (uint8_t[]){4, 0xff, 0}, 3);
    }
    uart.response_size = 65 * 3;
    expect_probe(&uart, FUXI_BT_BUDGET, &result);
    fake_init(&uart);
    memset(uart.response, 0, sizeof(uart.response));
    memcpy(uart.response, (uint8_t[]){2, 1, 0, 0, 0x10}, 5);
    uart.response_size = 4101;
    expect_probe(&uart, FUXI_BT_BUDGET, &result);
    assert(uart.response_offset == FUXI_BT_MAX_RX);
}

static void test_transport(void)
{
    struct fake_uart uart;
    struct fuxi_bt_result result;
    fake_init(&uart);
    uart.stale_size = 21;
    expect_probe(&uart, FUXI_BT_OK, &result);
    assert(result.drained_bytes == 21);
    fake_init(&uart);
    uart.stale_size = 1023;
    expect_probe(&uart, FUXI_BT_OK, &result);
    assert(result.drained_bytes == 1023);
    fake_init(&uart);
    uart.stale_size = 1024;
    expect_probe(&uart, FUXI_BT_BUDGET, &result);
    assert(result.drained_bytes == 1024 && uart.drained == 1024);
    assert(!uart.writes);
    fake_init(&uart);
    uart.continuous_stale = true;
    expect_probe(&uart, FUXI_BT_BUDGET, &result);
    assert(!uart.writes);
    fake_init(&uart);
    uart.acquire_status = FUXI_BT_BUSY;
    expect_probe(&uart, FUXI_BT_BUSY, &result);
    assert(!uart.writes && !uart.reads);
    fake_init(&uart);
    uart.acquire_delay = FUXI_BT_TIMEOUT_US;
    expect_probe(&uart, FUXI_BT_TIMEOUT, &result);
    assert(!uart.writes);
    fake_init(&uart);
    uart.over_write = true;
    expect_probe(&uart, FUXI_BT_IO, &result);
    fake_init(&uart);
    uart.over_read = true;
    expect_probe(&uart, FUXI_BT_IO, &result);
    fake_init(&uart);
    uart.write_status = FUXI_BT_IO;
    expect_probe(&uart, FUXI_BT_IO, &result);
    fake_init(&uart);
    uart.read_status = FUXI_BT_IO;
    expect_probe(&uart, FUXI_BT_IO, &result);
    fake_init(&uart);
    uart.write_status = FUXI_BT_AGAIN;
    uart.error_count = true;
    expect_probe(&uart, FUXI_BT_IO, &result);
    fake_init(&uart);
    uart.read_status = FUXI_BT_AGAIN;
    uart.error_count = true;
    expect_probe(&uart, FUXI_BT_IO, &result);
    fake_init(&uart);
    uart.tx_stalled = true;
    expect_probe(&uart, FUXI_BT_TIMEOUT, &result);
    assert(result.elapsed_us == FUXI_BT_TIMEOUT_US);
    fake_init(&uart);
    uart.stuck_clock = true;
    uart.response_size = 0;
    expect_probe(&uart, FUXI_BT_TIMEOUT, &result);
    assert(result.polls == FUXI_BT_MAX_POLLS);
    fake_init(&uart);
    uart.backwards_clock = true;
    uart.response_size = 0;
    expect_probe(&uart, FUXI_BT_IO, &result);
    fake_init(&uart);
    uart.read_delay = FUXI_BT_TIMEOUT_US;
    expect_probe(&uart, FUXI_BT_TIMEOUT, &result);
    assert(!result.version_valid);
    fake_init(&uart);
    uart.release_status = FUXI_BT_IO;
    expect_probe(&uart, FUXI_BT_CLEANUP, &result);
    assert(result.version_valid && result.cleanup == FUXI_BT_IO);
    fake_init(&uart);
    uart.acquire_status = FUXI_BT_IO;
    uart.release_status = FUXI_BT_BUSY;
    expect_probe(&uart, FUXI_BT_IO, &result);
    assert(result.cleanup == FUXI_BT_BUSY);
    fake_init(&uart);
    expect_probe(&uart, FUXI_BT_OK, &result);
    fake_init(&uart);
    expect_probe(&uart, FUXI_BT_OK, &result);
}

struct fake_mmio {
    unsigned off_mask;
    unsigned accesses;
    unsigned engine_accesses;
    unsigned fail_at;
    bool hardware_control;
    bool interface_seen;
};

static enum fuxi_bt_status fake_read32(void *context, uint64_t pa, uint32_t *value)
{
    static const uint32_t branches[] = {0x233d4, 0x233d0, 0x233cc, 0x23004, 0x1e754};
    struct fake_mmio *mmio = context;
    mmio->accesses++;
    if (mmio->fail_at == mmio->accesses) {
        return FUXI_BT_IO;
    }
    *value = 0;
    for (unsigned index = 0; index < 5; index++) {
        if (pa == FUXI_BT_GCC_BASE + branches[index]) {
            if (mmio->off_mask & (1u << index)) {
                *value = 1u << 31;
            }
            if (mmio->hardware_control) {
                *value |= 2;
            }
        }
    }
    if (pa >= FUXI_BT_UART_BASE && pa < FUXI_BT_UART_BASE + 0x4000) {
        assert(!mmio->off_mask);
        mmio->engine_accesses++;
        assert(pa != FUXI_BT_UART_BASE + 0x2004);
        if (pa == FUXI_BT_UART_BASE + 0x64) {
            mmio->interface_seen = true;
        }
    }
    if (pa >= FUXI_BT_WRAPPER_BASE && pa < FUXI_BT_WRAPPER_BASE + 0x4000) {
        assert(!mmio->off_mask);
        mmio->engine_accesses++;
    }
    return FUXI_BT_OK;
}

static void test_snapshot(void)
{
    struct fake_mmio mmio;
    struct fuxi_bt_snapshot snapshot;
    for (unsigned mask = 0; mask < 32; mask++) {
        for (unsigned control = 0; control < 2; control++) {
            memset(&mmio, 0, sizeof(mmio));
            mmio.off_mask = mask;
            mmio.hardware_control = control != 0;
            assert(fuxi_bt_snapshot_read(fake_read32, &mmio, &snapshot) == FUXI_BT_OK);
            assert(snapshot.off_mask == mask);
            assert(snapshot.engine_read == (mask == 0));
            assert(mmio.engine_accesses == (mask == 0 ? 6u : 0u));
            assert(mmio.interface_seen == (mask == 0));
        }
    }
    for (unsigned failure = 1; failure <= 35; failure++) {
        memset(&mmio, 0, sizeof(mmio));
        mmio.fail_at = failure;
        assert(fuxi_bt_snapshot_read(fake_read32, &mmio, &snapshot) == FUXI_BT_IO);
        assert(!snapshot.engine_read && mmio.accesses == failure);
    }
    assert(fuxi_bt_snapshot_read(NULL, &mmio, &snapshot) == FUXI_BT_ARGUMENT);
    assert(fuxi_bt_snapshot_read(fake_read32, &mmio, NULL) == FUXI_BT_ARGUMENT);
}

static void test_fuzz(void)
{
    struct fake_uart uart;
    struct fuxi_bt_result result;
    uint32_t random_state = 0x85507850;
    for (unsigned trial = 0; trial < 10000; trial++) {
        fake_init(&uart);
        uart.stuck_clock = true;
        uart.response_size = trial % 1024;
        uart.chunk = trial % 64 + 1;
        for (size_t index = 0; index < uart.response_size; index++) {
            random_state ^= random_state << 13;
            random_state ^= random_state >> 17;
            random_state ^= random_state << 5;
            uart.response[index] = (uint8_t)random_state;
        }
        (void)fuxi_bt_probe_run(1, &uart.ops, &result);
        assert(uart.acquisitions == 1 && uart.releases == 1);
        assert(result.polls <= FUXI_BT_MAX_POLLS);
        assert(result.rx_bytes <= FUXI_BT_MAX_RX);
        assert(result.tx_bytes <= 5);
    }
}

int main(void)
{
    test_protocol();
    test_transport();
    test_snapshot();
    test_fuzz();
    assert(!strcmp(fuxi_bt_status_name(FUXI_BT_OK), "ok"));
    assert(!strcmp(fuxi_bt_status_name((enum fuxi_bt_status)99), "unknown"));
    puts("PASS production C: 320 RX/TX fragment combinations, truncated/legacy/IBS replies, H4 ACL/SCO/ISO framing, time/byte/frame bounds, partial-acquire cleanup, 64 clock-gate combinations, 35 MMIO faults, 10000 deterministic fuzz inputs");
    return 0;
}
'''


def compiler_configuration(explicit):
    environment = dict(os.environ)
    if explicit:
        return explicit, environment
    for name in ("clang", "gcc", "cc"):
        compiler = shutil.which(name)
        if compiler:
            return [compiler], environment
    compiler = shutil.which("cl")
    if compiler:
        return [compiler], environment
    installer = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    vswhere = installer / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if os.name == "nt" and vswhere.exists():
        installation = subprocess.check_output([
            str(vswhere), "-latest", "-products", "*", "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property", "installationPath"
        ], text=True).strip()
        if installation:
            setup = Path(installation) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
            output = subprocess.check_output(
                f'cmd.exe /d /s /c ""{setup}" >nul && set"',
                text=True, errors="replace")
            for line in output.splitlines():
                if "=" in line and not line.startswith("="):
                    name, value = line.split("=", 1)
                    environment[name] = value
            compiler = shutil.which("cl", path=environment.get("Path", environment.get("PATH")))
            if compiler:
                return [compiler], environment
    raise SystemExit("A C11 compiler is required. Pass --cc COMPILER [ARG ...].")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--cc", nargs="+")
    args = parser.parse_args()
    compiler, environment = compiler_configuration(args.cc)
    msvc = Path(compiler[0]).name.lower() in ("cl", "cl.exe")
    if msvc and args.sanitize:
        raise SystemExit("--sanitize requires Clang or GCC with ASan and UBSan.")
    with tempfile.TemporaryDirectory(prefix="fuxi-bluetooth-") as temporary:
        directory = Path(temporary)
        harness = directory / "test.c"
        harness.write_text(HARNESS, encoding="utf-8")
        executable = directory / ("test.exe" if os.name == "nt" else "test")
        if msvc:
            command = compiler + [
                "/nologo", "/std:c11", "/W4", "/WX", "/Od", "/D_CRT_SECURE_NO_WARNINGS",
                f"/I{SOURCE}", str(SOURCE / "fuxi_bt.c"), str(harness),
                f"/Fe{executable}"
            ]
        else:
            command = compiler + [
                "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-I", str(SOURCE), str(SOURCE / "fuxi_bt.c"), str(harness),
                "-o", str(executable)
            ]
            if args.sanitize:
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        subprocess.run(command, cwd=directory, env=environment, check=True)
        subprocess.run([str(executable)], cwd=directory, env=environment, check=True, timeout=60)
        print(f"Compiler {compiler[0]}")
        print(f"Sanitizers {'ASan/UBSan' if args.sanitize else 'disabled'}")


if __name__ == "__main__":
    main()
