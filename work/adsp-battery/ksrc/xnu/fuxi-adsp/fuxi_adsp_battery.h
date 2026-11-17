/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* fuxiadsp=3: the battery manager's readings as SweetBattery (iokit/Kernel/arm/SweetBattery.cpp) publishes them to powerd.
 * Shared by bsd/dev/fuxi_adsp_battery.c (C) and SweetBattery.cpp (C++); plain data only. */
#ifndef FUXI_ADSP_BATTERY_H
#define FUXI_ADSP_BATTERY_H
#include <stdint.h>
#define FUXI_BATTERY_DEFAULT_MAX_AGE_MS 90000u
#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint32_t sequence;                /* plausible readings taken so far (1 = the first) */
    int32_t percent;                  /* 1..100: a reading never publishes 0 (iOS would shut down on a bad parse) */
    int32_t voltage_mv, current_ma;   /* current positive while the battery takes charge */
    int32_t temperature;              /* centidegrees C, valid only with temperature_valid */
    int32_t raw_mah, full_mah, design_mah, cycles;  /* 0: not reported */
    int32_t minutes_to_empty, minutes_to_full;      /* -1: unknown */
    uint32_t adapter_family;
    int32_t adapter_mv, adapter_ma, adapter_watts;
    uint8_t present, external, external_known, charging, status_known, fully_charged, temperature_valid, pad;
    uint64_t generation;
    uint32_t fresh_fields, max_age_ms, soc_age_ms, external_age_ms, status_age_ms;
    uint8_t soc_known, voltage_valid, current_valid, channel_up, stale;
} FuxiAdspBattery;

/* 1 when the DSP's battery manager is meant to feed the power source (fuxiadsp=3); SweetBattery then polls. */
int fuxi_adsp_battery_wanted(void);
int fuxi_adsp_battery_reading(FuxiAdspBattery *out);
/* SweetBattery samples the reading on a 30 s timer. fn(arg) is called, with the reading's lock held, each time something iOS
 * shows changes (charger, charging, full, percent, presence, or their validity), so the sample can be taken at once.
 * fn must only schedule work: it must not call back into this file. NULL unregisters; no call is in flight on return. */
void fuxi_adsp_battery_on_change(void (*fn)(void *), void *arg);

#ifdef __cplusplus
}
#endif
#endif
