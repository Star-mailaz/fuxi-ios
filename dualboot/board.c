/* SPDX-License-Identifier: MIT
 * Bare-metal Fuxi adapter: the entry ABI/linker layout and Linux handoff are
 * reused from the existing slot-b chain. Recovery bypasses all menu hardware.
 * Display guard/autorefresh handling: ios-fuxi/shim/{console.c,fuxi-probe/probe.c}.
 */
#include "menu.h"
#include "bootinfo.h"
#include "spmi.h"
#include "fuxi-ram-profile.h"
#ifndef MENU_DEFAULT_IOS
#define MENU_DEFAULT_IOS 0
#endif
#ifndef MENU_TIMEOUT_MS
#define MENU_TIMEOUT_MS 0
#endif
extern unsigned char _head[], _end[], _linux_start[], _linux_end[];
extern uint32_t probe_safe_rd32(uint64_t, uint32_t *);
extern unsigned probe_safe_wr32(uint64_t, uint32_t);

/* Kept in the ELF for offline and future RAM diagnostics, no storage writes. */
volatile uint32_t dualboot_report[8];
static uint64_t counter(void)
{ uint64_t v; __asm__ volatile("mrs %0, cntpct_el0" : "=r"(v)); return v; }
static uint64_t frequency(void)
{ uint64_t v; __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(v)); return v; }
static void delay_us(void *ctx, unsigned us)
{
    (void)ctx;
    uint64_t ticks = frequency() * us / 1000000u, start = counter();
    while (counter() - start < ticks) __asm__ volatile("yield");
}
static int read_reg(void *ctx, uintptr_t a, uint32_t *value)
{
    (void)ctx;
    uint32_t faulted = 0;
    *value = probe_safe_rd32(a, &faulted);
    __asm__ volatile("dmb oshld" ::: "memory");
    return !faulted;
}
static int write_reg(void *ctx, uintptr_t a, uint32_t value)
{
    (void)ctx;
    unsigned faulted = probe_safe_wr32(a, value);
    __asm__ volatile("dsb sy" ::: "memory");
    return !faulted;
}
static int reg_is(uintptr_t a, uint32_t expected)
{ uint32_t value; return read_reg(0, a, &value) && value == expected; }
static int screen_ready(void)
{
    return reg_is(0xae05014, 0xb8000000) && reg_is(0xae05024, 4320) &&
           reg_is(0xae05000, (2400u << 16) | 1080u) && reg_is(0xae05030, 0x237ff);
}
static void present(void)
{
    uint32_t refresh, start;
    __asm__ volatile("dsb sy" ::: "memory");
    if (!read_reg(0, 0xae362b4, &refresh) || (refresh & 0x80000000u)) return;
    if (read_reg(0, 0xae1601c, &start) && !(start & 1u)) (void)write_reg(0, 0xae1601c, 1);
}
static void draw(struct menu_paint_state *screen, const struct menu *m, const char *notice)
{
    if (menu_paint(screen, m, (volatile uint32_t *)0xb8000000UL, 1080, 2400, 1080,
                   1080u * 2400u, notice)) present();
}
static void announce_launch(struct menu_paint_state *screen)
{
    if (menu_paint_status(screen, (volatile uint32_t *)0xb8000000UL, 1080, 2400, 1080,
                          1080u * 2400u, "進入系統中")) {
        present();
        delay_us(0, 20000); /* 讓 command-mode 這一幀送到面板後再交接 */
    }
}
static int overlap(uintptr_t a, uintptr_t e, uintptr_t b, uintptr_t f)
{ return a < f && b < e; }
static uint64_t psci(uint64_t function)
{
    register uint64_t x0 __asm__("x0") = function;
    register uint64_t x1 __asm__("x1") = 0, x2 __asm__("x2") = 0, x3 __asm__("x3") = 0;
    __asm__ volatile("dsb sy\nsmc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) ::
                     "memory", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17");
    return x0;
}

/* Called by the existing start.o. Return Linux entry, or zero for loader_main.
 * No UFS, block device, slot metadata, USB or filesystem access in this module. */
uintptr_t chain_select(uintptr_t fdt)
{
    dualboot_report[0] = 0x44424d31; /* DBM1 */
    dualboot_report[1] = 1;
    uintptr_t linux_entry = (uintptr_t)_linux_start;
    if ((linux_entry & 0x1fffffu) || (uintptr_t)_linux_end - linux_entry < 64 ||
        !reg_is(linux_entry + 56, 0x644d5241)) return 0;
    uint32_t total;
    if (!fdt || (fdt & 7u) || fdt < 0x80000000u || fdt > 0xb8000000u - 40 ||
        !reg_is(fdt, 0xedfe0dd0) || !read_reg(0, fdt + 4, &total)) return 0;
    total = __builtin_bswap32(total);
    if (total < 40 || total > (2u << 20) || total > 0xb8000000u - fdt ||
        overlap(fdt, fdt + total, (uintptr_t)_head, (uintptr_t)_end)) return 0;
    /* Validate every containing word before the bounded byte parser reads it. */
    for (unsigned i = 0; i < total; i += 4) {
        uint32_t ignored;
        if (!read_reg(0, fdt + i, &ignored)) return 0;
    }
    struct menu_bootinfo info;
    if (!menu_fdt_initrd((const void *)fdt, total, &info) ||
        info.initrd_start < 0x80000000u || info.initrd_end > 0xb8000000u ||
        info.initrd_end - info.initrd_start > (256u << 20) ||
        overlap(info.initrd_start, info.initrd_end, (uintptr_t)_head, (uintptr_t)_end) ||
        overlap(info.initrd_start, info.initrd_end, fdt, fdt + total)) return 0;
    size_t initrd_bytes = (size_t)(info.initrd_end - info.initrd_start);
    int normal = menu_bootconfig_normal((const void *)(uintptr_t)info.initrd_start, initrd_bytes);
    if (normal < 0) normal = initrd_bytes < (64u << 20); /* existing chain fallback */
    if (!normal) { dualboot_report[1] = 2; return linux_entry; }
    /* Same 12GB SKU/usable-bank check as loader_main, before drawing or keys. */
    if (fuxi_ram_profile_check((const void *)fdt, total, FUXI_RAM_PROFILE_BASE,
#if defined(FUXI_RAM_9G)
                             FUXI_RAM_PROFILE_9G
#else
                             FUXI_RAM_PROFILE_5G
#endif
                             ) !=
        FuxiRamProfileStaticOk12G) return 0;
    if (!frequency() || !screen_ready()) { dualboot_report[1] = 90; return linux_entry; }
    struct menu_spmi spmi;
    struct menu_bus bus;
    /* Volatile stores force runtime ADRP address materialization. A constant
     * aggregate would embed ABS64 function pointers, invalid after ABL loads us. */
    volatile struct menu_bus *runtime_bus = &bus;
    runtime_bus->context = 0;
    runtime_bus->read = read_reg;
    runtime_bus->write = write_reg;
    runtime_bus->delay = delay_us;
    if (!menu_spmi_open(&spmi, &bus)) { dualboot_report[1] = 91; return linux_entry; }
    struct menu m;
    struct menu_keys keys;
    struct menu_paint_state screen = {0};
    menu_init(&m, MENU_DEFAULT_IOS ? MENU_IOS : MENU_ANDROID, MENU_TIMEOUT_MS);
    menu_keys_init(&keys);
    dualboot_report[1] = 3;
    draw(&screen, &m, 0);
    uint64_t previous = counter(), hz = frequency();
    int input_error = 0;
    for (;;) {
        delay_us(0, 10000);
        uint64_t now = counter(), ms64 = (now - previous) / (hz / 1000u ? hz / 1000u : 1u);
        unsigned ms = ms64 > 1000u ? 1000u : (unsigned)ms64;
        previous = now;
        unsigned mask;
        if (!menu_spmi_keys(&spmi, &mask)) {
            menu_keys_init(&keys);
            m.interacted = 1; m.remaining_ms = 0;
            if (!input_error) draw(&screen, &m, "按鍵讀取失敗");
            input_error = 1;
            delay_us(0, 100000);
            continue;
        }
        if (input_error) { draw(&screen, &m, 0); input_error = 0; }
        /* Any physical input, including its debounce interval, cancels timeout. */
        if (mask) { m.interacted = 1; m.remaining_ms = 0; }
        enum menu_event event = menu_keys_sample(&keys, mask, ms);
        enum menu_action action = menu_update(&m, event, ms);
        dualboot_report[2] = mask;
        dualboot_report[3] = m.page;
        dualboot_report[4] = m.focus;
        dualboot_report[5] = m.os;
        dualboot_report[6] = action;
        if (action == MENU_BOOT_ANDROID) {
            announce_launch(&screen);
            dualboot_report[1] = 4;
            return linux_entry;
        }
        if (action == MENU_BOOT_IOS) {
            announce_launch(&screen);
            dualboot_report[1] = 5;
            return 0;
        }
        if (action == MENU_FASTBOOT || action == MENU_RECOVERY) {
            if (menu_spmi_set_reboot_mode(&spmi, action)) (void)psci(0x84000009u);
        } else if (action == MENU_REBOOT) (void)psci(0x84000009u);
        else if (action == MENU_POWEROFF) (void)psci(0x84000008u);
        if (action != MENU_WAIT) {
            m.action = MENU_WAIT;
            m.interacted = 1; m.remaining_ms = 0;
            draw(&screen, &m, "無法執行，請重試");
        } else if (event != MENU_NONE) draw(&screen, &m, 0);
    }
}
