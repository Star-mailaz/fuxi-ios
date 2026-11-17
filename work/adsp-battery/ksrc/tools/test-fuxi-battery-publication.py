import argparse
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "xnu/fuxi-adsp"
PREP = ROOT / "xnu/fuxi-battery-prep"
sys.dont_write_bytecode = True

HOST_HEADER = r'''
#ifndef BATTERY_HOST_H
#define BATTERY_HOST_H
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "ShengAdsp.h"
#if defined(_MSC_VER)
#include <intrin.h>
#define __ATOMIC_RELEASE 0
#define __ATOMIC_ACQUIRE 0
#define __ATOMIC_ACQ_REL 0
#define __atomic_store_n(target, value, order) ((void)_InterlockedExchange((volatile long *)(target), (long)(value)))
#define __atomic_load_n(target, order) ((uint32_t)_InterlockedCompareExchange((volatile long *)(target), 0, 0))
#define __atomic_exchange_n(target, value, order) ((uint32_t)_InterlockedExchange((volatile long *)(target), (long)(value)))
#endif
#define NSEC_PER_MSEC 1000000u
#define LCK_GRP_DECLARE(name, label) int name
#define LCK_MTX_DECLARE(name, group) int name
#define bzero(target, length) memset(target, 0, length)
#define THREAD_CALL_PRIORITY_KERNEL 0
#define THREAD_CALL_OPTIONS_ONCE 0
typedef void *thread_call_param_t;
typedef struct { unsigned pending; uint64_t deadline; } thread_call_data_t;
void lck_mtx_lock(int *lock);
void lck_mtx_unlock(int *lock);
uint64_t mach_absolute_time(void);
void absolutetime_to_nanoseconds(uint64_t ticks, uint64_t *ns);
void clock_interval_to_deadline(uint32_t ms, uint32_t unit, uint64_t *deadline);
int thread_call_enter(thread_call_data_t *call);
int thread_call_enter_delayed(thread_call_data_t *call, uint64_t deadline);
void thread_call_setup_with_options(thread_call_data_t *call,
    void (*callback)(thread_call_param_t, thread_call_param_t), void *context, int priority, int options);
int PE_parse_boot_argn(const char *name, void *value, int size);
#endif
'''

HARNESS = r'''
#include "battery_host.h"
#include "fuxi_battery_freshness.h"
static unsigned checks;
static uint64_t host_now_ms;
static int host_send_refused;
static uint8_t host_request[SHENG_ADSP_MAX_MESSAGE];
static uint32_t host_request_length;
static uint32_t host_ttl;
static uint64_t host_pause_ms, host_pause_delay_ms;
static unsigned host_gets, host_sets, host_pause_starts, host_pause_ends, host_pause_cancels;
static char host_pause_log[512];
#define HOST_TICK_NS 250u
volatile uint32_t fuxi_tour_battery_test;
#define CHECK(condition) do { checks++; if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); exit(1); } } while (0)
struct ShengAdspChannel { int registered; };
static struct ShengAdspChannel host_channel;
void lck_mtx_lock(int *lock) { CHECK(*lock == 0); *lock = 1; }
void lck_mtx_unlock(int *lock) { CHECK(*lock == 1); *lock = 0; }
uint64_t mach_absolute_time(void) { return host_now_ms * (NSEC_PER_MSEC / HOST_TICK_NS); }
void absolutetime_to_nanoseconds(uint64_t ticks, uint64_t *ns) { *ns = ticks * HOST_TICK_NS; }
void clock_interval_to_deadline(uint32_t ms, uint32_t unit, uint64_t *deadline)
{ *deadline = mach_absolute_time() + (uint64_t)ms * unit / HOST_TICK_NS; }
int thread_call_enter(thread_call_data_t *call) { call->pending++; return 1; }
int thread_call_enter_delayed(thread_call_data_t *call, uint64_t deadline)
{ call->deadline = deadline; return 1; }
void thread_call_setup_with_options(thread_call_data_t *call,
    void (*callback)(thread_call_param_t, thread_call_param_t), void *context, int priority, int options)
{ (void)callback; (void)context; (void)priority; (void)options; memset(call, 0, sizeof(*call)); }
int PE_parse_boot_argn(const char *name, void *value, int size)
{
    if (host_ttl && !strcmp(name, "fuxibatttl") && size == sizeof(host_ttl)) {
        memcpy(value, &host_ttl, sizeof(host_ttl)); return 1;
    }
    if (size == sizeof(host_pause_ms)) {
        if (!strcmp(name, "fuxibatpause")) {
            memcpy(value, &host_pause_ms, sizeof(host_pause_ms)); return 1;
        }
        if (!strcmp(name, "fuxibatpausedelay")) {
            memcpy(value, &host_pause_delay_ms, sizeof(host_pause_delay_ms)); return 1;
        }
    }
    return 0;
}
unsigned fuxi_adsp_mode(void) { return 3; }
unsigned fuxi_adsp_battery_test_mode(void) { return 0; }
ShengAdspChannel *sheng_adsp_channel(const char *name, uint32_t size, uint32_t count,
    int initiator, const ShengAdspClient *client, void *context)
{
    (void)name; (void)size; (void)count; (void)initiator; (void)client; (void)context;
    host_channel.registered = 1; return &host_channel;
}
int sheng_adsp_send(ShengAdspChannel *channel, const void *data, uint32_t length)
{
    CHECK(channel == &host_channel && length <= sizeof(host_request));
    memcpy(host_request, data, length); host_request_length = length;
    const uint8_t *bytes = data;
    const uint32_t opcode = (uint32_t)bytes[8] | (uint32_t)bytes[9] << 8 |
        (uint32_t)bytes[10] << 16 | (uint32_t)bytes[11] << 24;
    if (opcode == SHENG_BATTMGR_OP_BATTERY_GET || opcode == SHENG_BATTMGR_OP_USB_GET ||
        opcode == SHENG_BATTMGR_OP_BOARD_GET) host_gets++;
    if (opcode == SHENG_BATTMGR_OP_USB_SET || opcode == SHENG_BATTMGR_OP_BOARD_SET) host_sets++;
    return host_send_refused;
}
static int host_printf(const char *format, ...)
{
    char text[1024];
    va_list arguments;
    va_start(arguments, format);
    const int count = vsnprintf(text, sizeof(text), format, arguments);
    va_end(arguments);
    CHECK(count >= 0 && (unsigned)count < sizeof(text));
    if (strstr(text, "FUXI BATTERY: poll-pause ")) {
        if (strstr(text, "poll-pause start ")) host_pause_starts++;
        if (strstr(text, "poll-pause end ")) host_pause_ends++;
        if (strstr(text, "poll-pause cancel ")) host_pause_cancels++;
        CHECK((unsigned)count < sizeof(host_pause_log));
        memcpy(host_pause_log, text, (unsigned)count + 1);
    }
    return count;
}
#define printf host_printf
#include "@PRODUCER@"
#undef printf

void host_consumer_reset(void);
void host_consumer_check(const FuxiAdspBattery *incoming);
void host_consumer_assert(int condition, const char *name)
{
    checks++;
    if (!condition) { fprintf(stderr, "FAIL consumer: %s\n", name); exit(1); }
}

static uint32_t get_word(const uint8_t *data)
{ return (uint32_t)data[0] | ((uint32_t)data[1] << 8) | ((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24); }
static void set_word(uint8_t *data, uint32_t value)
{
    data[0] = (uint8_t)value; data[1] = (uint8_t)(value >> 8);
    data[2] = (uint8_t)(value >> 16); data[3] = (uint8_t)(value >> 24);
}
static void reset_source(void)
{
    host_now_ms = 0; host_send_refused = 0; host_ttl = 0;
    host_pause_ms = host_pause_delay_ms = 0;
    host_gets = host_sets = host_pause_starts = host_pause_ends = host_pause_cancels = 0;
    memset(host_pause_log, 0, sizeof(host_pause_log));
    host_consumer_reset();
    fb_head = fb_count = fb_dropped = 0;
    fb_up = fb_changed = fb_lost = 0;
    fb_was_up = 0; fb_request_due = fb_refresh_due = 0;
    fb_worker_generation = fb_request_generation = 0;
    fb_max_age_ms = FUXI_BATTERY_DEFAULT_MAX_AGE_MS;
    fuxi_adsp_battery_start(1);
}
static FuxiAdspBattery reading(void)
{
    FuxiAdspBattery value;
    CHECK(fuxi_adsp_battery_reading(&value) == 1);
    return value;
}
static void start_channel(void) { fbState(NULL, 1); fbRun(NULL, NULL); }
static void begin_field(unsigned field)
{
    fb_bm.cursor = (uint8_t)field; fb_bm.in_flight = 0;
    fb_bm.keyboard_in_flight = -1; fb_bm.limit_in_flight = fb_bm.limit_due = 0;
    fb_request_due = 0; fbPump();
    CHECK(fb_bm.in_flight && host_request_length == 24);
}
static void make_answer(uint8_t answer[24], int32_t value, uint32_t result)
{
    set_word(answer, SHENG_BATTMGR_OWNER);
    set_word(answer + 4, SHENG_BATTMGR_TYPE_REQUEST);
    set_word(answer + 8, get_word(host_request + 8));
    set_word(answer + 12, get_word(host_request + 16));
    set_word(answer + 16, (uint32_t)value); set_word(answer + 20, result);
}
static void answer_field(unsigned field, int32_t value, uint32_t result)
{
    uint8_t answer[24]; begin_field(field); make_answer(answer, value, result);
    fbReceive(NULL, answer, sizeof(answer)); fbRun(NULL, NULL);
}
static void timeout_field(unsigned field)
{
    begin_field(field); host_now_ms += FB_REQUEST_MS;
    fbRun(NULL, NULL);
}
static void seed_connected(void)
{
    start_channel();
    answer_field(BmStatus, 1, 0); answer_field(BmCapacity, 9700, 0);
    answer_field(BmVoltage, 4300000, 0); answer_field(BmCurrent, -100000, 0);
    answer_field(BmUsbOnline, 1, 0);
}
static void test_bootstrap_and_flow_expiry(void)
{
    reset_source(); FuxiAdspBattery value = reading();
    CHECK(value.sequence == 0 && value.stale && !value.soc_known && !value.external_known);
    seed_connected(); value = reading();
    CHECK(value.percent == 97 && value.external && value.charging && !value.stale);
    CHECK(value.current_valid && value.voltage_valid);
    for (unsigned cycle = 0; cycle < 24; cycle++) {
        timeout_field(BmStatus); timeout_field(BmUsbOnline);
        answer_field(BmCapacity, 9600, 0);
    }
    value = reading();
    CHECK(value.soc_known && value.percent == 96 && value.stale);
    CHECK(!value.external_known && !value.status_known && value.external && value.charging);
    CHECK(!value.current_valid && !value.voltage_valid);
    host_now_ms += fb_max_age_ms;
    value = reading(); CHECK(!value.soc_known && value.percent == 96 && value.stale);
    answer_field(BmUsbOnline, 0, 0); value = reading();
    CHECK(value.external_known && !value.external && value.status_known && !value.charging && !value.fully_charged);
    CHECK(!value.soc_known && value.percent == 96);
    answer_field(BmCapacity, 9300, 0); value = reading();
    CHECK(value.soc_known && value.percent == 93 && !value.stale);
}
static void test_bad_soc_and_partial_unplug(void)
{
    reset_source(); seed_connected();
    host_now_ms += fb_max_age_ms;
    answer_field(BmCapacity, 10001, 0);
    answer_field(BmVoltage, 1000000, 0);
    FuxiAdspBattery value = reading();
    CHECK(value.percent == 97 && !value.soc_known && !value.voltage_valid);
    answer_field(BmUsbOnline, 0, 0); value = reading();
    CHECK(value.external_known && !value.external && !value.charging && value.status_known);
    CHECK(value.adapter_family == 0 && value.adapter_mv == 0 && value.adapter_ma == 0 && value.adapter_watts == 0);
    CHECK(!value.soc_known && value.percent == 97 && value.stale);
    const uint64_t before = fb_fresh.successful_at_ms[BmCapacity];
    answer_field(BmCapacity, 9500, 7);
    CHECK(fb_fresh.successful_at_ms[BmCapacity] == before);
    value = reading(); CHECK(!value.soc_known && value.percent == 97);
}
static void test_loss_ring_and_recovery(void)
{
    reset_source(); seed_connected();
    const uint64_t old_generation = fb_fresh.generation;
    uint8_t answer[24]; begin_field(BmUsbOnline); make_answer(answer, 0, 0);
    fbReceive(NULL, answer, sizeof(answer)); CHECK(fb_count == 1);
    fbState(NULL, 0); CHECK(fb_count == 0);
    FuxiAdspBattery value = reading();
    CHECK(!value.channel_up && value.stale && !value.external_known && value.external);
    fbState(NULL, 1); value = reading();
    CHECK(value.channel_up && !value.soc_known && !value.external_known && value.percent == 97);
    fbRun(NULL, NULL); begin_field(BmUsbOnline);
    fbReceive(NULL, answer, sizeof(answer));
    fb_ring[fb_head].generation = old_generation;
    fbRun(NULL, NULL); value = reading(); CHECK(!value.external_known && value.external);
    answer_field(BmUsbOnline, 0, 0); value = reading(); CHECK(value.external_known && !value.external);
    answer_field(BmCapacity, 9200, 0); value = reading(); CHECK(value.percent == 92 && !value.stale);
}
static void test_accepted_get_only_and_ingress_age(void)
{
    reset_source(); start_channel();
    uint8_t answer[24]; begin_field(BmCapacity); make_answer(answer, 9000, 0);
    set_word(answer + 12, 7);
    fbReceive(NULL, answer, sizeof(answer)); fbRun(NULL, NULL);
    CHECK(!(fb_fresh.observed_fields & (1u << BmCapacity)));
    uint8_t notification[12]; set_word(notification, SHENG_BATTMGR_OWNER);
    set_word(notification + 4, SHENG_BATTMGR_TYPE_NOTIFY);
    set_word(notification + 8, SHENG_BATTMGR_OP_NOTIFICATION);
    fbReceive(NULL, notification, sizeof(notification)); fbRun(NULL, NULL);
    CHECK(fb_fresh.observed_fields == 0);
    host_send_refused = 1; answer_field(BmCapacity, 9100, 0);
    CHECK(!(fb_fresh.observed_fields & (1u << BmCapacity)));
    host_send_refused = 0; begin_field(BmCapacity); make_answer(answer, 9100, 0);
    fbReceive(NULL, answer, sizeof(answer)); host_now_ms = fb_max_age_ms;
    fbRun(NULL, NULL); FuxiAdspBattery value = reading();
    CHECK(!value.soc_known && fb_fresh.successful_at_ms[BmCapacity] == 0);
    answer_field(BmCapacity, 9100, 0); value = reading(); CHECK(value.soc_known && value.percent == 91);
    const uint64_t before = fb_fresh.successful_at_ms[BmCapacity];
    host_now_ms++;
    fbReceive(NULL, notification, sizeof(notification)); fbRun(NULL, NULL);
    CHECK(fb_fresh.successful_at_ms[BmCapacity] == before);
}
static void test_configured_ttl_and_failed_refresh(void)
{
    reset_source(); host_ttl = 5000;
    fuxi_adsp_battery_start(1); seed_connected();
    CHECK(fb_max_age_ms == 5000);
    host_now_ms = 4999;
    FuxiAdspBattery value = reading(); CHECK(!value.stale && value.external_known);
    host_now_ms = 5000;
    value = reading(); CHECK(value.stale && !value.external_known && value.external);
    answer_field(BmCapacity, 9600, 0);
    const uint64_t before = fb_fresh.successful_at_ms[BmCapacity];
    host_now_ms++;
    answer_field(BmCapacity, 10001, 0);
    value = reading(); CHECK(value.soc_known && value.percent == 96);
    CHECK(fb_fresh.successful_at_ms[BmCapacity] == before);
    answer_field(BmUsbOnline, 1, 9);
    value = reading(); CHECK(!value.external_known && value.external && value.stale);
    CHECK(fb_fresh.successful_at_ms[BmUsbOnline] == 0);
    host_now_ms = before + fb_max_age_ms;
    value = reading(); CHECK(!value.soc_known && value.percent == 96);
}

static void configure_pause(uint64_t duration_ms, uint64_t delay_ms)
{
    reset_source();
    host_pause_ms = duration_ms;
    host_pause_delay_ms = delay_ms;
    fuxi_adsp_battery_start(1);
    CHECK(fb_max_age_ms == FUXI_BATTERY_DEFAULT_MAX_AGE_MS);
}

static void seed_pause_connected(void)
{
    start_channel();
    CHECK(fb_pause.phase == FuxiBatteryPollPauseWaiting || fb_pause.phase == FuxiBatteryPollPauseOff ||
        fb_pause.phase == FuxiBatteryPollPauseCancelled);
    answer_field(BmStatus, 1, 0); answer_field(BmCapacity, 9700, 0);
    answer_field(BmVoltage, 4300000, 0); answer_field(BmCurrent, -100000, 0);
    answer_field(BmUsbAdapter, 6, 0); answer_field(BmUsbVoltage, 9000000, 0);
    answer_field(BmUsbCurrent, 1200000, 0); answer_field(BmUsbOnline, 1, 0);
}

static void reply_pending_get(void)
{
    CHECK(fb_bm.in_flight && fb_request_due && host_request_length == 24);
    int32_t value = 0;
    uint32_t result = 0;
    switch (fb_bm.cursor) {
    case BmStatus: value = 1; break;
    case BmCapacity: value = 9700; break;
    case BmVoltage: value = 4300000; break;
    case BmCurrent: value = -100000; break;
    case BmUsbOnline: value = 1; break;
    case BmUsbType:
    case BmUsbAdapter: value = 6; break;
    case BmUsbVoltage: value = 9000000; break;
    case BmUsbCurrent: value = 1200000; break;
    default: result = 1; break;
    }
    uint8_t answer[24]; make_answer(answer, value, result);
    fbReceive(NULL, answer, sizeof(answer)); fbRun(NULL, NULL);
}

static void test_native_pause_ttl_aliases_and_recovery(void)
{
    configure_pause(130000, 0); seed_pause_connected();
    CHECK(fb_pause.phase == FuxiBatteryPollPauseHolding && host_pause_starts == 1);
    CHECK(host_pause_ends == 0 && host_pause_cancels == 0 && !fb_request_due && !fb_bm.in_flight);
    CHECK(fb_pause.generation == fb_fresh.generation && fb_pause.max_age_ms == 90000);
    CHECK(strstr(host_pause_log, "ttl_ms=90000 duration_ms=130000") && strstr(host_pause_log, "channel_up=1 now_ms=0"));
    CHECK(strstr(host_pause_log, "soc_age_ms=0 external_age_ms=0 status_age_ms=0") != NULL);
    FuxiAdspBattery value = reading(); host_consumer_check(&value);
    CHECK(value.soc_known && value.external_known && value.status_known);
    FuxiBatteryFreshness before;
    int32_t values_before[BmFields], codec_values_before[BmFields];
    FuxiAdspBattery pub_before;
    memcpy(&before, &fb_fresh, sizeof before);
    memcpy(values_before, fb_values, sizeof values_before);
    memcpy(codec_values_before, fb_bm.value, sizeof codec_values_before);
    memcpy(&pub_before, &fb_pub, sizeof pub_before);
    const uint32_t valid_before = fb_bm.valid;
    const unsigned gets = host_gets;
    for (host_now_ms = 1000; host_now_ms < 90000; host_now_ms += 1000) {
        fbRun(NULL, NULL);
        CHECK(host_gets == gets && host_sets == 0);
        CHECK(!fb_request_due && !fb_bm.in_flight);
        CHECK(memcmp(&before, &fb_fresh, sizeof before) == 0);
        CHECK(memcmp(values_before, fb_values, sizeof values_before) == 0);
        CHECK(memcmp(codec_values_before, fb_bm.value, sizeof codec_values_before) == 0);
        CHECK(memcmp(&pub_before, &fb_pub, sizeof pub_before) == 0);
        CHECK(fb_bm.valid == valid_before && host_pause_starts == 1 && host_pause_ends == 0);
    }
    host_now_ms = 89999;
    value = reading(); host_consumer_check(&value);
    CHECK(!value.stale && value.external_known && value.status_known && value.soc_known);
    host_now_ms = 90000;
    value = reading(); host_consumer_check(&value);
    CHECK(value.stale && !value.external_known && !value.status_known && !value.soc_known);
    CHECK(!value.current_valid && !value.voltage_valid && !value.fresh_fields);
    CHECK(value.external && value.charging && value.percent == 97 && value.adapter_family != 0);
    CHECK(value.soc_age_ms == 90000 && value.external_age_ms == 90000 && value.status_age_ms == 90000);
    for (host_now_ms = 90000; host_now_ms <= 120000; host_now_ms += 1000) {
        fbRun(NULL, NULL);
        CHECK(host_gets == gets && host_sets == 0 && !fb_request_due && !fb_bm.in_flight);
        CHECK(memcmp(&before, &fb_fresh, sizeof before) == 0 && fb_bm.valid == valid_before);
        CHECK(memcmp(values_before, fb_values, sizeof values_before) == 0);
        CHECK(memcmp(codec_values_before, fb_bm.value, sizeof codec_values_before) == 0);
    }
    host_now_ms = 120000;
    value = reading(); host_consumer_check(&value);
    CHECK(value.stale && !value.external_known && value.external);
    host_now_ms = 125000;
    fbRun(NULL, NULL);
    CHECK(fb_call.deadline == fbDeadline(5000));
    CHECK(fb_call.deadline != fb_pause.resume_at_ms);
    host_now_ms = 129999; fbRun(NULL, NULL);
    CHECK(host_gets == gets && fb_call.deadline == fbDeadline(1));
    host_now_ms = 130000;
    fbRun(NULL, NULL);
    CHECK(fb_pause.phase == FuxiBatteryPollPauseDone && host_pause_ends == 1);
    CHECK(host_gets == gets + 1 && host_pause_starts == 1 && host_pause_cancels == 0);
    CHECK(strstr(host_pause_log, "poll-pause end ") && strstr(host_pause_log, "external_age_ms=130000"));
    unsigned responses = 0;
    value = reading();
    while (value.stale && responses++ < 64) {
        reply_pending_get(); value = reading();
    }
    CHECK(!value.stale && value.soc_known && value.external_known && value.status_known);
    host_consumer_check(&value);
    CHECK(host_pause_starts == 1 && host_pause_ends == 1);
}

static void test_native_pause_late_reply_and_sets(void)
{
    configure_pause(130000, 1000); seed_pause_connected();
    CHECK(fb_pause.phase == FuxiBatteryPollPauseArmed && fb_bm.in_flight);
    CHECK(fb_call.deadline == fbDeadline(1000));
    const unsigned field = fb_bm.cursor;
    const unsigned gets = host_gets;
    host_now_ms = 1000;
    uint8_t answer[24]; make_answer(answer, 6, 0);
    fbReceive(NULL, answer, sizeof(answer));
    host_now_ms = 5000; fbRun(NULL, NULL);
    CHECK(fb_fresh.successful_at_ms[field] == 1000 && (fb_fresh.observed_fields & (1u << field)));
    CHECK(fb_values[field] == 6 && fb_pause.phase == FuxiBatteryPollPauseHolding);
    CHECK(fb_pause.resume_at_ms == 135000 && host_gets == gets && host_pause_starts == 1);
    FuxiBatteryFreshness before;
    memcpy(&before, &fb_fresh, sizeof before);
    host_now_ms = 6000;
    fbReceive(NULL, answer, sizeof(answer)); fbRun(NULL, NULL);
    CHECK(memcmp(&before, &fb_fresh, sizeof before) == 0 && host_gets == gets);
    fb_bm.limit_due = 900000;
    fbRun(NULL, NULL);
    CHECK(host_sets == 1 && host_gets == gets && fb_bm.limit_in_flight == 900000);
    make_answer(answer, 0, 0); fbReceive(NULL, answer, sizeof(answer)); fbRun(NULL, NULL);
    CHECK(!fb_bm.limit_in_flight && host_gets == gets);
    CHECK(memcmp(&before, &fb_fresh, sizeof before) == 0);
    sheng_battmgr_keyboard(&fb_bm, 1); fbRun(NULL, NULL);
    CHECK(host_sets == 2 && host_gets == gets && fb_bm.keyboard_in_flight == 1);
    make_answer(answer, 0, 0); fbReceive(NULL, answer, sizeof(answer)); fbRun(NULL, NULL);
    CHECK(fb_bm.keyboard_in_flight < 0 && host_gets == gets);
    CHECK(memcmp(&before, &fb_fresh, sizeof before) == 0);
    uint8_t notification[12]; set_word(notification, SHENG_BATTMGR_OWNER);
    set_word(notification + 4, SHENG_BATTMGR_TYPE_NOTIFY);
    set_word(notification + 8, SHENG_BATTMGR_OP_NOTIFICATION);
    fbReceive(NULL, notification, sizeof(notification)); fbRun(NULL, NULL);
    CHECK(memcmp(&before, &fb_fresh, sizeof before) == 0 && host_gets == gets);
    CHECK(host_pause_starts == 1 && !host_pause_ends && !host_pause_cancels);
}

static void test_native_pause_cancellation(void)
{
    for (unsigned mode = 0; mode < 4; mode++) {
        configure_pause(130000, mode == 3 ? 1000 : 0); seed_pause_connected();
        const uint64_t generation = fb_fresh.generation;
        const unsigned gets = host_gets;
        host_now_ms = 100;
        fbState(NULL, 0);
        if (mode != 0) fbState(NULL, 1);
        fbRun(NULL, NULL);
        CHECK(fb_pause.phase == FuxiBatteryPollPauseCancelled && host_pause_cancels == 1);
        CHECK(!host_pause_ends && host_pause_starts == (mode == 3 ? 0u : 1u));
        CHECK(fb_pause.generation == generation && !fb_fresh.observed_fields);
        CHECK(host_gets == gets + (mode == 0 ? 0u : 1u));
        CHECK(fb_pause.reason == (mode == 0 ? FuxiBatteryPollPauseChannel : FuxiBatteryPollPauseGeneration));
        FuxiAdspBattery value = reading(); host_consumer_check(&value);
        CHECK(value.stale && !value.external_known && value.external);
        host_now_ms = 101; fbRun(NULL, NULL);
        CHECK(host_pause_cancels == 1);
    }
    configure_pause(130000, 0); seed_pause_connected();
    host_now_ms = 1000; fbRun(NULL, NULL);
    const unsigned gets = host_gets;
    host_now_ms = 999; fbRun(NULL, NULL);
    CHECK(fb_pause.reason == FuxiBatteryPollPauseClock && host_pause_cancels == 1);
    CHECK(host_gets == gets + 1 && !host_pause_ends);
    host_now_ms = 1001; fbRun(NULL, NULL); CHECK(host_pause_cancels == 1);
    configure_pause(130000, 0); seed_pause_connected();
    fb_max_age_ms = 91000; host_now_ms = 1; fbRun(NULL, NULL);
    CHECK(fb_pause.reason == FuxiBatteryPollPauseTtl && host_pause_cancels == 1);
}

static void test_native_pause_configuration_and_default(void)
{
    configure_pause(0, UINT64_MAX); seed_pause_connected();
    CHECK(fb_pause.phase == FuxiBatteryPollPauseOff && !fb_pause.clock_seen);
    const unsigned gets = host_gets;
    reply_pending_get();
    CHECK(host_gets == gets + 1 && !host_pause_starts && !host_pause_ends && !host_pause_cancels);
    const uint64_t invalid[] = {1, 999, 300001, UINT64_MAX};
    for (unsigned index = 0; index < sizeof(invalid) / sizeof(invalid[0]); index++) {
        configure_pause(invalid[index], 0); seed_pause_connected();
        CHECK(fb_pause.phase == FuxiBatteryPollPauseCancelled && fb_pause.reason == FuxiBatteryPollPauseConfig);
        CHECK(!host_pause_starts && host_pause_cancels == 1 && fb_bm.in_flight);
    }
    configure_pause(130000, 60001); seed_pause_connected();
    CHECK(fb_pause.reason == FuxiBatteryPollPauseConfig && host_pause_cancels == 1);
    configure_pause(89999, 0); seed_pause_connected();
    CHECK(fb_pause.reason == FuxiBatteryPollPauseTtl && host_pause_cancels == 1 && fb_max_age_ms == 90000);
    configure_pause(300000, 60000); seed_pause_connected();
    CHECK(fb_pause.phase == FuxiBatteryPollPauseArmed && fb_pause.pause_at_ms == 60000);
    CHECK(fb_call.deadline == fbDeadline(FB_REQUEST_MS));
    configure_pause(130000, 0); host_ttl = 3600000; fuxi_adsp_battery_start(1); seed_pause_connected();
    CHECK(fb_pause.reason == FuxiBatteryPollPauseTtl && fb_max_age_ms == 3600000 && host_pause_cancels == 1);
}
static unsigned change_calls;
void host_consumer_change_tests(void);
static void change_seen(void *arg) { CHECK(arg == &change_calls && fb_pub_lock == 1); change_calls++; }
static void test_change_asks_for_a_sample(void)
{
    reset_source(); change_calls = 0; fb_change_key = 0;
    fuxi_adsp_battery_on_change(change_seen, &change_calls);
    seed_connected();
    CHECK(change_calls >= 1);
    unsigned before = change_calls;
    answer_field(BmVoltage, 4290000, 0); answer_field(BmCurrent, -90000, 0); answer_field(BmUsbOnline, 1, 0);
    CHECK(change_calls == before);
    answer_field(BmUsbOnline, 0, 0);
    CHECK(change_calls == before + 1);
    FuxiAdspBattery value = reading(); CHECK(!value.external && !value.charging);
    answer_field(BmUsbOnline, 0, 0); CHECK(change_calls == before + 1);
    answer_field(BmUsbOnline, 1, 0); CHECK(change_calls == before + 2);
    answer_field(BmCapacity, 9600, 0); CHECK(change_calls == before + 3);
    answer_field(BmCapacity, 9590, 0); CHECK(change_calls == before + 3);
    fuxi_adsp_battery_on_change(NULL, NULL);
    answer_field(BmUsbOnline, 0, 0); CHECK(change_calls == before + 3);
}
int main(void)
{
    host_consumer_change_tests();
    test_bootstrap_and_flow_expiry(); test_bad_soc_and_partial_unplug();
    test_change_asks_for_a_sample();
    test_loss_ring_and_recovery(); test_accepted_get_only_and_ingress_age();
    test_configured_ttl_and_failed_refresh();
    test_native_pause_ttl_aliases_and_recovery(); test_native_pause_late_reply_and_sets();
    test_native_pause_cancellation(); test_native_pause_configuration_and_default();
    printf("PASS fuxi-battery production publication: %u checks\n", checks);
    return 0;
}
'''

CONSUMER_HOST = r'''
#include <stdint.h>
#include <string.h>
#include "fuxi_battery_freshness.h"
extern "C" void host_consumer_assert(int condition, const char *name);
#define REQUIRE(condition) host_consumer_assert((condition) != 0, #condition)
typedef uint32_t UInt32;
struct OSObject {};
struct IOInterruptEventSource {
    unsigned pending = 0;
    bool enabled = true;
    void interruptOccurred(void *context, void *provider, int index) {
        REQUIRE(!context && !provider && !index);
        if (enabled) pending++;
    }
};
#define OSDynamicCast(type, value) static_cast<type *>(value)

struct Properties {
    struct Entry { const char *key; uint64_t value; } entries[80];
    unsigned count = 0;
    void put(const char *key, uint64_t value) {
        for (unsigned index = 0; index < count; index++) {
            if (!strcmp(entries[index].key, key)) { entries[index].value = value; return; }
        }
        REQUIRE(count < 80);
        entries[count++] = {key, value};
    }
    uint64_t get(const char *key) const {
        for (unsigned index = 0; index < count; index++) {
            if (!strcmp(entries[index].key, key)) return entries[index].value;
        }
        REQUIRE(false); return 0;
    }
};
struct OSNumber {
    uint32_t value;
    static OSNumber *withNumber(uint32_t value, unsigned bits) {
        REQUIRE(bits == 32); return new OSNumber{value};
    }
    void release() { delete this; }
};
struct OSSymbol {
    const char *key;
    static const OSSymbol *withCString(const char *key) { return new OSSymbol{key}; }
    void release() const { delete this; }
};
struct OSDictionary {
    Properties values;
    static OSDictionary *withCapacity(unsigned capacity) { (void)capacity; return new OSDictionary; }
    void setObject(const char *key, OSNumber *number) { values.put(key, number->value); }
    void release() { delete this; }
};
#define OSSafeReleaseNULL(object) do { if (object) { object->release(); object = nullptr; } } while (0)
#define HOST_KEY(name) static const char *name = #name
HOST_KEY(kIOPMPSAdapterDetailsFamilyKey);
HOST_KEY(kIOPMPSAdapterDetailsVoltage);
HOST_KEY(kIOPMPSAdapterDetailsAmperageKey);
HOST_KEY(kIOPMPSAdapterDetailsWattsKey);
HOST_KEY(kIOPMPSAdapterDetailsKey);
HOST_KEY(kIOBatteryCurrentChargeKey);
HOST_KEY(kIOBatteryCapacityKey);
HOST_KEY(kIOBatteryVoltageKey);
HOST_KEY(kIOBatteryAmperageKey);
HOST_KEY(kIOBatteryCycleCountKey);
HOST_KEY(kIOBatteryFlagsKey);
enum { kIOBatteryInstalled = 1, kIOBatteryChargerConnect = 2, kIOBatteryCharge = 4 };
static int IOLog(const char *format, ...) { (void)format; return 0; }

class SweetBattery : public OSObject {
public:
    FuxiAdspBattery fAdspLast = {};
    bool fAdspSOCShown = false, fAdspTemperatureShown = false, fAdspShown = false;
    int fLastMode = -1;
    unsigned fShown = 0, fShownLogs = 0, updates = 0;
    IOInterruptEventSource *fNotify = nullptr;
    bool fRunning = false, changeDuringPoll = false;
    unsigned polls = 0;
    Properties properties, adapter_properties, legacy_properties;
    SweetBattery() {
        fAdspLast.percent = 100; fAdspLast.voltage_mv = 4200;
        fAdspLast.present = fAdspLast.external = fAdspLast.fully_charged = 1;
        fAdspLast.temperature = 2500;
    }
    void publishAdsp(const FuxiAdspBattery &incoming);
    static void adspChanged(void *owner);
    static void adspChangedFired(OSObject *, IOInterruptEventSource *, int);
    void poll() {
        polls++;
        if (changeDuringPoll) { changeDuringPoll = false; adspChanged(this); }
    }
    void putBool(const char *key, bool value) { properties.put(key, value); }
    void putNumber(const char *key, uint32_t value) { properties.put(key, value); }
    void setBatteryInstalled(bool value) { properties.put("primary_present", value); }
    void setCurrentCapacity(unsigned value) { properties.put("primary_capacity", value); }
    void setMaxCapacity(unsigned value) { properties.put("primary_full", value); }
    void setExternalConnected(bool value) { properties.put("primary_external", value); }
    void setExternalChargeCapable(bool value) { properties.put("primary_capable", value); }
    void setIsCharging(bool value) { properties.put("primary_charging", value); }
    void setAtWarnLevel(bool value) { (void)value; }
    void setAtCriticalLevel(bool value) { (void)value; }
    void setVoltage(unsigned value) { properties.put("primary_voltage", value); }
    void setAmperage(int value) { properties.put("primary_current", (uint32_t)value); }
    void setTimeRemaining(int value) { properties.put("primary_time", (uint32_t)value); }
    void setCycleCount(unsigned value) { properties.put("primary_cycles", value); }
    void setPSProperty(const OSSymbol *key, OSDictionary *values) {
        REQUIRE(!strcmp(key->key, kIOPMPSAdapterDetailsKey)); adapter_properties = values->values;
    }
    void setLegacyIOBatteryInfo(OSDictionary *values) { legacy_properties = values->values; }
    void updateStatus() { updates++; }
};

@PUBLISH_ADSP@
@CHANGE_CALLBACKS@

extern "C" void host_consumer_change_tests(void)
{
    SweetBattery changed;
    IOInterruptEventSource event;
    changed.fNotify = &event;
    changed.fRunning = true;
    SweetBattery::adspChanged(nullptr);
    for (unsigned index = 0; index < 100; index++) SweetBattery::adspChanged(&changed);
    REQUIRE(event.pending == 100 && changed.polls == 0);
    event.pending = 0;
    changed.changeDuringPoll = true;
    SweetBattery::adspChangedFired(&changed, &event, 100);
    REQUIRE(changed.polls == 1 && event.pending == 1);
    SweetBattery::adspChangedFired(&changed, &event, 1);
    REQUIRE(changed.polls == 2);
    changed.fRunning = false;
    SweetBattery::adspChangedFired(&changed, &event, 1);
    REQUIRE(changed.polls == 2);
    changed.fNotify = nullptr;
    SweetBattery::adspChanged(&changed);
    REQUIRE(event.pending == 1);
}

static SweetBattery consumer;
extern "C" void host_consumer_reset(void) { consumer = SweetBattery(); }
extern "C" void host_consumer_check(const FuxiAdspBattery *incoming)
{
    const FuxiAdspBattery before = consumer.fAdspLast;
    consumer.publishAdsp(*incoming);
    const FuxiAdspBattery &shown = consumer.fAdspLast;
    REQUIRE(consumer.updates != 0);
    REQUIRE(shown.percent == (incoming->soc_known ? incoming->percent : before.percent));
    REQUIRE(consumer.properties.get("FuxiBatterySourceStale") == incoming->stale);
    REQUIRE(consumer.properties.get("FuxiBatteryExternalKnown") == incoming->external_known);
    REQUIRE(consumer.properties.get("FuxiBatteryStatusKnown") == incoming->status_known);
    REQUIRE(consumer.properties.get("FuxiBatterySOCValid") == incoming->soc_known);
    REQUIRE(consumer.properties.get("FuxiBatteryVoltageValid") == incoming->voltage_valid);
    REQUIRE(consumer.properties.get("SweetBatteryCurrentValid") == incoming->current_valid);
    REQUIRE(consumer.properties.get("SweetBatteryHardwareSampleValid") ==
        (incoming->soc_known && incoming->voltage_valid));
    REQUIRE(consumer.properties.get("FuxiBatteryFreshFields") == incoming->fresh_fields);
    REQUIRE(consumer.properties.get("FuxiBatteryMaxAgeMs") == incoming->max_age_ms);
    REQUIRE(consumer.properties.get("FuxiBatterySOCAgeMs") == incoming->soc_age_ms);
    REQUIRE(consumer.properties.get("FuxiBatteryExternalAgeMs") == incoming->external_age_ms);
    REQUIRE(consumer.properties.get("FuxiBatteryStatusAgeMs") == incoming->status_age_ms);
    REQUIRE(consumer.properties.get("FuxiBatteryChannelUp") == incoming->channel_up);
    REQUIRE(consumer.properties.get("primary_external") == shown.external);
    REQUIRE(consumer.properties.get("primary_external") == consumer.properties.get("AppleRawExternalConnected"));
    REQUIRE(consumer.properties.get("primary_capable") == shown.external);
    REQUIRE(consumer.properties.get("primary_charging") == shown.charging);
    REQUIRE(consumer.properties.get("FullyCharged") == shown.fully_charged);
    REQUIRE(consumer.properties.get("primary_capacity") == consumer.legacy_properties.get(kIOBatteryCurrentChargeKey));
    REQUIRE(consumer.properties.get("primary_full") == consumer.legacy_properties.get(kIOBatteryCapacityKey));
    REQUIRE(consumer.properties.get("primary_voltage") == consumer.legacy_properties.get(kIOBatteryVoltageKey));
    REQUIRE(consumer.properties.get("primary_current") == consumer.legacy_properties.get(kIOBatteryAmperageKey));
    const uint64_t flags = consumer.legacy_properties.get(kIOBatteryFlagsKey);
    REQUIRE(((flags & kIOBatteryChargerConnect) != 0) == (shown.external != 0));
    REQUIRE(((flags & kIOBatteryCharge) != 0) == (shown.charging != 0));
    REQUIRE(consumer.adapter_properties.get(kIOPMPSAdapterDetailsFamilyKey) == (shown.external ? shown.adapter_family : 0));
    REQUIRE(consumer.adapter_properties.get(kIOPMPSAdapterDetailsVoltage) ==
        (shown.external && shown.adapter_mv > 0 ? (UInt32)shown.adapter_mv : 0));
    REQUIRE(consumer.adapter_properties.get(kIOPMPSAdapterDetailsAmperageKey) ==
        (shown.external && shown.adapter_ma > 0 ? (UInt32)shown.adapter_ma : 0));
    REQUIRE(consumer.adapter_properties.get(kIOPMPSAdapterDetailsWattsKey) ==
        (shown.external && shown.adapter_watts > 0 ? (UInt32)shown.adapter_watts : 0));
    const uint32_t fields = (1u << BmUsbAdapter) | (1u << BmUsbVoltage) | (1u << BmUsbCurrent);
    REQUIRE(consumer.properties.get("FuxiBatteryAdapterValid") ==
        (incoming->external_known && (!shown.external || (incoming->fresh_fields & fields) == fields)));
    if (!incoming->external_known) REQUIRE(shown.external == before.external);
    if (!incoming->status_known) REQUIRE(shown.charging == before.charging);
}
'''


def check_consumer_wiring():
    text = (SOURCE / "SweetBattery.cpp").read_text(encoding="utf-8")
    publish = text.split("SweetBattery::publishAdsp(", 1)[1].split("\n#endif", 1)[0]
    poll = text.split("SweetBattery::poll(void)", 1)[1].split("SweetBattery::timerFired", 1)[0]
    start = text.split("SweetBattery::start(IOService *provider)", 1)[1].split("SweetBattery::stop", 1)[0]
    expected = [
        (publish, "fuxi_battery_prep_merge(&fAdspLast, &incoming);"),
        (publish, "const FuxiAdspBattery &b = fAdspLast;"),
        (publish, "setExternalConnected(b.external != 0);"),
        (publish, 'putBool("AppleRawExternalConnected", b.external != 0);'),
        (publish, "setIsCharging(b.charging != 0);"),
        (publish, "setCycleCount(b.cycles > 0 ? (unsigned)b.cycles : 0);"),
        (publish, 'putBool("FullyCharged", b.fully_charged != 0);'),
        (publish, "b.external ? b.adapter_family : 0"),
        (publish, "b.external ? kIOBatteryChargerConnect : 0"),
        (publish, "b.charging ? kIOBatteryCharge : 0"),
        (publish, 'putBool("SweetBatteryHardwareSampleValid", b.soc_known && b.voltage_valid);'),
        (publish, 'putBool("SweetBatteryCurrentValid", b.current_valid != 0);'),
        (publish, 'putBool("FuxiBatterySourceStale", b.stale != 0);'),
        (publish, "fAdspShown = fAdspShown || b.sequence != 0;"),
        (publish, 'putBool("SweetBatterySOCEstimated", !fAdspSOCShown);'),
        (publish, 'putBool("SweetBatteryTemperatureEstimated", !fAdspTemperatureShown);'),
        (poll, "if (fAdsp || fAdspShown)"),
        (poll, "if (fLastMode == -1) publish(100, 4200, 0, true, true, false, true, false, false);"),
        (poll, "publishAdsp(adsp);\n\t\treturn;"),
        (start, "publishAdsp(unavailable);"),
        (start, "fuxi_adsp_battery_on_change(&SweetBattery::adspChanged, this);"),
        (text, "fuxi_adsp_battery_on_change(NULL, NULL);\n#endif\n\tif (fLoop && fTimerAdded) {"),
        (text, "self->fNotify->interruptOccurred(NULL, NULL, 0);"),
        (text, "fAdspLast.temperature = 2500;"),
    ]
    for section, required in expected:
        assert required in section, required
    assert "fReal = fAdsp = false;" not in start
    assert poll.index("publishAdsp(adsp);") < poll.index("sweet_spmi_read(")
    assert "incoming." not in publish
    print(f"PASS consumer source wiring: {len(expected) + 3} structural checks (not IOKit execution)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sanitize", action="store_true")
    arguments = parser.parse_args()
    check_consumer_wiring()
    host_tools = runpy.run_path(str(ROOT / "tools/test-fuxi-audio-prep.py"))
    compiler, environment = host_tools["compiler_environment"]()
    msvc = Path(compiler[0].strip('"')).name.lower() in ("cl", "cl.exe")
    with tempfile.TemporaryDirectory(prefix="publication-host-", dir=PREP) as directory:
        temporary = Path(directory)
        for name in ("pexpert/arm64/board_config.h", "sys/param.h", "sys/systm.h",
                     "kern/clock.h", "kern/locks.h", "kern/thread_call.h", "pexpert/pexpert.h"):
            header = temporary / name
            header.parent.mkdir(parents=True, exist_ok=True)
            header.write_text("\n", encoding="utf-8")
        (temporary / "battery_host.h").write_text(HOST_HEADER, encoding="utf-8")
        harness = temporary / "publication_host.c"
        harness.write_text(HARNESS.replace("@PRODUCER@", (SOURCE / "fuxi_adsp_battery.c").as_posix()), encoding="utf-8")
        consumer_text = (SOURCE / "SweetBattery.cpp").read_text(encoding="utf-8")
        publish = re.search(r"void\s+SweetBattery::publishAdsp\([^\n]*\)\n\{.*?\n\}\n(?=#endif)",
            consumer_text, re.S)
        assert publish, "production publishAdsp method not found"
        consumer = temporary / "consumer_host.cpp"
        callbacks = re.search(r"void\s+SweetBattery::adspChanged\(.*?\n\}\n(?=#endif)",
            consumer_text, re.S)
        assert callbacks, "production change callbacks not found"
        consumer.write_text(CONSUMER_HOST.replace("@PUBLISH_ADSP@", publish[0]).replace(
            "@CHANGE_CALLBACKS@", callbacks[0]), encoding="utf-8")
        consumer_object = temporary / ("consumer_host.obj" if msvc else "consumer_host.o")
        if msvc:
            consumer_flags = ["/nologo", "/TP", "/std:c++17", "/W4", "/WX", "/Od", "/Zi", "/MD", "/c"]
            if arguments.sanitize:
                consumer_flags += ["/fsanitize=address"]
            consumer_command = compiler + consumer_flags + [f"/I{SOURCE}", f"/I{PREP}",
                str(consumer), f"/Fo:{consumer_object}"]
        else:
            consumer_flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-O1", "-g", "-x", "c++", "-c"]
            if arguments.sanitize:
                consumer_flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            consumer_command = compiler + consumer_flags + ["-I", str(SOURCE), "-I", str(PREP),
                str(consumer), "-o", str(consumer_object)]
        subprocess.run(consumer_command, cwd=directory, env=environment, check=True, timeout=120)
        vendor = SOURCE / "ShengBattmgr.c"
        if msvc:
            vendor_text = vendor.read_text(encoding="utf-8")
            field_table = re.search(r"kFields\[BmFields\] = \{(.*?)\n\};", vendor_text, re.S)
            enum_body = re.search(r"enum\s*\{(.*?)\};", (SOURCE / "ShengBattmgr.h").read_text(), re.S)[1]
            enum_names = [name.strip() for name in re.sub(r"/\*.*?\*/", "", enum_body, flags=re.S).split(",")]
            assert re.findall(r"\[(Bm\w+)\]\s*=", field_table[1]) == enum_names[:-1]
            translated = re.sub(r"\[Bm\w+\]\s*=\s*", "", field_table[1])
            vendor_text = vendor_text[:field_table.start(1)] + translated + vendor_text[field_table.end(1):]
            vendor = temporary / "battmgr_host.c"
            vendor.write_text(vendor_text, encoding="utf-8")
        sources = [harness, PREP / "fuxi_battery_freshness.c", vendor]
        executable = temporary / ("publication-test.exe" if os.name == "nt" else "publication-test")
        if msvc:
            flags = ["/nologo", "/TC", "/std:c11", "/W4", "/WX", "/Od", "/Zi", "/MD", "/DFUXI"]
            if arguments.sanitize:
                flags += ["/fsanitize=address"]
            command = compiler + flags + [f"/I{temporary}", f"/I{SOURCE}", f"/I{PREP}",
                f"/FI{temporary / 'battery_host.h'}"] + [str(source) for source in sources] + [f"/Fe:{executable}"]
        else:
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-g", "-DFUXI"]
            if arguments.sanitize:
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            command = compiler + flags + ["-I", str(temporary), "-I", str(SOURCE), "-I", str(PREP),
                "-include", str(temporary / "battery_host.h")] + [str(source) for source in sources] + ["-o", str(executable)]
        if msvc:
            command += ["/link", str(consumer_object)]
        else:
            command += [str(consumer_object)]
            command += ["-lc++" if sys.platform == "darwin" else "-lstdc++"]
        subprocess.run(command, cwd=directory, env=environment, check=True, timeout=120)
        result = subprocess.run([str(executable)], cwd=directory, env=environment,
            capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        passed = [line for line in result.stdout.splitlines() if line.startswith("PASS fuxi-battery production publication:")]
        assert len(passed) == 1, result.stdout
        print(passed[0])
        print(f"compiler={Path(compiler[0]).name}, sanitize={arguments.sanitize}, vendor_table_translation={msvc}")
        print("PASS consumer production publishAdsp execution with host IOKit objects (not native IOKit)")


if __name__ == "__main__":
    main()
