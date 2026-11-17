import argparse
import hashlib
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "xnu" / "fuxi-battery-prep"
ADSP = ROOT / "xnu" / "fuxi-adsp"
HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fuxi_battery_poll_pause.h"

static unsigned checks;
#define CHECK(expression) do { checks++; if (!(expression)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #expression); exit(1); \
} } while (0)

static void observe(FuxiBatteryFreshness *freshness, unsigned field, uint64_t now_ms)
{
    CHECK(fuxi_battery_prep_observe(freshness, freshness->generation,
        field, now_ms, 1) == FuxiBatteryPrepOk);
}

static void baseline(FuxiBatteryFreshness *freshness, uint64_t now_ms)
{
    CHECK(fuxi_battery_prep_init(freshness) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_channel(freshness, 1) == FuxiBatteryPrepOk);
    observe(freshness, BmCapacity, now_ms);
    observe(freshness, BmUsbOnline, now_ms);
    observe(freshness, BmStatus, now_ms);
}

static FuxiBatteryPollPauseDecision step(FuxiBatteryPollPause *pause,
    FuxiBatteryFreshness *freshness, FuxiAdspBattery *published,
    uint64_t now_ms, int quiescent)
{
    FuxiBatteryFreshness before;
    FuxiAdspBattery shown;
    memcpy(&before, freshness, sizeof before);
    memcpy(&shown, published, sizeof shown);
    const FuxiBatteryPollPauseDecision decision = fuxi_battery_poll_pause_step(
        pause, freshness, now_ms, published->max_age_ms, quiescent);
    CHECK(memcmp(&before, freshness, sizeof before) == 0);
    CHECK(memcmp(&shown, published, sizeof shown) == 0);
    CHECK(decision.withhold_get == (decision.phase == FuxiBatteryPollPauseHolding));
    CHECK(!decision.withhold_get || decision.wake_at_ms > now_ms);
    CHECK(!decision.withhold_get || decision.wake_at_ms - now_ms <=
        FUXI_BATTERY_POLL_PAUSE_MAX_DURATION_MS);
    return decision;
}

static FuxiBatteryPublishDecision fresh_at(const FuxiBatteryFreshness *freshness,
    uint64_t now_ms, uint32_t ttl_ms)
{
    FuxiBatteryPublishDecision decision;
    CHECK(fuxi_battery_prep_decide(freshness, now_ms, ttl_ms, &decision) == FuxiBatteryPrepOk);
    return decision;
}

static void test_default_and_config(void)
{
    FuxiBatteryPollPause pause = {0}, before;
    memcpy(&before, &pause, sizeof before);
    FuxiBatteryPollPauseDecision decision = fuxi_battery_poll_pause_step(
        &pause, NULL, UINT64_MAX, 0, 0);
    CHECK(decision.phase == FuxiBatteryPollPauseOff && !decision.withhold_get);
    CHECK(!decision.wake_at_ms && !decision.pause_once && !decision.resume_once);
    CHECK(memcmp(&pause, &before, sizeof before) == 0);
    CHECK(FUXI_BATTERY_POLL_PAUSE_DEFAULT_MS == 0);
    CHECK(fuxi_battery_poll_pause_init(&pause, UINT64_MAX, 0) == 0);
    CHECK(!pause.clock_seen && !pause.generation && !pause.delay_ms);
    decision = fuxi_battery_poll_pause_step(&pause, NULL, 0, 0, 0);
    CHECK(decision.phase == FuxiBatteryPollPauseOff);
    CHECK(fuxi_battery_poll_pause_init(NULL, 0, 92000) == -1);
    decision = fuxi_battery_poll_pause_step(NULL, NULL, 0, 0, 0);
    CHECK(decision.reason == FuxiBatteryPollPauseArgument && !decision.withhold_get);
    const uint64_t bad_duration[] = {1, 999, 300001, UINT32_MAX, UINT64_MAX};
    for (unsigned index = 0; index < sizeof bad_duration / sizeof bad_duration[0]; index++) {
        CHECK(fuxi_battery_poll_pause_init(&pause, 0, bad_duration[index]) == -1);
        CHECK(pause.reason == FuxiBatteryPollPauseConfig);
        decision = fuxi_battery_poll_pause_step(&pause, NULL, UINT64_MAX, 0, 1);
        CHECK(!decision.withhold_get && !decision.wake_at_ms);
    }
    CHECK(fuxi_battery_poll_pause_init(&pause, 60001, 92000) == -1);
    CHECK(fuxi_battery_poll_pause_init(&pause, UINT64_MAX, 92000) == -1);
    CHECK(fuxi_battery_poll_pause_init(&pause, 60000, 300000) == 0);
    decision = fuxi_battery_poll_pause_step(&pause, NULL, 0, 90000, 1);
    CHECK(decision.reason == FuxiBatteryPollPauseArgument && !decision.withhold_get);
}

static void test_bootstrap_delay_and_once(void)
{
    FuxiBatteryFreshness freshness;
    FuxiAdspBattery published = {0};
    FuxiBatteryPollPause pause;
    published.max_age_ms = FUXI_BATTERY_DEFAULT_MAX_AGE_MS;
    CHECK(fuxi_battery_prep_init(&freshness) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_poll_pause_init(&pause, 100, 92000) == 0);
    CHECK(step(&pause, &freshness, &published, 0, 1).phase == FuxiBatteryPollPauseWaiting);
    CHECK(fuxi_battery_prep_channel(&freshness, 1) == FuxiBatteryPrepOk);
    CHECK(step(&pause, &freshness, &published, 1, 1).phase == FuxiBatteryPollPauseWaiting);
    observe(&freshness, BmCapacity, 1);
    CHECK(step(&pause, &freshness, &published, 1, 1).phase == FuxiBatteryPollPauseWaiting);
    observe(&freshness, BmUsbOnline, 1);
    CHECK(step(&pause, &freshness, &published, 1, 1).phase == FuxiBatteryPollPauseWaiting);
    observe(&freshness, BmStatus, 1);
    CHECK(step(&pause, &freshness, &published, 1, 0).phase == FuxiBatteryPollPauseWaiting);
    FuxiBatteryPollPauseDecision decision = step(&pause, &freshness, &published, 1, 1);
    CHECK(decision.phase == FuxiBatteryPollPauseArmed && decision.wake_at_ms == 101);
    CHECK(pause.generation == freshness.generation && pause.max_age_ms == published.max_age_ms);
    CHECK(!decision.pause_once && !decision.withhold_get);
    decision = step(&pause, &freshness, &published, 100, 1);
    CHECK(!decision.withhold_get && decision.wake_at_ms == 101);
    decision = step(&pause, &freshness, &published, 101, 0);
    CHECK(!decision.withhold_get && decision.wake_at_ms == 92101);
    decision = step(&pause, &freshness, &published, 103, 1);
    CHECK(decision.withhold_get && decision.pause_once && decision.wake_at_ms == 92103);
    decision = step(&pause, &freshness, &published, 103, 1);
    CHECK(decision.withhold_get && !decision.pause_once && !decision.resume_once);
    decision = step(&pause, &freshness, &published, 92102, 1);
    CHECK(decision.withhold_get && !decision.resume_once);
    decision = step(&pause, &freshness, &published, 92103, 1);
    CHECK(!decision.withhold_get && decision.resume_once && !decision.wake_at_ms);
    CHECK(decision.phase == FuxiBatteryPollPauseDone);
    baseline(&freshness, 93000);
    decision = step(&pause, &freshness, &published, 93000, 1);
    CHECK(!decision.withhold_get && !decision.resume_once && !decision.pause_once);
    CHECK(decision.phase == FuxiBatteryPollPauseDone);
}

static void test_ttl_and_retained_values(void)
{
    FuxiBatteryFreshness freshness;
    FuxiBatteryPollPause pause;
    FuxiAdspBattery published = {0};
    baseline(&freshness, 1000);
    published.max_age_ms = FUXI_BATTERY_DEFAULT_MAX_AGE_MS;
    published.percent = 73;
    published.external = 1;
    published.charging = 1;
    published.voltage_mv = 4200;
    published.current_ma = 500;
    published.generation = freshness.generation;
    CHECK(fuxi_battery_poll_pause_init(&pause, 0, 92000) == 0);
    CHECK(step(&pause, &freshness, &published, 1000, 1).pause_once);
    FuxiBatteryPublishDecision validity = fresh_at(&freshness, 90999, published.max_age_ms);
    CHECK(validity.update_capacity && validity.update_external && validity.update_charging);
    CHECK(step(&pause, &freshness, &published, 91000, 1).withhold_get);
    validity = fresh_at(&freshness, 91000, published.max_age_ms);
    CHECK(!validity.fresh_fields && !validity.update_capacity && !validity.update_external);
    CHECK(!validity.update_charging);
    FuxiAdspBattery incoming = {0};
    incoming.generation = freshness.generation;
    incoming.channel_up = (uint8_t)freshness.channel_up;
    incoming.max_age_ms = published.max_age_ms;
    incoming.fresh_fields = validity.fresh_fields;
    incoming.soc_age_ms = 90000;
    incoming.external_age_ms = 90000;
    incoming.status_age_ms = 90000;
    incoming.stale = 1;
    fuxi_battery_prep_merge(&published, &incoming);
    CHECK(published.percent == 73 && published.external == 1 && published.charging == 1);
    CHECK(published.voltage_mv == 4200 && published.current_ma == 500);
    CHECK(published.stale && !published.soc_known && !published.external_known);
    CHECK(!published.status_known && !published.voltage_valid && !published.current_valid);
    CHECK(published.channel_up && published.generation == pause.generation);
    CHECK(published.external_age_ms == published.max_age_ms);
    CHECK(step(&pause, &freshness, &published, 93000, 1).resume_once);
    observe(&freshness, BmCapacity, 93000);
    validity = fresh_at(&freshness, 93000, published.max_age_ms);
    CHECK(validity.update_capacity && !validity.update_external && !validity.update_charging);
    CHECK(fuxi_battery_prep_observe(&freshness, freshness.generation,
        BmUsbOnline, 93000, 0) == FuxiBatteryPrepOk);
    CHECK(freshness.successful_at_ms[BmUsbOnline] == 1000);
    observe(&freshness, BmUsbOnline, 93001);
    validity = fresh_at(&freshness, 93001, published.max_age_ms);
    CHECK(validity.update_external && !validity.update_charging);
    observe(&freshness, BmStatus, 93002);
    CHECK(fresh_at(&freshness, 93002, published.max_age_ms).update_charging);
}

static void test_generation_and_channel(void)
{
    for (unsigned mode = 0; mode < 4; mode++) {
        FuxiBatteryFreshness freshness;
        FuxiBatteryPollPause pause;
        FuxiAdspBattery published = {0};
        baseline(&freshness, 1000);
        published.max_age_ms = 90000;
        CHECK(fuxi_battery_poll_pause_init(&pause, mode < 2 ? 100 : 0, 92000) == 0);
        FuxiBatteryPollPauseDecision decision = step(&pause, &freshness, &published, 1000, 1);
        const int was_holding = decision.withhold_get;
        const uint64_t old_generation = freshness.generation;
        CHECK(fuxi_battery_prep_channel(&freshness, 0) == FuxiBatteryPrepOk);
        if (mode % 2) {
            CHECK(fuxi_battery_prep_channel(&freshness, 1) == FuxiBatteryPrepOk);
        }
        decision = step(&pause, &freshness, &published, 1001, 1);
        CHECK(!decision.withhold_get && decision.phase == FuxiBatteryPollPauseCancelled);
        CHECK(decision.resume_once == was_holding && !decision.wake_at_ms);
        CHECK(decision.reason == (mode % 2 ? FuxiBatteryPollPauseGeneration : FuxiBatteryPollPauseChannel));
        CHECK(!fresh_at(&freshness, 1001, 90000).fresh_fields);
        if (!(mode % 2)) {
            CHECK(fuxi_battery_prep_channel(&freshness, 1) == FuxiBatteryPrepOk);
        }
        CHECK(fuxi_battery_prep_observe(&freshness, old_generation,
            BmCapacity, 1002, 1) == FuxiBatteryPrepGeneration);
        CHECK(!freshness.observed_fields);
        observe(&freshness, BmCapacity, 1002);
        observe(&freshness, BmUsbOnline, 1002);
        observe(&freshness, BmStatus, 1002);
        decision = step(&pause, &freshness, &published, 1002, 1);
        CHECK(!decision.withhold_get && !decision.pause_once && !decision.resume_once);
    }
    for (unsigned mode = 0; mode < 2; mode++) {
        FuxiBatteryFreshness freshness;
        FuxiBatteryPollPause pause;
        FuxiAdspBattery published = {0};
        baseline(&freshness, 1);
        published.max_age_ms = 90000;
        freshness.generation = mode ? UINT64_MAX : 0;
        CHECK(fuxi_battery_poll_pause_init(&pause, 0, 92000) == 0);
        CHECK(step(&pause, &freshness, &published, 1, 1).reason == FuxiBatteryPollPauseGeneration);
    }
}

static void test_clock_ttl_and_windows(void)
{
    for (unsigned mode = 0; mode < 3; mode++) {
        FuxiBatteryFreshness freshness;
        FuxiBatteryPollPause pause;
        FuxiAdspBattery published = {0};
        baseline(&freshness, 1000);
        published.max_age_ms = 90000;
        CHECK(fuxi_battery_poll_pause_init(&pause, mode == 1 ? 100 : 0, 92000) == 0);
        const FuxiBatteryPollPauseDecision before = step(&pause, &freshness,
            &published, 1000, mode != 0);
        FuxiBatteryPollPauseDecision decision = step(&pause, &freshness, &published, 999, 1);
        CHECK(decision.reason == FuxiBatteryPollPauseClock && !decision.withhold_get);
        CHECK(decision.resume_once == before.withhold_get);
        CHECK(step(&pause, &freshness, &published, 1001, 1).phase == FuxiBatteryPollPauseCancelled);
    }
    const uint32_t ttls[] = {0, 1, 2000, 90000, 299000, 299001, 3600000, UINT32_MAX};
    for (unsigned index = 0; index < sizeof ttls / sizeof ttls[0]; index++) {
        FuxiBatteryFreshness freshness;
        FuxiBatteryPollPause pause;
        FuxiAdspBattery published = {0};
        baseline(&freshness, 0);
        published.max_age_ms = ttls[index];
        CHECK(fuxi_battery_poll_pause_init(&pause, 0, 300000) == 0);
        FuxiBatteryPollPauseDecision decision = step(&pause, &freshness, &published, 0, 1);
        const int supported = ttls[index] && ttls[index] <= 299000;
        CHECK(decision.withhold_get == supported);
        if (supported) {
            CHECK(!fresh_at(&freshness, ttls[index], ttls[index]).fresh_fields);
            published.max_age_ms++;
            decision = step(&pause, &freshness, &published, 1, 1);
        }
        CHECK(decision.reason == FuxiBatteryPollPauseTtl && !decision.withhold_get);
    }
    FuxiBatteryFreshness freshness;
    FuxiBatteryPollPause pause;
    FuxiAdspBattery published = {0};
    baseline(&freshness, 1000);
    published.max_age_ms = 2000;
    CHECK(fuxi_battery_poll_pause_init(&pause, 100, 4000) == 0);
    CHECK(step(&pause, &freshness, &published, 1000, 1).phase == FuxiBatteryPollPauseArmed);
    CHECK(step(&pause, &freshness, &published, 1100, 0).phase == FuxiBatteryPollPauseArmed);
    CHECK(step(&pause, &freshness, &published, 5100, 1).reason == FuxiBatteryPollPauseMissedWindow);
    CHECK(fuxi_battery_poll_pause_init(&pause, 3000, 4000) == 0);
    CHECK(step(&pause, &freshness, &published, 1000, 1).phase == FuxiBatteryPollPauseArmed);
    CHECK(step(&pause, &freshness, &published, 4000, 1).reason == FuxiBatteryPollPauseBaseline);
    baseline(&freshness, 1001);
    CHECK(fuxi_battery_poll_pause_init(&pause, 0, 4000) == 0);
    CHECK(step(&pause, &freshness, &published, 1000, 1).phase == FuxiBatteryPollPauseWaiting);
    CHECK(step(&pause, &freshness, &published, 1001, 1).pause_once);
}

static void test_overflow(void)
{
    FuxiBatteryFreshness freshness;
    FuxiBatteryPollPause pause;
    FuxiAdspBattery published = {0};
    published.max_age_ms = 2000;
    baseline(&freshness, UINT64_MAX - 50);
    CHECK(fuxi_battery_poll_pause_init(&pause, 100, 4000) == 0);
    CHECK(step(&pause, &freshness, &published, UINT64_MAX - 50, 1).reason == FuxiBatteryPollPauseOverflow);
    baseline(&freshness, UINT64_MAX - 3999);
    CHECK(fuxi_battery_poll_pause_init(&pause, 0, 4000) == 0);
    CHECK(step(&pause, &freshness, &published, UINT64_MAX - 3999, 1).reason == FuxiBatteryPollPauseOverflow);
    baseline(&freshness, UINT64_MAX - 4000);
    CHECK(fuxi_battery_poll_pause_init(&pause, 0, 4000) == 0);
    CHECK(step(&pause, &freshness, &published, UINT64_MAX - 4000, 1).wake_at_ms == UINT64_MAX);
    CHECK(step(&pause, &freshness, &published, UINT64_MAX, 1).resume_once);
    baseline(&freshness, UINT64_MAX - 4050);
    CHECK(fuxi_battery_poll_pause_init(&pause, 0, 4000) == 0);
    CHECK(step(&pause, &freshness, &published, UINT64_MAX - 4050, 0).phase == FuxiBatteryPollPauseWaiting);
    CHECK(fuxi_battery_poll_pause_init(&pause, 1, 4000) == 0);
    CHECK(step(&pause, &freshness, &published, UINT64_MAX - 4050, 1).phase == FuxiBatteryPollPauseArmed);
    CHECK(step(&pause, &freshness, &published, UINT64_MAX - 4049, 0).phase == FuxiBatteryPollPauseArmed);
    CHECK(step(&pause, &freshness, &published, UINT64_MAX - 3999, 1).reason == FuxiBatteryPollPauseOverflow);
}

static uint32_t read32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 |
        (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}

static void write32(uint8_t *bytes, uint32_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
    bytes[2] = (uint8_t)(value >> 16);
    bytes[3] = (uint8_t)(value >> 24);
}

static int pending_set(const ShengBattmgr *codec)
{
    return codec->limit_due || (codec->keyboard_wanted >= 0 &&
        codec->keyboard_wanted != codec->keyboard_acked && codec->keyboard_tries < 3);
}

static uint32_t gated_next(ShengBattmgr *codec, int withhold_get, uint8_t *request)
{
    if (withhold_get && !pending_set(codec)) {
        return 0;
    }
    return sheng_battmgr_next(codec, request);
}

static void accept_get(ShengBattmgr *codec, FuxiBatteryFreshness *freshness,
    const uint8_t *request, uint64_t request_generation, uint64_t now_ms, int success)
{
    const unsigned field = codec->cursor;
    const uint32_t responses = codec->responses;
    uint8_t answer[SHENG_BATTMGR_REQUEST_BYTES];
    memcpy(answer, request, sizeof answer);
    write32(answer + 12, read32(request + 16));
    write32(answer + 16, field == BmCapacity ? 7300u : 1u);
    write32(answer + 20, success ? 0u : 1u);
    const int result = sheng_battmgr_receive(codec, answer, sizeof answer);
    CHECK(result == BmAnswer || result == BmCycleDone);
    CHECK(codec->responses == responses + 1);
    if (success && field < BmFields && (codec->valid & (UINT32_C(1) << field))) {
        CHECK(fuxi_battery_prep_observe(freshness, request_generation,
            field, now_ms, 1) == FuxiBatteryPrepOk);
    }
}

static void test_real_codec_gate_and_late_reply(void)
{
    FuxiBatteryFreshness freshness;
    FuxiBatteryPollPause pause;
    FuxiAdspBattery published = {0};
    ShengBattmgr codec;
    uint8_t request[SHENG_BATTMGR_REQUEST_BYTES];
    unsigned gets = 0;
    published.max_age_ms = 90000;
    CHECK(fuxi_battery_prep_init(&freshness) == FuxiBatteryPrepOk);
    CHECK(fuxi_battery_prep_channel(&freshness, 1) == FuxiBatteryPrepOk);
    sheng_battmgr_init(&codec);
    sheng_battmgr_refresh(&codec, 1);
    for (unsigned index = 0; index < BmFields; index++) {
        CHECK(gated_next(&codec, 0, request) == sizeof request);
        const uint32_t opcode = read32(request + 8);
        CHECK(opcode == SHENG_BATTMGR_OP_BATTERY_GET || opcode == SHENG_BATTMGR_OP_USB_GET ||
            opcode == SHENG_BATTMGR_OP_BOARD_GET);
        gets++;
        accept_get(&codec, &freshness, request, freshness.generation, 1000,
            codec.cursor == BmCapacity || codec.cursor == BmUsbOnline || codec.cursor == BmStatus);
    }
    CHECK(fresh_at(&freshness, 1000, published.max_age_ms).update_charging);
    sheng_battmgr_refresh(&codec, 0);
    CHECK(fuxi_battery_poll_pause_init(&pause, 0, 92000) == 0);
    FuxiBatteryPollPauseDecision decision = step(&pause, &freshness, &published, 1000, 1);
    CHECK(decision.pause_once && decision.withhold_get);
    ShengBattmgr codec_before;
    memcpy(&codec_before, &codec, sizeof codec_before);
    for (uint64_t now_ms = 1000; now_ms < 93000; now_ms += 1000) {
        decision = step(&pause, &freshness, &published, now_ms, 1);
        CHECK(gated_next(&codec, decision.withhold_get, request) == 0);
        CHECK(memcmp(&codec_before, &codec, sizeof codec) == 0);
        CHECK(gets == BmFields);
    }
    uint8_t notification[16] = {0};
    write32(notification, SHENG_BATTMGR_OWNER);
    write32(notification + 4, SHENG_BATTMGR_TYPE_NOTIFY);
    write32(notification + 8, SHENG_BATTMGR_OP_NOTIFICATION);
    FuxiBatteryFreshness samples_before;
    memcpy(&samples_before, &freshness, sizeof samples_before);
    CHECK(sheng_battmgr_receive(&codec, notification, sizeof notification) == BmNotified);
    CHECK(memcmp(&samples_before, &freshness, sizeof freshness) == 0);
    CHECK(gated_next(&codec, 1, request) == 0);
    CHECK(!fresh_at(&freshness, 91000, published.max_age_ms).fresh_fields);
    decision = step(&pause, &freshness, &published, 93000, 1);
    CHECK(decision.resume_once && !decision.withhold_get);
    CHECK(gated_next(&codec, decision.withhold_get, request) == sizeof request);
    gets++;
    accept_get(&codec, &freshness, request, freshness.generation, 93000, 1);
    CHECK(gets == BmFields + 1 && fresh_at(&freshness, 93000, 90000).fresh_fields);

    baseline(&freshness, 1000);
    CHECK(fuxi_battery_poll_pause_init(&pause, 0, 92000) == 0);
    CHECK(step(&pause, &freshness, &published, 1000, 1).withhold_get);
    observe(&freshness, BmCapacity, 5000);
    CHECK(step(&pause, &freshness, &published, 5000, 1).wake_at_ms == 93000);
    FuxiBatteryPublishDecision validity = fresh_at(&freshness, 91000, 90000);
    CHECK(validity.update_capacity && !validity.update_external && !validity.update_charging);
    CHECK(step(&pause, &freshness, &published, 93000, 1).resume_once);
    CHECK(fresh_at(&freshness, 93000, 90000).update_capacity);
    CHECK(!fresh_at(&freshness, 95000, 90000).update_capacity);

    sheng_battmgr_init(&codec);
    codec.limit_due = 900000;
    CHECK(gated_next(&codec, 1, request) == sizeof request);
    CHECK(read32(request + 8) == SHENG_BATTMGR_OP_USB_SET);
    CHECK(codec.limit_in_flight == 900000 && !codec.in_flight);
    CHECK(gated_next(&codec, 1, request) == 0);
    sheng_battmgr_init(&codec);
    sheng_battmgr_keyboard(&codec, 1);
    CHECK(gated_next(&codec, 1, request) == sizeof request);
    CHECK(read32(request + 8) == SHENG_BATTMGR_OP_BOARD_SET);
    CHECK(codec.keyboard_in_flight == 1 && !codec.in_flight);
}

static void test_schedule_grid(void)
{
    for (uint32_t delay_ms = 0; delay_ms <= 60000; delay_ms += 10000) {
        for (uint32_t ttl_ms = 2000; ttl_ms <= 182000; ttl_ms += 30000) {
            FuxiBatteryFreshness freshness;
            FuxiBatteryPollPause pause;
            FuxiAdspBattery published = {0};
            baseline(&freshness, 100000);
            published.max_age_ms = ttl_ms;
            CHECK(fuxi_battery_poll_pause_init(&pause, delay_ms, ttl_ms + 1000) == 0);
            FuxiBatteryPollPauseDecision decision = step(&pause, &freshness, &published, 100000, 1);
            if (delay_ms) {
                CHECK(decision.phase == FuxiBatteryPollPauseArmed);
                observe(&freshness, BmCapacity, 100000 + delay_ms);
                observe(&freshness, BmUsbOnline, 100000 + delay_ms);
                observe(&freshness, BmStatus, 100000 + delay_ms);
                decision = step(&pause, &freshness, &published, 100000 + delay_ms, 1);
            }
            CHECK(decision.withhold_get && decision.pause_once);
            const uint64_t end = decision.wake_at_ms;
            CHECK(!fresh_at(&freshness, end - 1000, ttl_ms).fresh_fields);
            CHECK(step(&pause, &freshness, &published, end - 1, 1).withhold_get);
            CHECK(step(&pause, &freshness, &published, end, 1).resume_once);
            CHECK(!step(&pause, &freshness, &published, end + 1, 1).withhold_get);
        }
    }
}

int main(void)
{
    test_default_and_config();
    test_bootstrap_delay_and_once();
    test_ttl_and_retained_values();
    test_generation_and_channel();
    test_clock_ttl_and_windows();
    test_overflow();
    test_real_codec_gate_and_late_reply();
    test_schedule_grid();
    printf("PASS fuxi-battery-pause: %u assertions, production freshness + codec\n", checks);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description="Unwired poll-withholding host checks; no device I/O.")
    parser.add_argument("--sanitize", action="store_true")
    arguments = parser.parse_args()
    host_tools = runpy.run_path(str(ROOT / "tools" / "test-fuxi-audio-prep.py"))
    compiler, environment = host_tools["compiler_environment"]()
    msvc = Path(compiler[0].strip('"')).name.lower() in ("cl", "cl.exe")
    sources = [PREP / "fuxi_battery_freshness.c", ADSP / "ShengBattmgr.c"]
    evidence = sources + [PREP / "fuxi_battery_poll_pause.h", PREP / "fuxi_battery_freshness.h",
        ADSP / "fuxi_adsp_battery.h", ADSP / "ShengBattmgr.h", ADSP / "fuxi_adsp_battery.c"]
    digests = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence}
    with tempfile.TemporaryDirectory(prefix="fuxi-battery-pause-") as directory:
        temporary = Path(directory)
        harness = temporary / "test_pause.c"
        harness.write_text(HARNESS, encoding="utf-8", newline="\n")
        executable = temporary / ("pause-test.exe" if os.name == "nt" else "pause-test")
        if msvc:
            flags = ["/nologo", "/TC", "/std:c11", "/W4", "/WX", "/Od", "/Zi", "/MD"]
            if arguments.sanitize:
                flags += ["/fsanitize=address"]
            command = compiler + flags + [f"/I{PREP}", f"/I{ADSP}"] + [
                str(source) for source in sources + [harness]] + [f"/Fe:{executable}"]
        else:
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
            if arguments.sanitize:
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            command = compiler + flags + ["-I", str(PREP), "-I", str(ADSP)] + [
                str(source) for source in sources + [harness]] + ["-o", str(executable)]
        subprocess.run(command, cwd=directory, env=environment, check=True, timeout=120)
        result = subprocess.run([str(executable)], cwd=directory, env=environment,
            capture_output=True, text=True, check=True, timeout=60)
        if not result.stdout.startswith("PASS fuxi-battery-pause:"):
            raise SystemExit(result.stdout + result.stderr)
        print(result.stdout.strip())
        print(f"compiler={Path(compiler[0]).name}, sanitize={arguments.sanitize}")
    for path, digest in digests.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"Source changed during host checks: {path}")
        print(f"sha256 {path.relative_to(ROOT).as_posix()} {digest}")


if __name__ == "__main__":
    main()
