#!/usr/bin/env python3
"""Exercise the production XNU entry using host declarations and simulated MMIO."""

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "xnu" / "fuxi-bluetooth"

STUBS = r'''
#include <stdlib.h>
#include <stdarg.h>
#include "fuxi_bt_board.h"
#ifdef _MSC_VER
#include <intrin.h>
#define __ATOMIC_ACQUIRE 0
#define __ATOMIC_RELEASE 0
#define __ATOMIC_ACQ_REL 0
static bool test_atomic_compare(unsigned *target, unsigned *expected, unsigned value)
{
    const unsigned previous = (unsigned)_InterlockedCompareExchange(
        (volatile long *)target, (long)value, (long)*expected);
    if (previous == *expected) {
        return true;
    }
    *expected = previous;
    return false;
}
#define __atomic_compare_exchange_n(target, expected, value, weak, success, failure) test_atomic_compare(target, expected, value)
#define __atomic_store_n(target, value, order) ((void)_InterlockedExchange((volatile long *)(target), (long)(value)))
#define __atomic_load_n(target, order) ((unsigned)_InterlockedCompareExchange((volatile long *)(target), 0, 0))
#endif

#define FUXI 1
typedef int kern_return_t;
typedef void *pmap_t;
typedef void *vm_map_t;
typedef uintptr_t vm_map_offset_t;
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef int vm_prot_t;
typedef int boolean_t;
typedef int wait_result_t;
typedef void *thread_t;
typedef void (*thread_continue_t)(void *, wait_result_t);
#define KERN_SUCCESS 0
#define PAGE_SIZE 16384u
#define PAGE_MASK 16383u
#define KMA_VAONLY 1u
#define KMA_KOBJECT 2u
#define KMA_NOPAGEWAIT 4u
#define VM_KERN_MEMORY_IOKIT 1u
#define VM_PROT_READ 1u
#define VM_PROT_WRITE 2u
#define VM_PROT_NONE 0u
#define VM_WIMG_IO 7u
#define TRUE 1
#define PMAP_OPTIONS_NOWAIT 1u
static vm_map_t kernel_map;
static pmap_t kernel_pmap;
static int test_boot_mode;
static bool test_arg_present;
static bool test_thread_fail;
static unsigned test_threads;
static unsigned test_thread_refs;
static unsigned test_terminations;
static unsigned test_allocations;
static unsigned test_frees;
static unsigned test_maps;
static unsigned test_mmio;
static unsigned test_engine_mmio;
static unsigned test_off_mask;
static unsigned test_alloc_failure;
static unsigned test_map_failure;
static unsigned test_read_failure;
static char test_log[16384];
static size_t test_log_size;
struct test_page {
    uintptr_t address;
    uint64_t pa;
};
static struct test_page test_pages[32];
struct test_written_reg {
    uint64_t pa;
    uint32_t value;
};
static struct test_written_reg test_written[32];
static unsigned test_written_count;
static unsigned test_writes;
static uint64_t test_clock_us;
static unsigned test_wlan; /* 0 一直低、1 一直高、2 先高 10 秒、低 2 秒、再高 */
static bool test_gpll0_ok;
static bool test_adt_present;
static uint32_t test_adt_value;
static unsigned test_adt_size;
static unsigned test_adt_lookups;

typedef const void *DTEntry;
#define kSuccess 0
static int SecureDTLookupEntry(const void *root, const char *path, DTEntry *entry)
{
    assert(!root && !strcmp(path, "/chosen") && entry);
    test_adt_lookups++;
    *entry = &test_adt_value;
    return kSuccess;
}

static int SecureDTGetProperty(DTEntry entry, const char *name, const void **value, unsigned int *size)
{
    assert(entry == &test_adt_value && !strcmp(name, "fuxi,bt"));
    if (!test_adt_present) {
        return 1;
    }
    *value = &test_adt_value;
    *size = test_adt_size;
    return kSuccess;
}

static void clock_get_uptime(uint64_t *absolute)
{
    *absolute = test_clock_us * 3u;
}

static void absolutetime_to_nanoseconds(uint64_t absolute, uint64_t *nanoseconds)
{
    *nanoseconds = absolute / 3u * 1000u;
}

static void delay(int microseconds)
{
    assert(microseconds > 0);
    test_clock_us += (unsigned)microseconds;
}

static bool test_wlan_high(void)
{
    if (test_wlan == 2) {
        return test_clock_us < 10000000u || test_clock_us >= 12000000u;
    }
    return test_wlan == 1;
}
static unsigned test_page_count;

static void test_printf(const char *format, ...)
{
    va_list args;
    int written;
    va_start(args, format);
    written = vsnprintf(test_log + test_log_size,
        sizeof(test_log) - test_log_size, format, args);
    va_end(args);
    assert(written >= 0 && (size_t)written < sizeof(test_log) - test_log_size);
    test_log_size += (size_t)written;
}
#define printf test_printf

static bool PE_parse_boot_argn(const char *name, void *value, int size)
{
    assert(!strcmp(name, "fuxibt") && size == sizeof(int));
    if (test_arg_present) {
        memcpy(value, &test_boot_mode, sizeof(test_boot_mode));
    }
    return test_arg_present;
}

static kern_return_t kmem_alloc(vm_map_t map, vm_offset_t *address,
    vm_size_t size, unsigned flags, unsigned tag)
{
    (void)map;
    assert(flags == 7 && tag == VM_KERN_MEMORY_IOKIT);
    test_allocations++;
    if (test_alloc_failure == test_allocations) {
        return 1;
    }
    *address = (uintptr_t)calloc(1, size);
    assert(*address);
    return KERN_SUCCESS;
}

static kern_return_t pmap_enter_options_addr(pmap_t map,
    vm_map_offset_t address, uint64_t pa, vm_prot_t protection,
    vm_prot_t fault, unsigned cache, boolean_t wired, unsigned options, void *arg)
{
    (void)map;
    assert(protection == 3 && fault == 0 && cache == 7 && wired == TRUE);
    assert(options == PMAP_OPTIONS_NOWAIT && !arg);
    assert(!(pa & PAGE_MASK));
    test_maps++;
    if (test_map_failure == test_maps) {
        return 1;
    }
    assert(test_page_count < 16);
    test_pages[test_page_count++] = (struct test_page){address, pa};
    return KERN_SUCCESS;
}

static void pmap_remove(pmap_t map, vm_map_offset_t start, vm_map_offset_t end)
{
    (void)map;
    assert(end > start);
    for (unsigned index = 0; index < test_page_count; index++) {
        if (test_pages[index].address >= start && test_pages[index].address < end) {
            test_pages[index].address = 0;
        }
    }
}

static void kmem_free(vm_map_t map, vm_offset_t address, vm_size_t size)
{
    (void)map;
    assert(size && address);
    test_frees++;
    free((void *)address);
}

static unsigned fuxi_gpu_access(uintptr_t address, uint64_t *value,
    unsigned write, unsigned reserved)
{
    static const uint32_t branches[] = {0x233d4, 0x233d0, 0x233cc, 0x23004, 0x1e754};
    uint64_t pa = 0;
    assert(write <= 1 && !reserved);
    test_mmio++;
    if (test_read_failure == test_mmio) {
        return 1;
    }
    for (unsigned index = 0; index < test_page_count; index++) {
        const uintptr_t start = test_pages[index].address;
        if (start && address >= start && address - start < PAGE_SIZE) {
            pa = test_pages[index].pa + address - start;
        }
    }
    assert(pa);
    if (write) {
        /* fuxi,bt=3 在 wrapper 前失敗時只會寫 GCC（投票與 SE6 RCG）。 */
        unsigned index = 0;
        assert(pa >= FUXI_BT_GCC_BASE && pa < FUXI_BT_GCC_BASE + 0x60000);
        test_writes++;
        while (index < test_written_count && test_written[index].pa != pa) {
            index++;
        }
        if (index == test_written_count) {
            assert(test_written_count < 32);
            test_written[test_written_count++].pa = pa;
        }
        test_written[index].value = (uint32_t)*value;
        return 0;
    }
    *value = 0;
    if (pa == FUXI_BT_TLMM_BASE + 80u * 0x1000u) {
        *value = test_wlan_high() ? 0x200u : 0;
    } else if (pa == FUXI_BT_TLMM_BASE + 80u * 0x1000u + 4u) {
        *value = test_wlan_high() ? 2u : 0;
    } else if (test_gpll0_ok && pa == FUXI_BT_GCC_BASE + 0x52018) {
        *value = 1;
    } else if (test_gpll0_ok && pa == FUXI_BT_GCC_BASE) {
        *value = 1u << 31;
    } else if (test_gpll0_ok && pa == FUXI_BT_GCC_BASE + 0x18) {
        *value = 0x402;
    }
    for (unsigned index = 0; index < test_written_count; index++) {
        if (test_written[index].pa == pa) {
            *value = test_written[index].value;
            if (pa == FUXI_BT_GCC_BASE + 0x1e760) {
                *value &= ~1u; /* CMD_UPDATE 立即完成 */
            }
            return 0;
        }
    }
    for (unsigned index = 0; index < 5; index++) {
        if (pa == FUXI_BT_GCC_BASE + branches[index] && (test_off_mask & (1u << index))) {
            *value = 1u << 31;
        }
    }
    if (pa >= FUXI_BT_UART_BASE && pa < FUXI_BT_UART_BASE + 0x4000) {
        assert(!test_off_mask);
        test_engine_mmio++;
        if (pa == FUXI_BT_UART_BASE + 0x68) {
            *value = 0x204;
        }
    }
    if (pa >= FUXI_BT_WRAPPER_BASE && pa < FUXI_BT_WRAPPER_BASE + 0x4000) {
        assert(!test_off_mask);
        test_engine_mmio++;
    }
    return 0;
}

static kern_return_t kernel_thread_start(thread_continue_t entry,
    void *context, thread_t *thread)
{
    assert(entry && !context);
    test_threads++;
    if (test_thread_fail) {
        return 1;
    }
    *thread = (thread_t)(uintptr_t)1;
    return KERN_SUCCESS;
}

static void thread_deallocate(thread_t thread)
{
    assert(thread);
    test_thread_refs++;
}

static thread_t current_thread(void)
{
    return (thread_t)(uintptr_t)1;
}

static kern_return_t thread_terminate(thread_t thread)
{
    assert(thread);
    test_terminations++;
    return 0;
}
'''

TESTS = r'''
static void test_entry_reset(int mode)
{
    assert(test_frees + (test_alloc_failure ? 1u : 0u) == test_allocations);
    test_boot_mode = mode;
    test_arg_present = true;
    test_thread_fail = false;
    test_threads = test_thread_refs = test_terminations = 0;
    test_allocations = test_frees = test_maps = test_mmio = test_engine_mmio = 0;
    test_off_mask = test_alloc_failure = test_map_failure = test_read_failure = 0;
    test_log_size = test_page_count = 0;
    test_log[0] = 0;
    fuxi_bt_started = fuxi_bt_mode = fuxi_bt_registration = 0;
    test_written_count = test_writes = test_wlan = test_adt_lookups = 0;
    test_clock_us = 0;
    test_gpll0_ok = test_adt_present = false;
    test_adt_value = test_adt_size = 0;
}

static uint32_t test_written_value(uint64_t pa)
{
    for (unsigned index = 0; index < test_written_count; index++) {
        if (test_written[index].pa == pa) {
            return test_written[index].value;
        }
    }
    assert(false);
    return 0;
}

static void test_board_mode(void)
{
    static const uint32_t restored[] = {0x52010, 0x1e764, 0x1e768, 0x1e76c, 0x1e770};
    /* 命令列已滿：沒有 fuxibt 時讀 ADT /chosen fuxi,bt（u32）。 */
    test_entry_reset(0);
    test_arg_present = false;
    test_adt_present = true;
    test_adt_value = 3;
    test_adt_size = 4;
    fuxi_bt_init();
    assert(test_threads == 1 && fuxi_bt_mode == 3 && test_adt_lookups == 1);
    test_entry_reset(0);
    test_arg_present = false;
    test_adt_present = true;
    test_adt_value = 3;
    test_adt_size = 8;
    fuxi_bt_init();
    assert(!test_threads && test_adt_lookups == 1);
    test_entry_reset(0);
    test_arg_present = false;
    test_adt_present = true;
    test_adt_value = 0x80000000u;
    test_adt_size = 4;
    fuxi_bt_init();
    assert(!test_threads && strstr(test_log, "mode -1 rejected"));
    test_entry_reset(0);
    test_arg_present = false;
    test_adt_present = true;
    test_adt_value = 4;
    test_adt_size = 4;
    fuxi_bt_init();
    assert(!test_threads && strstr(test_log, "mode 4 rejected"));
    test_entry_reset(0);
    test_adt_present = true;
    test_adt_value = 3;
    test_adt_size = 4;
    fuxi_bt_init();
    assert(!test_threads && !test_adt_lookups);
    test_entry_reset(0);
    test_arg_present = false;
    fuxi_bt_init();
    assert(!test_threads && test_adt_lookups == 1);

    /* WLAN_EN 一直沒拉高：300 秒後放棄，不寫任何暫存器。 */
    test_entry_reset(3);
    fuxi_bt_init();
    fuxi_bt_worker(NULL, 0);
    assert(strstr(test_log, "not steady high for 15 s within 300 s; BT_EN untouched"));
    assert(!test_writes && test_allocations == test_frees && test_terminations == 1);
    assert(test_clock_us >= 300000000u && test_clock_us < 300500000u);
    assert(!strstr(test_log, "board power"));

    /* WLAN_EN 穩定、GPLL0 沒鎖：在 gpll0 階段停下，不寫。 */
    test_entry_reset(3);
    test_wlan = 1;
    fuxi_bt_init();
    fuxi_bt_worker(NULL, 0);
    assert(strstr(test_log, "board WLAN_EN steady after 15000 ms"));
    assert(strstr(test_log, "board power status=no-uart stage=gpll0"));
    assert(strstr(test_log, "board restore status=ok"));
    assert(!test_writes && test_allocations == test_frees && !strstr(test_log, "probe status="));

    /* WLAN_EN 中途掉 2 秒：從再次拉高起重新算 15 秒。 */
    test_entry_reset(3);
    test_wlan = 2;
    fuxi_bt_init();
    fuxi_bt_worker(NULL, 0);
    assert(strstr(test_log, "board WLAN_EN steady after 27000 ms"));

    /* GPLL0 正常但 QUP wrapper 讀不到：投票與 RCG 都寫過，之後全部還原。 */
    test_entry_reset(3);
    test_wlan = 1;
    test_gpll0_ok = true;
    fuxi_bt_init();
    fuxi_bt_worker(NULL, 0);
    assert(strstr(test_log, "board power status=no-uart stage=wrapper value=0 "));
    assert(strstr(test_log, "added=0x40f rcg_cfg=0->0x2601"));
    assert(strstr(test_log, "board restore status=ok"));
    assert(test_writes == 12 && test_allocations == test_frees);
    for (unsigned index = 0; index < sizeof(restored) / sizeof(restored[0]); index++) {
        assert(test_written_value(FUXI_BT_GCC_BASE + restored[index]) == 0);
    }
    assert(!strstr(test_log, "probe status="));
}

static void test_entry(void)
{
    struct fake_uart uart;
    for (int mode = -1; mode <= 3; mode++) {
        test_entry_reset(mode);
        fuxi_bt_init();
        if (mode < 1 || mode > 3) {
            assert(!test_threads && !test_allocations && !test_mmio);
        } else {
            assert(test_threads == 1 && test_thread_refs == 1);
            fuxi_bt_init();
            assert(test_threads == 1);
        }
    }
    test_entry_reset(2);
    test_arg_present = false;
    fuxi_bt_init();
    assert(!test_threads && !test_mmio);
    test_entry_reset(1);
    test_thread_fail = true;
    fuxi_bt_init();
    assert(test_threads == 1 && !test_thread_refs);
    assert(strstr(test_log, "worker start failed"));
    test_entry_reset(1);
    test_off_mask = 0x10;
    fuxi_bt_init();
    fuxi_bt_worker(NULL, 0);
    assert(test_terminations == 1 && test_allocations == test_frees);
    assert(!test_engine_mmio && !strstr(test_log, "probe status="));
    test_entry_reset(1);
    fuxi_bt_init();
    fuxi_bt_worker(NULL, 0);
    assert(test_allocations == test_frees && test_engine_mmio == 6);
    assert(strstr(test_log, "protocol=2"));
    test_entry_reset(2);
    fuxi_bt_init();
    fuxi_bt_worker(NULL, 0);
    assert(strstr(test_log, "probe status=no-uart"));
    assert(test_allocations == test_frees);
    test_entry_reset(2);
    fake_init(&uart);
    assert(fuxi_bt_register_uart(NULL) == FUXI_BT_ARGUMENT);
    assert(fuxi_bt_register_uart(&uart.ops) == FUXI_BT_OK);
    assert(fuxi_bt_register_uart(&uart.ops) == FUXI_BT_BUSY);
    fuxi_bt_init();
    fuxi_bt_worker(NULL, 0);
    assert(uart.acquisitions == 1 && uart.releases == 1);
    assert(strstr(test_log, "probe status=ok cleanup=ok tx=5 rx=21"));
    assert(strstr(test_log, "QCA version product=0x12345678"));
    assert(test_allocations == test_frees);
    for (unsigned failure = 1; failure <= 6; failure++) {
        test_entry_reset(1);
        test_alloc_failure = failure;
        fuxi_bt_init();
        fuxi_bt_worker(NULL, 0);
        assert(test_allocations == failure && test_frees == failure - 1);
        assert(strstr(test_log, "survey status=io"));
    }
    for (unsigned failure = 1; failure <= 7; failure++) {
        test_entry_reset(1);
        test_map_failure = failure;
        fuxi_bt_init();
        fuxi_bt_worker(NULL, 0);
        assert(test_allocations == test_frees);
        assert(strstr(test_log, "survey status=io"));
    }
    for (unsigned failure = 1; failure <= 35; failure++) {
        test_entry_reset(2);
        fake_init(&uart);
        assert(fuxi_bt_register_uart(&uart.ops) == FUXI_BT_OK);
        test_read_failure = failure;
        fuxi_bt_init();
        fuxi_bt_worker(NULL, 0);
        assert(test_mmio == failure && test_allocations == test_frees);
        assert(!uart.acquisitions && !uart.releases);
        assert(strstr(test_log, "read fault pa="));
    }
    test_board_mode();
    test_entry_reset(0);
    puts("PASS XNU host model: default-off/invalid args, ADT fuxi,bt fallback, one-shot startup, registration, survey gates, QCA worker, board mode WLAN_EN gate/GPLL0 refusal/write+restore, 6 allocation/7 pmap/35 MMIO failure cleanup paths");
}

int main(void)
{
    test_protocol();
    test_transport();
    test_snapshot();
    test_fuzz();
    test_entry();
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--cc", nargs="+")
    args = parser.parse_args()
    specification = importlib.util.spec_from_file_location(
        "fuxi_bluetooth_test", ROOT / "tools" / "test-fuxi-bluetooth.py")
    module = importlib.util.module_from_spec(specification)
    sys.dont_write_bytecode = True
    specification.loader.exec_module(module)
    compiler, environment = module.compiler_configuration(args.cc)
    msvc = Path(compiler[0]).name.lower() in ("cl", "cl.exe")
    if msvc and args.sanitize:
        raise SystemExit("--sanitize requires Clang or GCC with ASan and UBSan.")
    production = (SOURCE / "fuxi_bt_xnu.c").read_text(encoding="utf-8")
    production = "\n".join(line for line in production.splitlines()
                           if not line.startswith("#include "))
    harness = module.HARNESS[:module.HARNESS.index("int main(void)")]
    with tempfile.TemporaryDirectory(prefix="fuxi-bluetooth-xnu-") as temporary:
        directory = Path(temporary)
        generated = directory / "entry.c"
        generated.write_text(harness + STUBS + production + TESTS, encoding="utf-8")
        executable = directory / ("entry.exe" if os.name == "nt" else "entry")
        if msvc:
            command = compiler + [
                "/nologo", "/std:c11", "/W4", "/WX", "/Od", "/D_CRT_SECURE_NO_WARNINGS",
                f"/I{SOURCE}", str(SOURCE / "fuxi_bt.c"), str(SOURCE / "fuxi_bt_geni_fifo.c"),
                str(SOURCE / "fuxi_bt_board.c"), str(generated),
                f"/Fe{executable}"
            ]
        else:
            command = compiler + [
                "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-I", str(SOURCE), str(SOURCE / "fuxi_bt.c"), str(SOURCE / "fuxi_bt_geni_fifo.c"),
                str(SOURCE / "fuxi_bt_board.c"), str(generated),
                "-o", str(executable)
            ]
            if args.sanitize:
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        subprocess.run(command, cwd=directory, env=environment, check=True)
        subprocess.run([str(executable)], cwd=directory, env=environment, check=True, timeout=60)
        print("XNU declarations and MMIO are simulated in this host check.")
        print(f"Sanitizers {'ASan/UBSan' if args.sanitize else 'disabled'}")


if __name__ == "__main__":
    main()
