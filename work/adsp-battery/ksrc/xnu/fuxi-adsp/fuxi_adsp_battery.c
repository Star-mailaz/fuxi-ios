/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* fuxiadsp=2: the client of the battery manager the audio DSP runs (PMIC GLINK channel "PMIC_RTR_ADSP_APPS"). Phase 1 only reads:
 * every refresh cycle of ShengBattmgr.c (one request in flight, 2 s per request, a cycle every 60 s and at each notification) ends
 * in a "FUXI BATTERY:" log line with what iOS would be shown, and the first cycles also list every raw field, so the Fuxi board's
 * properties can be checked before anything is published to powerd (SweetBattery keeps its default until then). Charging itself
 * stays with the DSP firmware; nothing is written to it except the notification enable request.
 * Adapted from UniXNU-sheng package/ShengBattery.cpp (6880068), BSD-2-Clause-Patent: Copyright (c) 2026, UniXNU contributors
 * (LICENSE.UniXNU-sheng). Design as there: the DSP thread's callbacks only copy a message into a small ring and kick a thread
 * call, so the DSP thread never waits for this client and never re-enters sheng_adsp_send; the cycle runs in that thread call.
 *
 */
#include <pexpert/arm64/board_config.h>
#if defined(FUXI)
#include <sys/param.h>
#include <sys/systm.h>
#include <kern/clock.h>
#include <kern/locks.h>
/* thread_call_data_t / thread_call_setup_with_options are MACH_KERNEL_PRIVATE; same exposure as fuxi_adreno.c. */
#define MACH_KERNEL_PRIVATE 1
#include <kern/thread_call.h>
#undef MACH_KERNEL_PRIVATE
#include <pexpert/pexpert.h>
#include "ShengAdsp.h"
#include "ShengBattmgr.h"
#include "fuxi_adsp_battery.h"
#include "fuxi_battery_freshness.h"
#include "fuxi_battery_poll_pause.h"

void fuxi_adsp_battery_start(int publish);
extern unsigned fuxi_adsp_mode(void);

#define FB_REQUEST_MS 2000u
#define FB_REFRESH_MS 10000u
#define FB_SLOW_EVERY 10u
#define FB_RING 16u

static LCK_GRP_DECLARE(fb_grp, "fuxi_adsp_battery");
static LCK_MTX_DECLARE(fb_ring_lock, &fb_grp); /* the ring (callbacks on the DSP thread vs. the thread call) */
static LCK_MTX_DECLARE(fb_lock, &fb_grp);      /* the battery manager state */
static struct { uint64_t generation, received_at_ms; uint32_t length; uint8_t data[SHENG_ADSP_MAX_MESSAGE]; } fb_ring[FB_RING];
static uint32_t fb_head, fb_count, fb_dropped;
static volatile uint32_t fb_up, fb_changed, fb_lost;
static ShengBattmgr fb_bm;
static ShengAdspChannel *fb_channel;
static thread_call_data_t fb_call;
static int fb_was_up;
static uint64_t fb_request_due, fb_refresh_due; /* absolute time; 0 = none */
static uint32_t fb_refreshes, fb_logged, fb_send_refused;
static LCK_MTX_DECLARE(fb_pub_lock, &fb_grp);  /* the published reading (the thread call vs. SweetBattery's work loop) */
static FuxiAdspBattery fb_pub;
static FuxiBatteryFreshness fb_fresh;
static int32_t fb_values[BmFields];
static uint64_t fb_worker_generation, fb_request_generation;
static uint32_t fb_max_age_ms = FUXI_BATTERY_DEFAULT_MAX_AGE_MS;
static FuxiBatteryPollPause fb_pause;
static int fb_publish;
static void (*fb_change_fn)(void *);  /* under fb_pub_lock, like the reading it watches */
static void *fb_change_arg;
static uint32_t fb_change_key;
static uint32_t fb_implausible;
static uint64_t fbNowMs(void);

/* ---- the DSP thread: copy and kick, nothing else ---- */
static void fbState(void *context, int up)
{
    (void)context;
    lck_mtx_lock(&fb_ring_lock);
    lck_mtx_lock(&fb_pub_lock);
    const uint64_t before = fb_fresh.generation;
    (void)fuxi_battery_prep_channel(&fb_fresh, up);
    if (before != fb_fresh.generation || !up) {
        fb_dropped += fb_count;
        fb_head = fb_count = 0;
    }
    if (!up) __atomic_store_n(&fb_lost, 1u, __ATOMIC_RELEASE);
    __atomic_store_n(&fb_up, fb_fresh.channel_up ? 1u : 0u, __ATOMIC_RELEASE);
    __atomic_store_n(&fb_changed, 1u, __ATOMIC_RELEASE);
    lck_mtx_unlock(&fb_pub_lock);
    lck_mtx_unlock(&fb_ring_lock);
    (void)thread_call_enter(&fb_call);
}
static void fbReceive(void *context, const uint8_t *data, uint32_t length)
{
    (void)context;
    lck_mtx_lock(&fb_ring_lock);
    lck_mtx_lock(&fb_pub_lock);
    if (fb_fresh.channel_up && fb_count < FB_RING && length && length <= SHENG_ADSP_MAX_MESSAGE) {
        const uint32_t slot = (fb_head + fb_count) % FB_RING;
        fb_ring[slot].generation = fb_fresh.generation;
        fb_ring[slot].received_at_ms = fbNowMs();
        memcpy(fb_ring[slot].data, data, length);
        fb_ring[slot].length = length;
        fb_count++;
    } else {
        fb_dropped++;
    }
    lck_mtx_unlock(&fb_pub_lock);
    lck_mtx_unlock(&fb_ring_lock);
    (void)thread_call_enter(&fb_call);
}

/* ---- the thread call ---- */
static uint64_t fbDeadline(uint32_t ms)
{
    uint64_t at;
    clock_interval_to_deadline(ms, NSEC_PER_MSEC, &at);
    return at;
}
static uint64_t fbNowMs(void)
{
    uint64_t ns;
    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    return ns / NSEC_PER_MSEC;
}

static uint32_t fbAge(unsigned field, uint64_t now_ms)
{
    if (!(fb_fresh.observed_fields & (1u << field)) || now_ms < fb_fresh.successful_at_ms[field]) return UINT32_MAX;
    const uint64_t age = now_ms - fb_fresh.successful_at_ms[field];
    return age > UINT32_MAX ? UINT32_MAX : (uint32_t)age;
}

static void fbPauseLog(const char *event, uint64_t now_ms)
{
    printf("FUXI BATTERY: poll-pause %s generation=%llu channel_generation=%llu channel_up=%u now_ms=%llu ttl_ms=%u duration_ms=%u "
        "soc_age_ms=%u external_age_ms=%u status_age_ms=%u reason=%u\n",
        event, (unsigned long long)fb_pause.generation, (unsigned long long)fb_fresh.generation,
        (unsigned)(fb_fresh.channel_up != 0), (unsigned long long)now_ms,
        fb_max_age_ms, fb_pause.duration_ms, fbAge(BmCapacity, now_ms), fbAge(BmUsbOnline, now_ms),
        fbAge(BmStatus, now_ms), (unsigned)fb_pause.reason);
}

static FuxiBatteryPollPauseDecision fbPauseStep(uint64_t now_ms)
{
    lck_mtx_lock(&fb_pub_lock);
    const enum FuxiBatteryPollPausePhase before = fb_pause.phase;
    const int idle = fb_was_up && fb_worker_generation == fb_fresh.generation &&
        !fb_request_due && !fb_bm.in_flight && !fb_bm.limit_in_flight && fb_bm.keyboard_in_flight < 0;
    const FuxiBatteryPollPauseDecision decision = fuxi_battery_poll_pause_step(
        &fb_pause, &fb_fresh, now_ms, fb_max_age_ms, idle);
    if (decision.phase == FuxiBatteryPollPauseCancelled && before != decision.phase) {
        fbPauseLog("cancel", now_ms);
    } else if (decision.pause_once) {
        fbPauseLog("start", now_ms);
    } else if (decision.resume_once) {
        fbPauseLog("end", now_ms);
    }
    lck_mtx_unlock(&fb_pub_lock);
    return decision;
}

static void fbValidity(FuxiAdspBattery *b, uint64_t now_ms)
{
    FuxiBatteryPublishDecision decision;
    (void)fuxi_battery_prep_decide(&fb_fresh, now_ms, fb_max_age_ms, &decision);
    b->generation = fb_fresh.generation;
    b->fresh_fields = decision.fresh_fields;
    b->max_age_ms = fb_max_age_ms;
    b->soc_age_ms = fbAge(BmCapacity, now_ms);
    b->external_age_ms = fbAge(BmUsbOnline, now_ms);
    b->status_age_ms = fbAge(BmStatus, now_ms);
    b->channel_up = fb_fresh.channel_up != 0;
    b->soc_known = decision.update_capacity != 0;
    b->external_known = decision.update_external != 0;
    b->status_known = decision.update_charging || (b->external_known && !b->external);
    b->voltage_valid = (decision.fresh_fields & (1u << BmVoltage)) != 0;
    b->current_valid = (decision.fresh_fields & (1u << BmCurrent)) != 0;
    b->temperature_valid = (decision.fresh_fields & (1u << BmTemperature)) != 0;
    b->stale = !b->channel_up || !b->soc_known || !b->external_known || !b->status_known;
}
static void fbRaw(void)
{
    char line[400];
    unsigned at = 0;
    for (unsigned i = 0; i < BmFields && at + 24 < sizeof(line); ++i) {
        const int n = (fb_bm.valid >> i) & 1u ? snprintf(line + at, sizeof(line) - at, " f%u=%d", i, fb_bm.value[i])
                                              : snprintf(line + at, sizeof(line) - at, " f%u=-", i);
        if (n <= 0) break;
        at += (unsigned)n;
    }
    printf("FUXI BATTERY: raw valid=%#x last_timeout=%d%s\n", fb_bm.valid, fb_bm.last_timeout, line);
}
static void fbBoard(ShengBatterySnapshot *s, const ShengBattmgr *bm);

static void fbPublish(uint64_t now_ms)
{
    ShengBattmgr measured;
    ShengBatterySnapshot snapshot;
    FuxiAdspBattery b;
    FuxiBatteryPublishDecision decision;
    bzero(&measured, sizeof(measured));
    (void)fuxi_battery_prep_decide(&fb_fresh, now_ms, fb_max_age_ms, &decision);
    measured.valid = decision.fresh_fields;
    memcpy(measured.value, fb_values, sizeof(fb_values));
    sheng_battmgr_snapshot(&measured, &snapshot);
    fbBoard(&snapshot, &measured);
    const ShengBatterySnapshot *s = &snapshot;
    bzero(&b, sizeof(b));
    b.percent = s->percent < 1 ? 1 : s->percent;
    b.voltage_mv = s->voltage_mv;
    b.current_ma = s->current_ma;
    b.temperature = s->temperature;
    b.temperature_valid = s->temperature_valid ? 1 : 0;
    b.raw_mah = s->raw_mah > 0 ? s->raw_mah : 0;
    b.full_mah = s->full_mah > 0 ? s->full_mah : 0;
    b.design_mah = s->design_mah > 0 ? s->design_mah : 0;
    b.cycles = s->cycles > 0 ? s->cycles : 0;
    b.minutes_to_empty = s->time_to_empty_min;
    b.minutes_to_full = s->time_to_full_min;
    b.adapter_family = s->adapter_family;
    b.adapter_mv = s->adapter_mv;
    b.adapter_ma = s->adapter_ma;
    b.adapter_watts = s->adapter_watts;
    b.present = s->present ? 1 : 0;
    b.external = s->external ? 1 : 0;
    b.charging = s->charging ? 1 : 0;
    b.fully_charged = s->fully_charged ? 1 : 0;
    b.sequence = fb_pub.sequence + 1;
    if (!b.sequence) b.sequence = 1;
    fbValidity(&b, now_ms);
    fuxi_battery_prep_merge(&fb_pub, &b);
    /* 2026-11-16 torchlock trip: the cable was pulled twice for about 10 and 15 s; this file saw both at once, SweetBattery's
     * 30 s sample saw neither, and iOS kept showing a charger. Ask for a sample whenever the shown state changes. */
    const uint32_t key = ((uint32_t)fb_pub.percent & 0xffu) | ((uint32_t)(fb_pub.external != 0) << 8) |
        ((uint32_t)(fb_pub.charging != 0) << 9) | ((uint32_t)(fb_pub.fully_charged != 0) << 10) |
        ((uint32_t)(b.external_known != 0) << 11) | ((uint32_t)(b.status_known != 0) << 12) |
        ((uint32_t)(fb_pub.present != 0) << 13) | ((uint32_t)(b.soc_known != 0) << 14) | 0x10000u;
    if (key != fb_change_key) {
        fb_change_key = key;
        if (fb_change_fn) fb_change_fn(fb_change_arg);
    }
}

static int fbValueValid(unsigned field, int32_t value)
{
    switch (field) {
    case BmCapacity: return value >= 0 && value <= 10000;
    case BmVoltage: return value >= 2500000 && value <= 4800000;
    case BmCurrent:
    case BmUsbCurrent: return value != INT32_MIN;
    case BmTemperature: return value >= -4000 && value <= 9000;
    case BmStatus: return value >= 1 && value <= 4;
    case BmPresent:
    case BmUsbOnline: return value == 0 || value == 1;
    default: return value >= 0;
    }
}

int fuxi_adsp_battery_wanted(void) { return fuxi_adsp_mode() >= 3; }

void fuxi_adsp_battery_on_change(void (*fn)(void *), void *arg)
{
    lck_mtx_lock(&fb_pub_lock);
    fb_change_fn = fn;
    fb_change_arg = fn ? arg : NULL;
    lck_mtx_unlock(&fb_pub_lock);
}

/* Test loaders only (fuxi,adsp=4, fuxi_adsp.c): once the boot tour sets fuxi_tour_battery_test (bsd/dev/fuxi_keys.c), every
 * reading handed to SweetBattery says "57%, unplugged, discharging" while the log keeps the real one, so a screenshot shows whether
 * iOS's battery display follows a published change. Without fuxi,adsp=4 the flag is ignored. */
extern unsigned fuxi_adsp_battery_test_mode(void);
extern volatile uint32_t fuxi_tour_battery_test;
static uint32_t fb_test_said;

int fuxi_adsp_battery_reading(FuxiAdspBattery *out)
{
    int have;
    if (!out || !fb_publish) return 0;
    lck_mtx_lock(&fb_pub_lock);
    *out = fb_pub;
    fbValidity(out, fbNowMs());
    have = 1;
    lck_mtx_unlock(&fb_pub_lock);
    if (out->soc_known && out->external_known && out->status_known &&
        __atomic_load_n(&fuxi_tour_battery_test, __ATOMIC_ACQUIRE) && fuxi_adsp_battery_test_mode()) {
        if (!__atomic_exchange_n(&fb_test_said, 1u, __ATOMIC_ACQ_REL))
            printf("FUXI BATTERY: TEST (fuxi,adsp=4) SweetBattery now gets a staged reading: 57%%, unplugged, -300 mA\n");
        out->percent = 57;
        out->current_ma = -300;
        out->external = 0;
        out->external_known = 1;
        out->charging = 0;
        out->status_known = 1;
        out->fully_charged = 0;
        out->minutes_to_full = -1;
    }
    return have;
}

/* Fuxi has one cell and one fuel gauge. ShengBattmgr's snapshot adds the sheng tablet's second gauge (board properties
 * 0xa6/0xa7), which this firmware answers with 0 and with the first gauge's remaining charge, so the sum read about half
 * (2026-11-16 adsp2: 4002/(4265+4002) mAh = 48% while Android showed 97% and the firmware's capacity property was 9600).
 * Use the firmware's state of charge (battery property 4, hundredths of a percent) as Android does, and the first gauge's
 * remaining charge (uAh) as the raw capacity: property 15 answers 4002 here, i.e. mAh, which the snapshot turns into 4. */
static void fbBoard(ShengBatterySnapshot *s, const ShengBattmgr *bm)
{
#define FB_HAS(f) ((bm->valid >> (f)) & 1u)
    if (FB_HAS(BmCapacity) && bm->value[BmCapacity] >= 0 && bm->value[BmCapacity] <= 10000) {
        s->percent = (bm->value[BmCapacity] + 50) / 100;
        s->charge_known = 1;
        s->fully_charged = s->external && ((FB_HAS(BmStatus) && bm->value[BmStatus] == 4) || s->percent == 100);
        s->critical = s->present && s->external_known && !s->external && s->percent <= 2;
    }
    if (FB_HAS(BmGauge1Remaining) && bm->value[BmGauge1Remaining] > 0)
        s->raw_mah = bm->value[BmGauge1Remaining] / 1000;
    /* The adapter's kind: this firmware keeps the USB property 1 (BmUsbType) at SDP for the whole session and reports what charger
     * detection found in property 20 (BmUsbAdapter): 2026-11-16 adsp2b went SDP -> PD there (input limit 500 mA -> 1.2 A) while
     * BmUsbType stayed 1, so the log named a PD charger a computer port (SweetBattery does not publish the family yet). Same
     * POWER_SUPPLY_USB_TYPE -> kIOPSFamilyCode mapping as ShengBattmgr.c family(). */
    if (s->external && FB_HAS(BmUsbAdapter) && bm->value[BmUsbAdapter] > 0) {
        switch (bm->value[BmUsbAdapter]) {
        case 1: s->adapter_family = 0xe0004000u; break;
        case 2: s->adapter_family = 0xe0004004u; break;
        case 3: s->adapter_family = 0xe0004005u; break;
        case 5: s->adapter_family = 0xe0004009u; break;
        case 6: case 7: case 8: s->adapter_family = 0xe000400au; break;
        default: s->adapter_family = 0xe0004007u; break;
        }
    }
#undef FB_HAS
}

static void fbLog(void)
{
    ShengBatterySnapshot s;
    sheng_battmgr_snapshot(&fb_bm, &s);
    fbBoard(&s, &fb_bm);
    printf("FUXI BATTERY: percent=%d%s mV=%d mA=%d temp=%d%s present=%d external=%d%s charging=%d%s full=%d critical=%d "
        "mAh raw=%d full=%d design=%d cycles=%d tte_min=%d ttf_min=%d adapter=%#x %dmV %dmA %dW | cycles=%u answers=%u timeouts=%u "
        "errors=%u notifications=%u ignored=%u dropped=%u refused=%u\n",
        s.percent, s.charge_known ? "" : "(default)", s.voltage_mv, s.current_ma, s.temperature, s.temperature_valid ? "" : "(invalid)",
        s.present, s.external, s.external_known ? "" : "(unknown)", s.charging, s.status_known ? "" : "(unknown)", s.fully_charged,
        s.critical, s.raw_mah, s.full_mah, s.design_mah, s.cycles, s.time_to_empty_min, s.time_to_full_min, s.adapter_family,
        s.adapter_mv, s.adapter_ma, s.adapter_watts, fb_bm.cycles_done, fb_bm.responses, fb_bm.timeouts, fb_bm.errors,
        fb_bm.notifications, fb_bm.ignored, fb_dropped, fb_send_refused);
    if (fb_logged++ < 3 || fb_logged % 10 == 0) fbRaw();
}
static void fbPump(void)
{
    uint8_t out[SHENG_BATTMGR_REQUEST_BYTES];
    if (!fb_was_up || fb_request_due) return;
    lck_mtx_lock(&fb_pub_lock);
    if (!fb_fresh.channel_up || fb_worker_generation != fb_fresh.generation) {
        lck_mtx_unlock(&fb_pub_lock);
        return;
    }
    const int set_due = fb_bm.limit_due || (fb_bm.keyboard_wanted >= 0 &&
        fb_bm.keyboard_wanted != fb_bm.keyboard_acked && fb_bm.keyboard_tries < 3);
    if (fb_pause.phase == FuxiBatteryPollPauseHolding && !set_due) {
        lck_mtx_unlock(&fb_pub_lock);
        return;
    }
    const uint32_t n = sheng_battmgr_next(&fb_bm, out);
    if (!n) {
        lck_mtx_unlock(&fb_pub_lock);
        return;
    }
    const int refused = sheng_adsp_send(fb_channel, out, n);
    if (refused) fb_send_refused++;
    fb_request_due = fbDeadline(FB_REQUEST_MS);
    fb_request_generation = refused ? 0 : fb_worker_generation;
    lck_mtx_unlock(&fb_pub_lock);
}
static void fbRun(thread_call_param_t p0, thread_call_param_t p1)
{
    (void)p0; (void)p1;
    lck_mtx_lock(&fb_lock);
    if (__atomic_exchange_n(&fb_changed, 0u, __ATOMIC_ACQ_REL)) {
        const int up = __atomic_load_n(&fb_up, __ATOMIC_ACQUIRE) != 0;
        lck_mtx_lock(&fb_pub_lock);
        fb_worker_generation = fb_fresh.generation;
        lck_mtx_unlock(&fb_pub_lock);
        /* A down/up pair may coalesce into one event: a loss always resets the cycle. */
        if (__atomic_exchange_n(&fb_lost, 0u, __ATOMIC_ACQ_REL)) {
            fb_request_due = 0;
            fb_refresh_due = 0;
            fb_request_generation = 0;
            sheng_battmgr_init(&fb_bm);
            if (fb_was_up) printf("FUXI BATTERY: channel down\n");
            fb_was_up = 0;
        }
        const int before = fb_was_up;
        fb_was_up = up;
        if (up && !before) {
            uint8_t enable[SHENG_BATTMGR_ENABLE_BYTES];
            if (sheng_adsp_send(fb_channel, enable, sheng_battmgr_enable_request(enable))) fb_send_refused++;
            sheng_battmgr_refresh(&fb_bm, 1);
            fb_refresh_due = fbDeadline(FB_REFRESH_MS);
            printf("FUXI BATTERY: channel up; notifications requested, first refresh\n");
        }
    }
    for (;;) {
        uint8_t data[SHENG_ADSP_MAX_MESSAGE];
        uint32_t length = 0;
        uint64_t generation = 0;
        uint64_t received_at = 0;
        lck_mtx_lock(&fb_ring_lock);
        if (fb_count) {
            length = fb_ring[fb_head].length;
            generation = fb_ring[fb_head].generation;
            received_at = fb_ring[fb_head].received_at_ms;
            memcpy(data, fb_ring[fb_head].data, length);
            fb_head = (fb_head + 1) % FB_RING;
            fb_count--;
        }
        lck_mtx_unlock(&fb_ring_lock);
        if (!length) break;
        lck_mtx_lock(&fb_pub_lock);
        if (!fb_fresh.channel_up || generation != fb_fresh.generation || generation != fb_worker_generation) {
            lck_mtx_unlock(&fb_pub_lock);
            continue;
        }
        const unsigned field = fb_bm.in_flight && generation == fb_request_generation ? fb_bm.cursor : BmFields;
        const uint32_t responses = fb_bm.responses;
        const int result = sheng_battmgr_receive(&fb_bm, data, length);
        if (field < BmFields && fb_bm.responses != responses && (fb_bm.valid & (1u << field))) {
            if (fbValueValid(field, fb_bm.value[field])) {
                if (fuxi_battery_prep_observe(&fb_fresh, generation, field, received_at, 1) == FuxiBatteryPrepOk) {
                    fb_values[field] = fb_bm.value[field];
                    if (fb_publish) fbPublish(fbNowMs());
                }
            } else {
                fb_bm.valid &= ~(1u << field);
                if (fb_implausible++ < 8) printf("FUXI BATTERY: rejected field %u value %d\n", field, fb_bm.value[field]);
            }
        }
        lck_mtx_unlock(&fb_pub_lock);
        if (result == BmAnswer || result == BmCycleDone) fb_request_due = 0;
        if (result == BmCycleDone) fbLog();
    }
    const uint64_t now = mach_absolute_time();
    if (fb_was_up && fb_request_due && now >= fb_request_due) {
        const uint32_t before = fb_bm.cycles_done;
        sheng_battmgr_timeout(&fb_bm);
        fb_request_due = 0;
        if (fb_bm.cycles_done != before) fbLog();
    }
    if (fb_was_up && fb_refresh_due && now >= fb_refresh_due) {
        sheng_battmgr_refresh(&fb_bm, ++fb_refreshes % FB_SLOW_EVERY == 0);
        fb_refresh_due = fbDeadline(FB_REFRESH_MS);
    }
    const FuxiBatteryPollPauseDecision pause = fbPauseStep(fbNowMs());
    fbPump();
    uint64_t next = 0;
    if (fb_was_up && fb_request_due) next = fb_request_due;
    if (fb_was_up && fb_refresh_due && (!next || fb_refresh_due < next)) next = fb_refresh_due;
    if (pause.wake_at_ms) {
        const uint64_t now_ms = fbNowMs();
        const uint64_t remaining = pause.wake_at_ms > now_ms ? pause.wake_at_ms - now_ms : 1u;
        const uint32_t wait_ms = remaining > FUXI_BATTERY_POLL_PAUSE_MAX_DURATION_MS ?
            FUXI_BATTERY_POLL_PAUSE_MAX_DURATION_MS : (uint32_t)remaining;
        const uint64_t wake = fbDeadline(wait_ms);
        if (!next || wake < next) next = wake;
    }
    if (next) (void)thread_call_enter_delayed(&fb_call, next);
    lck_mtx_unlock(&fb_lock);
}

/* Called by fuxi_adsp_init before the DSP thread starts (the channel registers before the DSP can open it). publish: fuxiadsp=3. */
void fuxi_adsp_battery_start(int publish)
{
    static const ShengAdspClient client = {fbState, fbReceive};
    sheng_battmgr_init(&fb_bm);
    thread_call_setup_with_options(&fb_call, fbRun, NULL, THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE);
    fb_publish = publish != 0;
    (void)fuxi_battery_prep_init(&fb_fresh);
    bzero(fb_values, sizeof(fb_values));
    bzero(&fb_pub, sizeof(fb_pub));
    uint32_t max_age = FUXI_BATTERY_DEFAULT_MAX_AGE_MS;
    if (PE_parse_boot_argn("fuxibatttl", &max_age, sizeof(max_age)) && max_age >= FB_REQUEST_MS && max_age <= 3600000u)
        fb_max_age_ms = max_age;
    uint64_t pause_ms = FUXI_BATTERY_POLL_PAUSE_DEFAULT_MS;
    uint64_t pause_delay_ms = 0;
    (void)PE_parse_boot_argn("fuxibatpause", &pause_ms, sizeof(pause_ms));
    (void)PE_parse_boot_argn("fuxibatpausedelay", &pause_delay_ms, sizeof(pause_delay_ms));
    if (fuxi_battery_poll_pause_init(&fb_pause, pause_delay_ms, pause_ms))
        fbPauseLog("cancel", fbNowMs());
    fb_channel = sheng_adsp_channel("PMIC_RTR_ADSP_APPS", 1024, 4, 0, &client, NULL);
    printf("FUXI BATTERY: battery manager client %s%s\n", fb_channel ? "registered" : "NOT registered",
        fb_publish ? ", readings go to SweetBattery" : "");
}
#endif /* FUXI */
