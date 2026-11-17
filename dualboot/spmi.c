/* SPDX-License-Identifier: MIT
 * Register contract reused from unixnu-fuxi/package/BootResetCore.h (MIT),
 * FuxiButtons.cpp and ksrc/docs-lanes/buttons.md; checked against the local
 * Linux v6.12 spmi-pmic-arb reference. No IRQ or GPIO configuration writes.
 */
#include "spmi.h"
#define CORE UINT32_C(0x0c400000)
#define CONFIG UINT32_C(0x0c42d000)
#define OBSERVER UINT32_C(0x0c440000)
#define CHANNEL UINT32_C(0x0c500000)

static int rd(struct menu_spmi *s, uintptr_t a, uint32_t *v)
{ return s->bus.read(s->bus.context, a, v); }
static int wr(struct menu_spmi *s, uintptr_t a, uint32_t v)
{ return s->bus.write(s->bus.context, a, v); }
static int wait_done(struct menu_spmi *s, uintptr_t ch)
{
    for (unsigned i = 0; i < 100; ++i) {
        uint32_t status;
        if (!rd(s, ch + 8, &status)) return 0;
        if (status & 1u) return !(status & 14u);
        s->bus.delay(s->bus.context, 1);
    }
    return 0;
}
static int read8(struct menu_spmi *s, int apid, unsigned reg, uint8_t *v)
{
    if (apid < 0 || (unsigned)apid >= s->count) return 0;
    uintptr_t ch = OBSERVER + (unsigned)apid * 0x20u;
    uint32_t value;
    if (!wr(s, ch, (1u << 27) | (reg << 4)) || !wait_done(s, ch) || !rd(s, ch + 0x18, &value)) return 0;
    *v = (uint8_t)value;
    return 1;
}

int menu_spmi_open(struct menu_spmi *s, const struct menu_bus *bus)
{
    *s = (struct menu_spmi){0};
    if (!bus || !bus->read || !bus->write || !bus->delay) return 0;
    s->bus = *bus;
    s->pon = s->gpio = s->sdam = s->sdam_owner = -1;
    uint32_t version, features;
    if (!rd(s, CORE, &version) || version < 0x70000000u || version >= 0x80000000u ||
        !rd(s, CORE + 4, &features)) return 0;
    s->count = features & 0x7ffu;
    if (!s->count || s->count > 1024) return 0;
    for (unsigned i = 0; i < s->count; ++i) {
        uint32_t map, owner;
        if (!rd(s, CORE + 0x2000 + 4 * i, &map)) return 0;
        if (!map) continue;
        unsigned ppid = (map >> 8) & 0xfffu;
        if (ppid != 0x013 && ppid != 0x18d && ppid != 0x071) continue;
        if (!rd(s, CONFIG + 4 * i, &owner)) return 0;
        owner &= 7u;
        if (ppid == 0x013 && (s->pon < 0 || owner == 0)) s->pon = (int)i;
        if (ppid == 0x18d && (s->gpio < 0 || owner == 0)) s->gpio = (int)i;
        if (ppid == 0x071 && (s->sdam < 0 || owner == 0)) {
            s->sdam = (int)i; s->sdam_owner = (int)owner;
        }
    }
    /* Withhold an unconfigured GPIO instead of treating its floating level as
     * a held Vol-up. All checks below are observer reads. */
    uint8_t type, mode, enable;
    if (s->pon < 0 || s->gpio < 0 || !read8(s, s->gpio, 4, &type) || type != 0x10 ||
        !read8(s, s->gpio, 0x40, &mode) || (mode & 3u) ||
        !read8(s, s->gpio, 0x46, &enable) || !(enable & 0x80u)) return 0;
    unsigned keys;
    return menu_spmi_keys(s, &keys);
}

int menu_spmi_keys(struct menu_spmi *s, unsigned *mask)
{
    uint8_t pon, gpio;
    if (!read8(s, s->pon, 0x10, &pon) || !read8(s, s->gpio, 0x10, &gpio)) return 0;
    *mask = (pon & 0x80u ? MENU_KEY_POWER : 0u) | (pon & 0x40u ? MENU_KEY_DOWN : 0u) |
            (!(gpio & 1u) ? MENU_KEY_UP : 0u);
    return 1;
}

int menu_spmi_set_reboot_mode(struct menu_spmi *s, enum menu_action action)
{
    /* FuxiResetSystemLib.c and the Qualcomm restart_reason driver agree:
     * Recovery = 1, bootloader = 2 in SDAM 0x48 bits [7:1]. */
    unsigned mode;
    switch (action) {
    case MENU_RECOVERY: mode = 1; break;
    case MENU_FASTBOOT: mode = 2; break;
    default: return 0;
    }
    if (s->sdam < 0 || s->sdam_owner != 0) return 0;
    uint8_t before, after;
    if (!read8(s, s->sdam, 0x48, &before)) return 0;
    uint8_t next = (uint8_t)((before & 1u) | (mode << 1));
    uintptr_t ch = CHANNEL + (unsigned)s->sdam * 0x1000u;
    if (!wr(s, ch + 0x10, next) || !wr(s, ch, 0x48u << 4) || !wait_done(s, ch) ||
        !read8(s, s->sdam, 0x48, &after)) return 0;
    return after == next;
}
