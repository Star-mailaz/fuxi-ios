/* SPDX-License-Identifier: MIT */
#ifndef FUXI_DUALBOOT_BOOTINFO_H
#define FUXI_DUALBOOT_BOOTINFO_H
#include <stddef.h>
#include <stdint.h>
struct menu_bootinfo { uint64_t initrd_start, initrd_end; };
int menu_fdt_initrd(const void *data, size_t bytes, struct menu_bootinfo *out);
/* 1: normal Android initrd; 0: Recovery; -1: invalid trailer. */
int menu_bootconfig_normal(const void *initrd, size_t bytes);
#endif
