/* SPDX-License-Identifier: MIT */
#ifndef FUXI_DUALBOOT_MENU_H
#define FUXI_DUALBOOT_MENU_H
#include <stddef.h>
#include <stdint.h>

enum menu_os { MENU_ANDROID, MENU_IOS };
enum menu_home_control { MENU_ANDROID_BUTTON, MENU_IOS_BUTTON, MENU_OPTIONS,
                         MENU_HOME_COUNT };
enum menu_advanced_control { MENU_RETURN_BUTTON, MENU_FASTBOOT_BUTTON, MENU_RECOVERY_BUTTON,
                             MENU_REBOOT_BUTTON, MENU_POWEROFF_BUTTON, MENU_ADVANCED_COUNT };
enum menu_page { MENU_HOME, MENU_ADVANCED };
enum menu_event { MENU_NONE, MENU_UP, MENU_DOWN, MENU_CONFIRM, MENU_BACK };
enum menu_action { MENU_WAIT, MENU_BOOT_ANDROID, MENU_BOOT_IOS,
                   MENU_REBOOT, MENU_FASTBOOT, MENU_POWEROFF, MENU_RECOVERY };
enum menu_key { MENU_KEY_UP = 1, MENU_KEY_DOWN = 2, MENU_KEY_POWER = 4 };
struct menu {
    enum menu_os os;
    enum menu_page page;
    unsigned focus, timeout_ms, remaining_ms;
    int interacted;
    enum menu_action action;
};
struct menu_keys {
    unsigned candidate, stable, elapsed_ms;
    int armed, power_pending;
};
struct menu_paint_state {
    int drawn;
    enum menu_page page;
    unsigned focus;
    const char *notice;
};
void menu_init(struct menu *m, enum menu_os os, unsigned timeout_ms);
enum menu_action menu_update(struct menu *m, enum menu_event event, unsigned elapsed_ms);
void menu_keys_init(struct menu_keys *keys);
enum menu_event menu_keys_sample(struct menu_keys *keys, unsigned mask, unsigned elapsed_ms);
/* Same renderer runs in firmware and in the host preview. stride is in pixels. */
int menu_draw(const struct menu *m, volatile uint32_t *pixels, unsigned width,
              unsigned height, unsigned stride, size_t capacity_pixels, const char *notice);
/* Keep one zero-initialized state per framebuffer. Notices have static lifetime.
 * Returns 1 when pixels changed, 0 when there was nothing to draw or bounds failed. */
int menu_paint(struct menu_paint_state *state, const struct menu *m,
               volatile uint32_t *pixels, unsigned width, unsigned height,
               unsigned stride, size_t capacity_pixels, const char *notice);
/* Replace the key hints after a boot choice. Needs a menu painted through state;
 * returns 1 when pixels changed. The next menu_paint redraws the whole page. */
int menu_paint_status(struct menu_paint_state *state, volatile uint32_t *pixels, unsigned width,
                      unsigned height, unsigned stride, size_t capacity_pixels, const char *status);
const char *menu_action_name(enum menu_action action);
#endif
