#include "fuxi_battery_freshness.h"

_Static_assert(BmFields <= 32, "Battery freshness mask supports at most 32 fields");

int fuxi_battery_prep_init(FuxiBatteryFreshness *state)
{
    if (!state) {
        return FuxiBatteryPrepArgument;
    }
    const FuxiBatteryFreshness initial = {0};
    *state = initial;
    return FuxiBatteryPrepOk;
}

int fuxi_battery_prep_channel(FuxiBatteryFreshness *state, int up)
{
    if (!state) {
        return FuxiBatteryPrepArgument;
    }
    up = up != 0;
    if (state->channel_up == up) {
        return FuxiBatteryPrepOk;
    }
    state->channel_up = 0;
    state->observed_fields = 0;
    if (state->generation == UINT64_MAX) {
        return FuxiBatteryPrepGeneration;
    }
    state->generation++;
    state->channel_up = up;
    return FuxiBatteryPrepOk;
}

int fuxi_battery_prep_observe(FuxiBatteryFreshness *state,
    uint64_t generation, unsigned field, uint64_t now_ms, int success)
{
    uint32_t bit;

    if (!state || field >= BmFields) {
        return FuxiBatteryPrepArgument;
    }
    if (!state->channel_up) {
        return FuxiBatteryPrepDisconnected;
    }
    if (generation != state->generation) {
        return FuxiBatteryPrepGeneration;
    }
    if (!success) {
        return FuxiBatteryPrepOk;
    }
    bit = UINT32_C(1) << field;
    if ((state->observed_fields & bit) && now_ms < state->successful_at_ms[field]) {
        return FuxiBatteryPrepTime;
    }
    state->successful_at_ms[field] = now_ms;
    state->observed_fields |= bit;
    return FuxiBatteryPrepOk;
}

int fuxi_battery_prep_decide(const FuxiBatteryFreshness *state,
    uint64_t now_ms, uint64_t max_age_ms, FuxiBatteryPublishDecision *decision)
{
    FuxiBatteryPublishDecision result = {0, 0, 0, 0};

    if (!state || !decision || !max_age_ms) {
        return FuxiBatteryPrepArgument;
    }
    if (state->channel_up) {
        for (unsigned field = 0; field < BmFields; field++) {
            const uint32_t bit = UINT32_C(1) << field;
            const uint64_t sampled_at = state->successful_at_ms[field];
            if ((state->observed_fields & bit) && now_ms >= sampled_at &&
                now_ms - sampled_at < max_age_ms) {
                result.fresh_fields |= bit;
            }
        }
    }
    result.update_capacity = (result.fresh_fields & (UINT32_C(1) << BmCapacity)) != 0;
    result.update_external = (result.fresh_fields & (UINT32_C(1) << BmUsbOnline)) != 0;
    result.update_charging = result.update_external &&
        (result.fresh_fields & (UINT32_C(1) << BmStatus)) != 0;
    *decision = result;
    return FuxiBatteryPrepOk;
}

void fuxi_battery_prep_merge(FuxiAdspBattery *shown, const FuxiAdspBattery *incoming)
{
    if (!shown || !incoming) {
        return;
    }
    if (incoming->soc_known) {
        shown->percent = incoming->percent;
    }
    if (incoming->fresh_fields & (UINT32_C(1) << BmPresent)) {
        shown->present = incoming->present;
    }
    if (incoming->voltage_valid) {
        shown->voltage_mv = incoming->voltage_mv;
    }
    if (incoming->current_valid) {
        shown->current_ma = incoming->current_ma;
    }
    if (incoming->temperature_valid) {
        shown->temperature = incoming->temperature;
    }
    if (incoming->fresh_fields & (UINT32_C(1) << BmGauge1Remaining)) {
        shown->raw_mah = incoming->raw_mah;
    }
    if (incoming->fresh_fields & (UINT32_C(1) << BmFull)) {
        shown->full_mah = incoming->full_mah;
    }
    if (incoming->fresh_fields & (UINT32_C(1) << BmDesign)) {
        shown->design_mah = incoming->design_mah;
    }
    if (incoming->fresh_fields & (UINT32_C(1) << BmCycles)) {
        shown->cycles = incoming->cycles;
    }
    if (incoming->fresh_fields & (UINT32_C(1) << BmTimeToEmpty)) {
        shown->minutes_to_empty = incoming->minutes_to_empty;
    }
    if (incoming->fresh_fields & (UINT32_C(1) << BmTimeToFull)) {
        shown->minutes_to_full = incoming->minutes_to_full;
    }
    if (incoming->external_known) {
        shown->external = incoming->external;
        if (!incoming->external) {
            shown->charging = 0;
            shown->fully_charged = 0;
            shown->adapter_family = 0;
            shown->adapter_mv = 0;
            shown->adapter_ma = 0;
            shown->adapter_watts = 0;
        } else {
            if (incoming->fresh_fields & (UINT32_C(1) << BmUsbAdapter)) {
                shown->adapter_family = incoming->adapter_family;
            }
            if (incoming->fresh_fields & (UINT32_C(1) << BmUsbVoltage)) {
                shown->adapter_mv = incoming->adapter_mv;
            }
            if (incoming->fresh_fields & (UINT32_C(1) << BmUsbCurrent)) {
                shown->adapter_ma = incoming->adapter_ma;
            }
            if ((incoming->fresh_fields & (UINT32_C(1) << BmUsbVoltage)) &&
                (incoming->fresh_fields & (UINT32_C(1) << BmUsbCurrent))) {
                shown->adapter_watts = incoming->adapter_watts;
            }
        }
    }
    if (incoming->status_known) {
        shown->charging = incoming->charging;
        shown->fully_charged = incoming->fully_charged;
    }
    shown->sequence = incoming->sequence;
    shown->generation = incoming->generation;
    shown->fresh_fields = incoming->fresh_fields;
    shown->max_age_ms = incoming->max_age_ms;
    shown->soc_age_ms = incoming->soc_age_ms;
    shown->external_age_ms = incoming->external_age_ms;
    shown->status_age_ms = incoming->status_age_ms;
    shown->soc_known = incoming->soc_known;
    shown->external_known = incoming->external_known;
    shown->status_known = incoming->status_known;
    shown->voltage_valid = incoming->voltage_valid;
    shown->current_valid = incoming->current_valid;
    shown->temperature_valid = incoming->temperature_valid;
    shown->channel_up = incoming->channel_up;
    shown->stale = incoming->stale;
}
