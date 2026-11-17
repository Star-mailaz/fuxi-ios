#ifndef FUXI_BATTERY_POLL_PAUSE_H
#define FUXI_BATTERY_POLL_PAUSE_H

#include "fuxi_battery_freshness.h"

#define FUXI_BATTERY_POLL_PAUSE_DEFAULT_MS 0u
#define FUXI_BATTERY_POLL_PAUSE_MAX_DELAY_MS 60000u
#define FUXI_BATTERY_POLL_PAUSE_MAX_DURATION_MS 300000u
#define FUXI_BATTERY_POLL_PAUSE_TTL_MARGIN_MS 1000u

enum FuxiBatteryPollPausePhase {
    FuxiBatteryPollPauseOff = 0,
    FuxiBatteryPollPauseWaiting,
    FuxiBatteryPollPauseArmed,
    FuxiBatteryPollPauseHolding,
    FuxiBatteryPollPauseDone,
    FuxiBatteryPollPauseCancelled
};

enum FuxiBatteryPollPauseReason {
    FuxiBatteryPollPauseNoReason = 0,
    FuxiBatteryPollPauseConfig,
    FuxiBatteryPollPauseArgument,
    FuxiBatteryPollPauseClock,
    FuxiBatteryPollPauseChannel,
    FuxiBatteryPollPauseGeneration,
    FuxiBatteryPollPauseTtl,
    FuxiBatteryPollPauseOverflow,
    FuxiBatteryPollPauseMissedWindow,
    FuxiBatteryPollPauseBaseline
};

typedef struct {
    uint64_t generation;
    uint64_t last_now_ms;
    uint64_t pause_at_ms;
    uint64_t start_before_ms;
    uint64_t resume_at_ms;
    uint32_t delay_ms;
    uint32_t duration_ms;
    uint32_t max_age_ms;
    enum FuxiBatteryPollPausePhase phase;
    enum FuxiBatteryPollPauseReason reason;
    int clock_seen;
} FuxiBatteryPollPause;

typedef struct {
    uint64_t wake_at_ms;
    enum FuxiBatteryPollPausePhase phase;
    enum FuxiBatteryPollPauseReason reason;
    int withhold_get;
    int pause_once;
    int resume_once;
} FuxiBatteryPollPauseDecision;

static inline int fuxi_battery_poll_pause_init(FuxiBatteryPollPause *state,
    uint64_t delay_ms, uint64_t duration_ms)
{
    const FuxiBatteryPollPause initial = {0};
    if (!state) {
        return -1;
    }
    *state = initial;
    if (!duration_ms) {
        return 0;
    }
    if (delay_ms > FUXI_BATTERY_POLL_PAUSE_MAX_DELAY_MS ||
        duration_ms > FUXI_BATTERY_POLL_PAUSE_MAX_DURATION_MS ||
        duration_ms < FUXI_BATTERY_POLL_PAUSE_TTL_MARGIN_MS) {
        state->phase = FuxiBatteryPollPauseCancelled;
        state->reason = FuxiBatteryPollPauseConfig;
        return -1;
    }
    state->delay_ms = (uint32_t)delay_ms;
    state->duration_ms = (uint32_t)duration_ms;
    state->phase = FuxiBatteryPollPauseWaiting;
    return 0;
}

static inline FuxiBatteryPollPauseDecision fuxi_battery_poll_pause_result(
    const FuxiBatteryPollPause *state, int pause_once, int resume_once)
{
    FuxiBatteryPollPauseDecision result = {0};
    result.phase = state->phase;
    result.reason = state->reason;
    result.pause_once = pause_once;
    result.resume_once = resume_once;
    result.withhold_get = state->phase == FuxiBatteryPollPauseHolding;
    if (result.withhold_get) {
        result.wake_at_ms = state->resume_at_ms;
    } else if (state->phase == FuxiBatteryPollPauseArmed) {
        result.wake_at_ms = state->last_now_ms < state->pause_at_ms ?
            state->pause_at_ms : state->start_before_ms;
    }
    return result;
}

static inline FuxiBatteryPollPauseDecision fuxi_battery_poll_pause_cancel(
    FuxiBatteryPollPause *state, enum FuxiBatteryPollPauseReason reason)
{
    const int resumed = state->phase == FuxiBatteryPollPauseHolding;
    state->phase = FuxiBatteryPollPauseCancelled;
    state->reason = reason;
    return fuxi_battery_poll_pause_result(state, 0, resumed);
}

static inline FuxiBatteryPollPauseDecision fuxi_battery_poll_pause_step(
    FuxiBatteryPollPause *state, const FuxiBatteryFreshness *freshness,
    uint64_t now_ms, uint32_t max_age_ms, int quiescent)
{
    FuxiBatteryPublishDecision baseline;
    const uint32_t required = (UINT32_C(1) << BmCapacity) |
        (UINT32_C(1) << BmUsbOnline) | (UINT32_C(1) << BmStatus);

    if (!state) {
        FuxiBatteryPollPauseDecision result = {0};
        result.phase = FuxiBatteryPollPauseCancelled;
        result.reason = FuxiBatteryPollPauseArgument;
        return result;
    }
    if (state->phase == FuxiBatteryPollPauseOff ||
        state->phase == FuxiBatteryPollPauseDone ||
        state->phase == FuxiBatteryPollPauseCancelled) {
        return fuxi_battery_poll_pause_result(state, 0, 0);
    }
    if (!freshness) {
        return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseArgument);
    }
    if (state->clock_seen && now_ms < state->last_now_ms) {
        return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseClock);
    }
    state->last_now_ms = now_ms;
    state->clock_seen = 1;
    if (!max_age_ms ||
        max_age_ms > state->duration_ms - FUXI_BATTERY_POLL_PAUSE_TTL_MARGIN_MS) {
        return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseTtl);
    }
    if (state->phase != FuxiBatteryPollPauseWaiting) {
        if (!freshness->channel_up) {
            return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseChannel);
        }
        if (freshness->generation != state->generation) {
            return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseGeneration);
        }
        if (max_age_ms != state->max_age_ms) {
            return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseTtl);
        }
    }
    if (state->phase == FuxiBatteryPollPauseHolding) {
        if (now_ms >= state->resume_at_ms) {
            state->phase = FuxiBatteryPollPauseDone;
            return fuxi_battery_poll_pause_result(state, 0, 1);
        }
        return fuxi_battery_poll_pause_result(state, 0, 0);
    }
    if (!freshness->channel_up) {
        return fuxi_battery_poll_pause_result(state, 0, 0);
    }
    if (!freshness->generation || freshness->generation == UINT64_MAX) {
        return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseGeneration);
    }
    (void)fuxi_battery_prep_decide(freshness, now_ms, max_age_ms, &baseline);
    if (state->phase == FuxiBatteryPollPauseWaiting) {
        if (!quiescent || (baseline.fresh_fields & required) != required) {
            return fuxi_battery_poll_pause_result(state, 0, 0);
        }
        if (state->delay_ms > UINT64_MAX - now_ms) {
            return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseOverflow);
        }
        state->pause_at_ms = now_ms + state->delay_ms;
        if (state->duration_ms > UINT64_MAX - state->pause_at_ms) {
            return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseOverflow);
        }
        state->start_before_ms = state->pause_at_ms + state->duration_ms;
        state->generation = freshness->generation;
        state->max_age_ms = max_age_ms;
        state->phase = FuxiBatteryPollPauseArmed;
    }
    if (now_ms < state->pause_at_ms) {
        return fuxi_battery_poll_pause_result(state, 0, 0);
    }
    if (now_ms >= state->start_before_ms) {
        return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseMissedWindow);
    }
    if (!quiescent) {
        return fuxi_battery_poll_pause_result(state, 0, 0);
    }
    if ((baseline.fresh_fields & required) != required) {
        return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseBaseline);
    }
    if (state->duration_ms > UINT64_MAX - now_ms) {
        return fuxi_battery_poll_pause_cancel(state, FuxiBatteryPollPauseOverflow);
    }
    state->resume_at_ms = now_ms + state->duration_ms;
    state->phase = FuxiBatteryPollPauseHolding;
    return fuxi_battery_poll_pause_result(state, 1, 0);
}

#endif
