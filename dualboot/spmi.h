/* SPDX-License-Identifier: MIT */
#ifndef FUXI_DUALBOOT_SPMI_H
#define FUXI_DUALBOOT_SPMI_H
#include <stdint.h>
#include "menu.h"
struct menu_bus {
    void *context;
    int (*read)(void *, uintptr_t, uint32_t *);
    int (*write)(void *, uintptr_t, uint32_t);
    void (*delay)(void *, unsigned);
};
struct menu_spmi { struct menu_bus bus; unsigned count; int pon, gpio, sdam, sdam_owner; };
int menu_spmi_open(struct menu_spmi *s, const struct menu_bus *bus);
int menu_spmi_keys(struct menu_spmi *s, unsigned *mask);
int menu_spmi_set_reboot_mode(struct menu_spmi *s, enum menu_action action);
#endif
