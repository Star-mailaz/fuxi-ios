#include "fuxi_battery_freshness.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks;

#define CHECK(condition) do { \
    checks++; \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        exit(1); \
    } \
} while (0)

static void test_disconnect_and_generation(void)
{
    FuxiBatteryFreshness state;
    FuxiBatteryPublishDecision decision;
    uint64_t old_generation;

    CHECK(fuxi_battery_prep_init(&state) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_decide(&state, 0, 90000, &decision) == FuxiBatteryPrepOk);
    CHECK(decision.fresh_fields == 0);
    CHECK(fuxi_battery_prep_channel(&state, 1) == FuxiBatteryPrepOk);
    old_generation = state.generation;
    CHECK(fuxi_battery_prep_observe(&state, old_generation, BmCapacity, 0, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_observe(&state, old_generation, BmUsbOnline, 0, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_observe(&state, old_generation, BmStatus, 0, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_decide(&state, 1, 90000, &decision) == FuxiBatteryPrepOk);
    CHECK(decision.update_capacity && decision.update_external && decision.update_charging);
    CHECK(fuxi_battery_prep_channel(&state, 0) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_decide(&state, 2, 90000, &decision) == FuxiBatteryPrepOk);
    CHECK(decision.fresh_fields == 0 && !decision.update_external && !decision.update_charging);
    CHECK(fuxi_battery_prep_observe(&state, old_generation, BmUsbOnline, 2, 1) == FuxiBatteryPrepDisconnected);
    CHECK(fuxi_battery_prep_channel(&state, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_observe(&state, old_generation, BmUsbOnline, 3, 1) == FuxiBatteryPrepGeneration);
    CHECK(fuxi_battery_prep_decide(&state, 3, 90000, &decision) == FuxiBatteryPrepOk);
    CHECK(decision.fresh_fields == 0);
    CHECK(fuxi_battery_prep_observe(&state, state.generation, BmUsbOnline, 3, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_decide(&state, 3, 90000, &decision) == FuxiBatteryPrepOk);
    CHECK(!decision.update_capacity && decision.update_external && !decision.update_charging);
}

static void test_independent_ages(void)
{
    FuxiBatteryFreshness state;
    FuxiBatteryPublishDecision decision;

    CHECK(fuxi_battery_prep_init(&state) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_channel(&state, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_observe(&state, state.generation, BmUsbOnline, 0, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_observe(&state, state.generation, BmStatus, 0, 1) == FuxiBatteryPrepOk);
    for (uint64_t now = 1; now <= 200000; now += 1000) {
        CHECK(fuxi_battery_prep_observe(&state, state.generation, BmCapacity, now, 1) == FuxiBatteryPrepOk);
        CHECK(fuxi_battery_prep_observe(&state, state.generation, BmUsbOnline, now, 0) == FuxiBatteryPrepOk);
        CHECK(fuxi_battery_prep_observe(&state, state.generation, BmStatus, now, 0) == FuxiBatteryPrepOk);
        CHECK(fuxi_battery_prep_decide(&state, now, 90000, &decision) == FuxiBatteryPrepOk);
        CHECK(decision.update_capacity);
        CHECK(decision.update_external == (now < 90000));
        CHECK(decision.update_charging == (now < 90000));
    }
    CHECK(fuxi_battery_prep_decide(&state, 90000, 90000, &decision) == FuxiBatteryPrepOk);
    CHECK(!decision.update_external && !decision.update_charging);
}

static void test_real_unplug_policy(void)
{
    FuxiBatteryFreshness state;
    FuxiBatteryPublishDecision decision;
    int shown_percent = 100;
    int shown_external = 1;
    int shown_charging = 1;
    const int measured_external = 0;

    CHECK(fuxi_battery_prep_init(&state) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_channel(&state, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_observe(&state, state.generation, BmUsbOnline, 100, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_decide(&state, 100, 90000, &decision) == FuxiBatteryPrepOk);
    CHECK(decision.update_external && !decision.update_capacity && !decision.update_charging);
    if (decision.update_external) {
        shown_external = measured_external;
        if (!measured_external) {
            shown_charging = 0;
        }
    }
    CHECK(shown_external == 0 && shown_percent == 100 && shown_charging == 0);
    CHECK(fuxi_battery_prep_channel(&state, 0) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_decide(&state, 101, 90000, &decision) == FuxiBatteryPrepOk);
    CHECK(!decision.update_capacity && !decision.update_external && !decision.update_charging);
    CHECK(shown_external == 0 && shown_percent == 100);
}

static void test_every_field_and_boundaries(void)
{
    FuxiBatteryFreshness state;
    FuxiBatteryPublishDecision decision;
    FuxiBatteryPublishDecision before;

    CHECK(fuxi_battery_prep_init(NULL) == FuxiBatteryPrepArgument);
    CHECK(fuxi_battery_prep_channel(NULL, 1) == FuxiBatteryPrepArgument);
    CHECK(fuxi_battery_prep_init(&state) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_observe(NULL, 0, 0, 0, 1) == FuxiBatteryPrepArgument);
    CHECK(fuxi_battery_prep_observe(&state, 0, BmFields, 0, 1) == FuxiBatteryPrepArgument);
    CHECK(fuxi_battery_prep_decide(&state, 0, 1, NULL) == FuxiBatteryPrepArgument);
    memset(&decision, 0xa5, sizeof(decision));
    memcpy(&before, &decision, sizeof(before));
    CHECK(fuxi_battery_prep_decide(&state, 0, 0, &decision) == FuxiBatteryPrepArgument);
    CHECK(memcmp(&before, &decision, sizeof(decision)) == 0);
    for (unsigned field = 0; field < BmFields; field++) {
        CHECK(fuxi_battery_prep_channel(&state, 0) == FuxiBatteryPrepOk);
        CHECK(fuxi_battery_prep_channel(&state, 1) == FuxiBatteryPrepOk);
        CHECK(fuxi_battery_prep_observe(&state, state.generation, field, 100, 1) == FuxiBatteryPrepOk);
        CHECK(fuxi_battery_prep_decide(&state, 99, 10, &decision) == FuxiBatteryPrepOk);
        CHECK(decision.fresh_fields == 0);
        CHECK(fuxi_battery_prep_decide(&state, 109, 10, &decision) == FuxiBatteryPrepOk);
        CHECK(decision.fresh_fields == (UINT32_C(1) << field));
        CHECK(fuxi_battery_prep_decide(&state, 110, 10, &decision) == FuxiBatteryPrepOk);
        CHECK(decision.fresh_fields == 0);
        CHECK(fuxi_battery_prep_observe(&state, state.generation, field, 99, 1) == FuxiBatteryPrepTime);
        CHECK(state.successful_at_ms[field] == 100);
    }
    CHECK(fuxi_battery_prep_observe(&state, state.generation, BmUsbOnline,
        UINT64_MAX - 1, 1) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_decide(&state, UINT64_MAX, 2, &decision) == FuxiBatteryPrepOk);
    CHECK(decision.update_external);
    CHECK(fuxi_battery_prep_decide(&state, 0, UINT64_MAX, &decision) == FuxiBatteryPrepOk);
    CHECK(decision.fresh_fields == 0);
    state.generation = UINT64_MAX;
    CHECK(fuxi_battery_prep_channel(&state, 0) == FuxiBatteryPrepGeneration);
    CHECK(!state.channel_up && state.observed_fields == 0);
    CHECK(fuxi_battery_prep_channel(&state, 1) == FuxiBatteryPrepGeneration);
    CHECK(!state.channel_up);
}

static void test_production_merge(void)
{
    FuxiAdspBattery shown = {0};
    FuxiAdspBattery incoming = {0};

    shown.percent = 100;
    shown.voltage_mv = 4200;
    shown.temperature = 2500;
    shown.full_mah = shown.design_mah = 5020;
    shown.present = shown.external = shown.fully_charged = 1;
    shown.minutes_to_empty = shown.minutes_to_full = -1;
    incoming.stale = 1;
    incoming.max_age_ms = FUXI_BATTERY_DEFAULT_MAX_AGE_MS;
    incoming.soc_age_ms = incoming.external_age_ms = incoming.status_age_ms = ~(uint32_t)0;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.sequence == 0 && shown.stale && !shown.channel_up);
    CHECK(shown.percent == 100 && shown.voltage_mv == 4200 && shown.temperature == 2500);
    CHECK(shown.present && shown.external && shown.fully_charged && !shown.charging);
    CHECK(!shown.soc_known && !shown.external_known && !shown.status_known);
    CHECK(!shown.voltage_valid && !shown.current_valid && !shown.temperature_valid);
    CHECK(shown.max_age_ms == 90000 && shown.soc_age_ms == ~(uint32_t)0);

    incoming.sequence = 1;
    incoming.generation = 1;
    incoming.channel_up = incoming.soc_known = incoming.external_known = incoming.status_known = 1;
    incoming.voltage_valid = incoming.current_valid = incoming.temperature_valid = 1;
    incoming.stale = 0;
    incoming.fresh_fields = ~(uint32_t)0;
    incoming.percent = 97;
    incoming.present = incoming.external = incoming.charging = 1;
    incoming.voltage_mv = 4300;
    incoming.current_ma = 100;
    incoming.temperature = 2800;
    incoming.raw_mah = 4200;
    incoming.full_mah = 4500;
    incoming.design_mah = 4500;
    incoming.cycles = 83;
    incoming.minutes_to_empty = 360;
    incoming.minutes_to_full = 40;
    incoming.adapter_family = 0xe000400au;
    incoming.adapter_mv = 9000;
    incoming.adapter_ma = 2000;
    incoming.adapter_watts = 18;
    incoming.soc_age_ms = incoming.external_age_ms = incoming.status_age_ms = 0;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.sequence == 1 && shown.generation == 1 && !shown.stale);
    CHECK(shown.percent == 97 && shown.external && shown.charging && !shown.fully_charged);
    CHECK(shown.voltage_mv == 4300 && shown.current_ma == 100 && shown.temperature == 2800);
    CHECK(shown.raw_mah == 4200 && shown.full_mah == 4500 && shown.design_mah == 4500);
    CHECK(shown.cycles == 83 && shown.minutes_to_empty == 360 && shown.minutes_to_full == 40);
    CHECK(shown.adapter_family == 0xe000400au && shown.adapter_watts == 18);

    incoming.sequence++;
    incoming.percent = 96;
    incoming.fresh_fields = UINT32_C(1) << BmCapacity;
    incoming.external_known = incoming.status_known = 0;
    incoming.voltage_valid = incoming.current_valid = incoming.temperature_valid = 0;
    incoming.external = incoming.charging = incoming.fully_charged = 0;
    incoming.present = 0;
    incoming.voltage_mv = incoming.current_ma = incoming.temperature = 0;
    incoming.raw_mah = incoming.full_mah = incoming.design_mah = incoming.cycles = 0;
    incoming.adapter_family = 0;
    incoming.adapter_mv = incoming.adapter_ma = incoming.adapter_watts = 0;
    incoming.minutes_to_empty = incoming.minutes_to_full = -1;
    incoming.external_age_ms = incoming.status_age_ms = 90000;
    incoming.stale = 1;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.percent == 96 && shown.soc_known && shown.stale);
    CHECK(shown.present && shown.external && shown.charging && !shown.fully_charged);
    CHECK(!shown.external_known && !shown.status_known);
    CHECK(!shown.voltage_valid && !shown.current_valid && !shown.temperature_valid);
    CHECK(shown.voltage_mv == 4300 && shown.current_ma == 100 && shown.temperature == 2800);
    CHECK(shown.raw_mah == 4200 && shown.full_mah == 4500 && shown.design_mah == 4500);
    CHECK(shown.cycles == 83 && shown.minutes_to_empty == 360 && shown.minutes_to_full == 40);
    CHECK(shown.adapter_family == 0xe000400au && shown.adapter_mv == 9000);
    CHECK(shown.adapter_ma == 2000 && shown.adapter_watts == 18);
    CHECK(shown.external_age_ms == 90000 && shown.status_age_ms == 90000);

    incoming.sequence++;
    incoming.soc_known = 0;
    incoming.percent = 0;
    incoming.external_known = incoming.status_known = 1;
    incoming.fresh_fields = UINT32_C(1) << BmUsbOnline;
    incoming.external_age_ms = 0;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.percent == 96 && !shown.soc_known && shown.stale);
    CHECK(shown.external_known && shown.status_known && !shown.external);
    CHECK(!shown.charging && !shown.fully_charged && shown.present);
    CHECK(!shown.adapter_family && !shown.adapter_mv && !shown.adapter_ma && !shown.adapter_watts);
    CHECK(shown.status_age_ms == 90000 && shown.external_age_ms == 0);

    incoming.generation = 2;
    incoming.channel_up = incoming.external_known = incoming.status_known = 0;
    incoming.fresh_fields = 0;
    incoming.external = incoming.charging = incoming.fully_charged = 1;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.generation == 2 && !shown.channel_up && shown.stale);
    CHECK(!shown.external && !shown.charging && !shown.fully_charged);
    CHECK(shown.percent == 96 && shown.voltage_mv == 4300 && !shown.voltage_valid);
    incoming.generation = 3;
    incoming.channel_up = 1;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.channel_up && shown.generation == 3 && shown.fresh_fields == 0);
    CHECK(!shown.external_known && !shown.status_known && !shown.external);

    incoming.sequence++;
    incoming.external_known = 1;
    incoming.fresh_fields = (UINT32_C(1) << BmUsbOnline) | (UINT32_C(1) << BmUsbVoltage);
    incoming.adapter_mv = 5000;
    incoming.adapter_ma = 3000;
    incoming.adapter_watts = 15;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.external && !shown.status_known && !shown.charging && !shown.fully_charged);
    CHECK(shown.adapter_mv == 5000 && !shown.adapter_ma && !shown.adapter_watts);
    incoming.fresh_fields |= UINT32_C(1) << BmUsbCurrent;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.adapter_mv == 5000 && shown.adapter_ma == 3000 && shown.adapter_watts == 15);

    incoming.sequence++;
    incoming.soc_known = incoming.status_known = incoming.voltage_valid = 1;
    incoming.current_valid = incoming.temperature_valid = 1;
    incoming.fresh_fields = ~(uint32_t)0;
    incoming.percent = 92;
    incoming.present = 1;
    incoming.voltage_mv = 4100;
    incoming.current_ma = 75;
    incoming.temperature = 2700;
    incoming.charging = 1;
    incoming.fully_charged = 0;
    incoming.stale = 0;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.percent == 92 && !shown.stale && shown.soc_known && shown.voltage_valid);
    CHECK(shown.external && shown.charging && shown.status_known && !shown.fully_charged);
    CHECK(shown.current_ma == 75 && shown.current_valid && shown.temperature == 2700);
    CHECK(shown.temperature_valid && shown.cycles == 0);

    incoming.sequence++;
    incoming.stale = 1;
    incoming.soc_known = incoming.external_known = incoming.status_known = 0;
    incoming.voltage_valid = incoming.current_valid = incoming.temperature_valid = 0;
    incoming.fresh_fields = 0;
    incoming.percent = 100;
    incoming.voltage_mv = 4200;
    incoming.charging = 0;
    incoming.fully_charged = 1;
    fuxi_battery_prep_merge(&shown, &incoming);
    CHECK(shown.percent == 92 && shown.voltage_mv == 4100 && shown.stale);
    CHECK(shown.external && shown.charging && !shown.fully_charged);
    CHECK(!shown.soc_known && !shown.external_known && !shown.status_known);
    fuxi_battery_prep_merge(NULL, &incoming);
    fuxi_battery_prep_merge(&shown, NULL);
    CHECK(shown.percent == 92 && shown.voltage_mv == 4100);
}

int main(void)
{
    test_disconnect_and_generation();
    test_independent_ages();
    test_real_unplug_policy();
    test_every_field_and_boundaries();
    test_production_merge();
    printf("PASS fuxi-battery-prep freshness: %u checks\n", checks);
    return 0;
}
