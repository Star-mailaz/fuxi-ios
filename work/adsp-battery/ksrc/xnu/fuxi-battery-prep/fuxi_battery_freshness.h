#ifndef FUXI_BATTERY_FRESHNESS_H
#define FUXI_BATTERY_FRESHNESS_H

#include <stdint.h>
#include "ShengBattmgr.h"
#include "fuxi_adsp_battery.h"

#ifdef __cplusplus
extern "C" {
#endif

enum FuxiBatteryPrepResult {
    FuxiBatteryPrepOk = 0,
    FuxiBatteryPrepArgument = -1,
    FuxiBatteryPrepGeneration = -2,
    FuxiBatteryPrepDisconnected = -3,
    FuxiBatteryPrepTime = -4
};

typedef struct {
    uint64_t generation;
    uint64_t successful_at_ms[BmFields];
    uint32_t observed_fields;
    int channel_up;
} FuxiBatteryFreshness;

typedef struct {
    uint32_t fresh_fields;
    int update_capacity;
    int update_external;
    int update_charging;
} FuxiBatteryPublishDecision;

int fuxi_battery_prep_init(FuxiBatteryFreshness *state);
int fuxi_battery_prep_channel(FuxiBatteryFreshness *state, int up);
int fuxi_battery_prep_observe(FuxiBatteryFreshness *state,
    uint64_t generation, unsigned field, uint64_t now_ms, int success);
int fuxi_battery_prep_decide(const FuxiBatteryFreshness *state,
    uint64_t now_ms, uint64_t max_age_ms, FuxiBatteryPublishDecision *decision);
void fuxi_battery_prep_merge(FuxiAdspBattery *shown, const FuxiAdspBattery *incoming);

#ifdef __cplusplus
}
#endif

#endif
