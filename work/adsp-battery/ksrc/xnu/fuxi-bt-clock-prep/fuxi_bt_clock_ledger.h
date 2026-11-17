#ifndef FUXI_BT_CLOCK_LEDGER_H
#define FUXI_BT_CLOCK_LEDGER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FUXI_BT_CLOCK_COUNT 5u
#define FUXI_BT_CLOCK_ALL 0x1fu
#define FUXI_BT_CLOCK_TIMEOUT_US 20000u
#define FUXI_BT_CLOCK_MAX_STEPS 32u

enum fuxi_bt_clock_id {
    FUXI_BT_CLOCK_CORE = 0,
    FUXI_BT_CLOCK_S_AHB,
    FUXI_BT_CLOCK_M_AHB,
    FUXI_BT_CLOCK_CORE_2X,
    FUXI_BT_CLOCK_SE6
};

enum fuxi_bt_clock_status {
    FUXI_BT_CLOCK_OK = 0,
    FUXI_BT_CLOCK_OFF,
    FUXI_BT_CLOCK_AGAIN,
    FUXI_BT_CLOCK_DEFER,
    FUXI_BT_CLOCK_ARGUMENT,
    FUXI_BT_CLOCK_IO,
    FUXI_BT_CLOCK_TIMEOUT,
    FUXI_BT_CLOCK_TIME_REVERSED,
    FUXI_BT_CLOCK_BUSY
};

enum fuxi_bt_clock_state {
    FUXI_BT_CLOCK_ZERO = 0,
    FUXI_BT_CLOCK_DISABLED,
    FUXI_BT_CLOCK_ACQUIRING,
    FUXI_BT_CLOCK_READY,
    FUXI_BT_CLOCK_NEEDS_RELEASE,
    FUXI_BT_CLOCK_RELEASING,
    FUXI_BT_CLOCK_CLOSED,
    FUXI_BT_CLOCK_RETAINED
};

enum fuxi_bt_clock_acquire_result {
    FUXI_BT_CLOCK_ACQUIRED = 0,
    FUXI_BT_CLOCK_ACQUIRE_FAILED_NONE,
    FUXI_BT_CLOCK_ACQUIRE_FAILED_HELD,
    FUXI_BT_CLOCK_ACQUIRE_AMBIGUOUS
};

enum fuxi_bt_clock_release_result {
    FUXI_BT_CLOCK_RELEASED = 0,
    FUXI_BT_CLOCK_RELEASE_FAILED_HELD,
    FUXI_BT_CLOCK_RELEASE_AMBIGUOUS
};

struct fuxi_bt_clock_ledger {
    enum fuxi_bt_clock_state state;
    enum fuxi_bt_clock_status error;
    enum fuxi_bt_clock_status cleanup;
    uint32_t attempted;
    uint32_t acquired;
    uint32_t owned;
    uint32_t released;
    uint32_t uncertain;
    uint32_t retained;
    uint64_t tokens[FUXI_BT_CLOCK_COUNT];
    enum fuxi_bt_clock_id order[FUXI_BT_CLOCK_COUNT];
    unsigned order_count;
    unsigned steps;
    uint64_t started_us;
    uint64_t last_us;
    bool survey_deferred;
    bool release_complete;
};

#ifdef __cplusplus
extern "C" {
#endif

enum fuxi_bt_clock_status fuxi_bt_clock_ledger_begin(struct fuxi_bt_clock_ledger *ledger,
    unsigned opt_in, uint64_t now_us);
enum fuxi_bt_clock_status fuxi_bt_clock_ledger_tick(struct fuxi_bt_clock_ledger *ledger,
    uint64_t now_us);
enum fuxi_bt_clock_status fuxi_bt_clock_ledger_acquire(struct fuxi_bt_clock_ledger *ledger,
    enum fuxi_bt_clock_id clock, enum fuxi_bt_clock_acquire_result result,
    uint64_t token, uint64_t now_us);
enum fuxi_bt_clock_status fuxi_bt_clock_ledger_survey(struct fuxi_bt_clock_ledger *ledger);
enum fuxi_bt_clock_status fuxi_bt_clock_ledger_release_begin(struct fuxi_bt_clock_ledger *ledger,
    uint64_t now_us);
enum fuxi_bt_clock_status fuxi_bt_clock_ledger_next_release(const struct fuxi_bt_clock_ledger *ledger,
    enum fuxi_bt_clock_id *clock, uint64_t *token);
enum fuxi_bt_clock_status fuxi_bt_clock_ledger_release(struct fuxi_bt_clock_ledger *ledger,
    enum fuxi_bt_clock_id clock, enum fuxi_bt_clock_release_result result, uint64_t now_us);

#ifdef __cplusplus
}
#endif

#endif
