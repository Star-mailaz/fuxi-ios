#include "fuxi_bt_clock_ledger.h"

static void retain(struct fuxi_bt_clock_ledger *ledger)
{
    ledger->retained = ledger->owned | ledger->uncertain;
}

static enum fuxi_bt_clock_status fail(struct fuxi_bt_clock_ledger *ledger,
    enum fuxi_bt_clock_status status)
{
    if (ledger->state == FUXI_BT_CLOCK_RELEASING) {
        ledger->cleanup = status;
        ledger->state = FUXI_BT_CLOCK_RETAINED;
    } else {
        if (ledger->error == FUXI_BT_CLOCK_OK) {
            ledger->error = status;
        }
        ledger->state = FUXI_BT_CLOCK_NEEDS_RELEASE;
    }
    retain(ledger);
    return status;
}

static enum fuxi_bt_clock_status budget(struct fuxi_bt_clock_ledger *ledger, uint64_t now_us)
{
    if (now_us < ledger->last_us) {
        return fail(ledger, FUXI_BT_CLOCK_TIME_REVERSED);
    }
    ledger->last_us = now_us;
    ledger->steps++;
    if (now_us - ledger->started_us >= FUXI_BT_CLOCK_TIMEOUT_US ||
        ledger->steps >= FUXI_BT_CLOCK_MAX_STEPS) {
        return fail(ledger, FUXI_BT_CLOCK_TIMEOUT);
    }
    return FUXI_BT_CLOCK_OK;
}

enum fuxi_bt_clock_status fuxi_bt_clock_ledger_begin(struct fuxi_bt_clock_ledger *ledger,
    unsigned opt_in, uint64_t now_us)
{
    if (!ledger) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    if (ledger->owned || ledger->uncertain || ledger->state == FUXI_BT_CLOCK_ACQUIRING ||
        ledger->state == FUXI_BT_CLOCK_READY || ledger->state == FUXI_BT_CLOCK_RELEASING) {
        return FUXI_BT_CLOCK_BUSY;
    }
    if (opt_in > 1) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    *ledger = (struct fuxi_bt_clock_ledger){0};
    ledger->survey_deferred = true;
    if (!opt_in) {
        ledger->state = FUXI_BT_CLOCK_DISABLED;
        return FUXI_BT_CLOCK_OFF;
    }
    ledger->state = FUXI_BT_CLOCK_ACQUIRING;
    ledger->started_us = now_us;
    ledger->last_us = now_us;
    return FUXI_BT_CLOCK_OK;
}

enum fuxi_bt_clock_status fuxi_bt_clock_ledger_tick(struct fuxi_bt_clock_ledger *ledger,
    uint64_t now_us)
{
    if (!ledger) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    if (ledger->state == FUXI_BT_CLOCK_DISABLED) {
        return FUXI_BT_CLOCK_OFF;
    }
    if (ledger->state != FUXI_BT_CLOCK_ACQUIRING && ledger->state != FUXI_BT_CLOCK_READY &&
        ledger->state != FUXI_BT_CLOCK_RELEASING) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    return budget(ledger, now_us);
}

enum fuxi_bt_clock_status fuxi_bt_clock_ledger_acquire(struct fuxi_bt_clock_ledger *ledger,
    enum fuxi_bt_clock_id clock, enum fuxi_bt_clock_acquire_result result,
    uint64_t token, uint64_t now_us)
{
    uint32_t bit;
    enum fuxi_bt_clock_status status;
    if (!ledger || (unsigned)clock >= FUXI_BT_CLOCK_COUNT ||
        (unsigned)result > FUXI_BT_CLOCK_ACQUIRE_AMBIGUOUS) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    if (ledger->state == FUXI_BT_CLOCK_DISABLED) {
        return FUXI_BT_CLOCK_OFF;
    }
    bit = 1u << (unsigned)clock;
    if (ledger->state != FUXI_BT_CLOCK_ACQUIRING || (ledger->attempted & bit)) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    ledger->attempted |= bit;
    ledger->tokens[(unsigned)clock] = token;
    if (result == FUXI_BT_CLOCK_ACQUIRED || result == FUXI_BT_CLOCK_ACQUIRE_FAILED_HELD) {
        ledger->acquired |= bit;
        ledger->owned |= bit;
        ledger->order[ledger->order_count++] = clock;
        if (!token) {
            ledger->uncertain |= bit;
        }
    } else if (result == FUXI_BT_CLOCK_ACQUIRE_AMBIGUOUS || token) {
        ledger->uncertain |= bit;
    }
    retain(ledger);
    status = budget(ledger, now_us);
    if (status != FUXI_BT_CLOCK_OK) {
        return status;
    }
    if (ledger->uncertain) {
        return fail(ledger, FUXI_BT_CLOCK_DEFER);
    }
    if (result != FUXI_BT_CLOCK_ACQUIRED) {
        return fail(ledger, FUXI_BT_CLOCK_IO);
    }
    if (ledger->owned == FUXI_BT_CLOCK_ALL) {
        ledger->state = FUXI_BT_CLOCK_READY;
    }
    return FUXI_BT_CLOCK_OK;
}

enum fuxi_bt_clock_status fuxi_bt_clock_ledger_survey(struct fuxi_bt_clock_ledger *ledger)
{
    if (!ledger) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    if (ledger->state == FUXI_BT_CLOCK_DISABLED) {
        return FUXI_BT_CLOCK_OFF;
    }
    ledger->survey_deferred = true;
    return FUXI_BT_CLOCK_DEFER;
}

enum fuxi_bt_clock_status fuxi_bt_clock_ledger_release_begin(struct fuxi_bt_clock_ledger *ledger,
    uint64_t now_us)
{
    if (!ledger) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    if (ledger->state == FUXI_BT_CLOCK_DISABLED) {
        return FUXI_BT_CLOCK_OFF;
    }
    if (ledger->state == FUXI_BT_CLOCK_CLOSED) {
        return FUXI_BT_CLOCK_OK;
    }
    if (ledger->state != FUXI_BT_CLOCK_ACQUIRING && ledger->state != FUXI_BT_CLOCK_READY &&
        ledger->state != FUXI_BT_CLOCK_NEEDS_RELEASE) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    if (ledger->uncertain || now_us < ledger->last_us) {
        ledger->cleanup = ledger->uncertain ? FUXI_BT_CLOCK_DEFER : FUXI_BT_CLOCK_TIME_REVERSED;
        ledger->state = FUXI_BT_CLOCK_RETAINED;
        retain(ledger);
        return ledger->cleanup;
    }
    ledger->state = FUXI_BT_CLOCK_RELEASING;
    ledger->started_us = now_us;
    ledger->last_us = now_us;
    ledger->steps = 0;
    if (!ledger->owned) {
        ledger->state = FUXI_BT_CLOCK_CLOSED;
        ledger->release_complete = true;
    }
    return FUXI_BT_CLOCK_OK;
}

enum fuxi_bt_clock_status fuxi_bt_clock_ledger_next_release(const struct fuxi_bt_clock_ledger *ledger,
    enum fuxi_bt_clock_id *clock, uint64_t *token)
{
    if (!ledger || !clock || !token) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    *clock = (enum fuxi_bt_clock_id)FUXI_BT_CLOCK_COUNT;
    *token = 0;
    if (ledger->state == FUXI_BT_CLOCK_CLOSED) {
        return FUXI_BT_CLOCK_OK;
    }
    if (ledger->state != FUXI_BT_CLOCK_RELEASING || ledger->uncertain) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    for (unsigned index = ledger->order_count; index; index--) {
        enum fuxi_bt_clock_id candidate = ledger->order[index - 1];
        if (ledger->owned & (1u << (unsigned)candidate)) {
            *clock = candidate;
            *token = ledger->tokens[(unsigned)candidate];
            return FUXI_BT_CLOCK_AGAIN;
        }
    }
    return FUXI_BT_CLOCK_ARGUMENT;
}

enum fuxi_bt_clock_status fuxi_bt_clock_ledger_release(struct fuxi_bt_clock_ledger *ledger,
    enum fuxi_bt_clock_id clock, enum fuxi_bt_clock_release_result result, uint64_t now_us)
{
    enum fuxi_bt_clock_id expected;
    uint64_t token;
    uint32_t bit;
    enum fuxi_bt_clock_status status;
    if (!ledger || (unsigned)clock >= FUXI_BT_CLOCK_COUNT ||
        (unsigned)result > FUXI_BT_CLOCK_RELEASE_AMBIGUOUS) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    if (fuxi_bt_clock_ledger_next_release(ledger, &expected, &token) != FUXI_BT_CLOCK_AGAIN ||
        clock != expected) {
        return FUXI_BT_CLOCK_ARGUMENT;
    }
    bit = 1u << (unsigned)clock;
    if (result == FUXI_BT_CLOCK_RELEASED) {
        ledger->owned &= ~bit;
        ledger->released |= bit;
        ledger->tokens[(unsigned)clock] = 0;
    } else if (result == FUXI_BT_CLOCK_RELEASE_AMBIGUOUS) {
        ledger->uncertain |= bit;
    }
    retain(ledger);
    status = budget(ledger, now_us);
    if (status != FUXI_BT_CLOCK_OK) {
        return status;
    }
    if (result != FUXI_BT_CLOCK_RELEASED) {
        return fail(ledger, result == FUXI_BT_CLOCK_RELEASE_AMBIGUOUS ? FUXI_BT_CLOCK_DEFER : FUXI_BT_CLOCK_IO);
    }
    if (!ledger->owned) {
        ledger->state = FUXI_BT_CLOCK_CLOSED;
        ledger->release_complete = true;
    }
    return FUXI_BT_CLOCK_OK;
}
