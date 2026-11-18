/* SPDX-License-Identifier: MIT
 * Interaction reference: Mi8 Dual-Boot Lab bootmenu_hercules.inc (9dfb6f9),
 * UniXNU Menu.c. Independent implementation; no LVGL or UEFI dependency.
 */
#include "menu.h"

void menu_init(struct menu *m, enum menu_os os, unsigned timeout_ms)
{
    *m = (struct menu){0};
    m->os = os == MENU_IOS ? MENU_IOS : MENU_ANDROID;
    m->focus = m->os == MENU_IOS ? MENU_IOS_BUTTON : MENU_ANDROID_BUTTON;
    m->timeout_ms = timeout_ms;
    m->remaining_ms = timeout_ms;
}

enum menu_action menu_update(struct menu *m, enum menu_event event, unsigned elapsed_ms)
{
    if (m->action != MENU_WAIT) return m->action;
    /* An input arriving on the deadline wins over the timer. No timer resumes
     * when returning from Other Options. Confirm boots the focused OS. */
    if (event != MENU_NONE) {
        m->interacted = 1;
        m->remaining_ms = 0;
    } else if (!m->interacted && m->remaining_ms) {
        if (elapsed_ms >= m->remaining_ms) {
            m->remaining_ms = 0;
            m->os = MENU_ANDROID;
            m->action = MENU_BOOT_ANDROID;
            return m->action;
        }
        m->remaining_ms -= elapsed_ms;
    }
    unsigned count = m->page == MENU_HOME ? MENU_HOME_COUNT : MENU_ADVANCED_COUNT;
    if (event == MENU_UP) m->focus = (m->focus + count - 1) % count;
    if (event == MENU_DOWN) m->focus = (m->focus + 1) % count;
    if (event == MENU_BACK && m->page == MENU_ADVANCED) {
        m->page = MENU_HOME;
        m->focus = MENU_OPTIONS;
    }
    if (event != MENU_CONFIRM) return m->action;
    if (m->page == MENU_HOME) {
        if (m->focus == MENU_ANDROID_BUTTON) { m->os = MENU_ANDROID; m->action = MENU_BOOT_ANDROID; }
        else if (m->focus == MENU_IOS_BUTTON) { m->os = MENU_IOS; m->action = MENU_BOOT_IOS; }
        else if (m->focus == MENU_OPTIONS) { m->page = MENU_ADVANCED; m->focus = MENU_RETURN_BUTTON; }
    } else {
        switch (m->focus) {
        case MENU_RETURN_BUTTON: m->page = MENU_HOME; m->focus = MENU_OPTIONS; break;
        case MENU_REBOOT_BUTTON: m->action = MENU_REBOOT; break;
        case MENU_FASTBOOT_BUTTON: m->action = MENU_FASTBOOT; break;
        case MENU_RECOVERY_BUTTON: m->action = MENU_RECOVERY; break;
        case MENU_POWEROFF_BUTTON: m->action = MENU_POWEROFF; break;
        }
    }
    return m->action;
}

void menu_keys_init(struct menu_keys *k) { *k = (struct menu_keys){0}; }

enum menu_event menu_keys_sample(struct menu_keys *k, unsigned mask, unsigned elapsed_ms)
{
    mask &= 7u;
    if (mask && (mask & (mask - 1))) {
        k->armed = 0;
        k->power_pending = 0;
    }
    if (mask != k->candidate) { k->candidate = mask; k->elapsed_ms = 0; }
    else if (k->elapsed_ms < 40u) {
        unsigned left = 40u - k->elapsed_ms;
        k->elapsed_ms += elapsed_ms < left ? elapsed_ms : left;
    }
    if (k->elapsed_ms < 40u) return MENU_NONE;
    if (!k->armed) {
        if (!mask) { k->armed = 1; k->stable = 0; k->power_pending = 0; }
        return MENU_NONE;
    }
    unsigned previous = k->stable;
    if (previous == mask) return MENU_NONE;
    k->stable = mask;
    /* Ignore chords until every key is released. In particular never consume
     * Power+Vol-down (the PMIC warm-reset gesture) as a boot confirmation. */
    if (mask && (mask & (mask - 1))) {
        k->armed = 0;
        k->power_pending = 0;
        return MENU_NONE;
    }
    if (mask == MENU_KEY_POWER) { k->power_pending = 1; return MENU_NONE; }
    if (!mask && previous == MENU_KEY_POWER && k->power_pending) {
        k->power_pending = 0;
        return MENU_CONFIRM;
    }
    k->power_pending = 0;
    if (mask == MENU_KEY_UP) return MENU_UP;
    if (mask == MENU_KEY_DOWN) return MENU_DOWN;
    return MENU_NONE;
}

const char *menu_action_name(enum menu_action a)
{
    switch (a) {
    case MENU_BOOT_ANDROID: return "android";
    case MENU_BOOT_IOS: return "ios";
    case MENU_REBOOT: return "reboot";
    case MENU_FASTBOOT: return "fastboot";
    case MENU_RECOVERY: return "recovery";
    case MENU_POWEROFF: return "poweroff";
    default: return "wait";
    }
}
