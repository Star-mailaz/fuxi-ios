#include <pexpert/arm64/board_config.h>
#if defined(FUXI)
#include <sys/param.h>
#include <sys/systm.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <vm/vm_kern.h>
#include <vm/pmap.h>
#include <string.h>
#include "fuxi_bt.h"
#include "fuxi_bt_board.h"

extern kern_return_t pmap_enter_options_addr(pmap_t, vm_map_offset_t,
    uint64_t, vm_prot_t, vm_prot_t, unsigned, boolean_t, unsigned, void *);
extern unsigned fuxi_gpu_access(uintptr_t, uint64_t *, unsigned, unsigned);
extern kern_return_t kernel_thread_start(thread_continue_t, void *, thread_t *);
extern kern_return_t thread_terminate(thread_t);
extern void thread_deallocate(thread_t);

struct fuxi_bt_window {
    uint64_t pa;
    vm_size_t size;
    vm_offset_t va;
};

static struct fuxi_bt_window fuxi_bt_windows[] = {
    {0x11c000, 0x4000, 0},
    {0x120000, 0x4000, 0},
    {0x150000, 0x4000, 0},
    {0xf14c000, 0x8000, 0},
    {FUXI_BT_UART_BASE, 0x4000, 0},
    {FUXI_BT_WRAPPER_BASE, 0x4000, 0},
    {FUXI_BT_GCC_BASE, 0x4000, 0} /* GPLL0 MODE／USER_CTL（fuxi,bt=3） */
};
static struct fuxi_bt_board fuxi_bt_board_state;
static struct fuxi_bt_uart_ops fuxi_bt_uart;
static unsigned fuxi_bt_registration;
static unsigned fuxi_bt_started;
static unsigned fuxi_bt_mode;

enum fuxi_bt_status fuxi_bt_register_uart(const struct fuxi_bt_uart_ops *ops)
{
    unsigned expected = 0;
    if (!fuxi_bt_uart_ops_valid(ops)) {
        return FUXI_BT_ARGUMENT;
    }
    if (!__atomic_compare_exchange_n(&fuxi_bt_registration, &expected, 1,
        false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        return FUXI_BT_BUSY;
    }
    fuxi_bt_uart = *ops;
    __atomic_store_n(&fuxi_bt_registration, 2, __ATOMIC_RELEASE);
    return FUXI_BT_OK;
}

static enum fuxi_bt_status fuxi_bt_map(struct fuxi_bt_window *window)
{
    vm_offset_t address = 0;
    kern_return_t status;
    if (window->va) {
        return FUXI_BT_OK;
    }
    if ((window->pa & PAGE_MASK) || (window->size & PAGE_MASK)) {
        return FUXI_BT_ARGUMENT;
    }
    status = kmem_alloc(kernel_map, &address, window->size,
        KMA_VAONLY | KMA_KOBJECT | KMA_NOPAGEWAIT, VM_KERN_MEMORY_IOKIT);
    if (status != KERN_SUCCESS) {
        return FUXI_BT_IO;
    }
    for (vm_size_t offset = 0; offset < window->size; offset += PAGE_SIZE) {
        status = pmap_enter_options_addr(kernel_pmap, address + offset,
            window->pa + offset, VM_PROT_READ | VM_PROT_WRITE, VM_PROT_NONE,
            VM_WIMG_IO, TRUE, PMAP_OPTIONS_NOWAIT, NULL);
        if (status != KERN_SUCCESS) {
            pmap_remove(kernel_pmap, address, address + window->size);
            kmem_free(kernel_map, address, window->size);
            return FUXI_BT_IO;
        }
    }
    window->va = address;
    return FUXI_BT_OK;
}

static void fuxi_bt_unmap(void)
{
    for (unsigned index = 0; index < sizeof(fuxi_bt_windows) / sizeof(fuxi_bt_windows[0]); index++) {
        struct fuxi_bt_window *window = &fuxi_bt_windows[index];
        if (window->va) {
            pmap_remove(kernel_pmap, window->va, window->va + window->size);
            kmem_free(kernel_map, window->va, window->size);
            window->va = 0;
        }
    }
}

static enum fuxi_bt_status fuxi_bt_read32(void *context,
    uint64_t pa, uint32_t *value)
{
    (void)context;
    if (pa & 3) {
        return FUXI_BT_ARGUMENT;
    }
    for (unsigned index = 0; index < sizeof(fuxi_bt_windows) / sizeof(fuxi_bt_windows[0]); index++) {
        struct fuxi_bt_window *window = &fuxi_bt_windows[index];
        if (pa >= window->pa && pa - window->pa <= window->size - 4) {
            uint64_t raw = 0;
            enum fuxi_bt_status status = fuxi_bt_map(window);
            if (status != FUXI_BT_OK) {
                return status;
            }
            if (fuxi_gpu_access(window->va + (uintptr_t)(pa - window->pa), &raw, 0, 0)) {
                printf("FUXI BT: read fault pa=%#llx\n", pa);
                return FUXI_BT_IO;
            }
            *value = (uint32_t)raw;
            return FUXI_BT_OK;
        }
    }
    return FUXI_BT_ARGUMENT;
}

static enum fuxi_bt_status fuxi_bt_write32(void *context,
    uint64_t pa, uint32_t value)
{
    (void)context;
    if (pa & 3) {
        return FUXI_BT_ARGUMENT;
    }
    for (unsigned index = 0; index < sizeof(fuxi_bt_windows) / sizeof(fuxi_bt_windows[0]); index++) {
        struct fuxi_bt_window *window = &fuxi_bt_windows[index];
        if (pa >= window->pa && pa - window->pa <= window->size - 4) {
            uint64_t raw = value;
            enum fuxi_bt_status status = fuxi_bt_map(window);
            if (status != FUXI_BT_OK) {
                return status;
            }
            if (fuxi_gpu_access(window->va + (uintptr_t)(pa - window->pa), &raw, 1, 0)) {
                printf("FUXI BT: write fault pa=%#llx\n", pa);
                return FUXI_BT_IO;
            }
            return FUXI_BT_OK;
        }
    }
    return FUXI_BT_ARGUMENT;
}

static uint64_t fuxi_bt_now_us(void *context)
{
    uint64_t absolute, nanoseconds;
    (void)context;
    clock_get_uptime(&absolute);
    absolutetime_to_nanoseconds(absolute, &nanoseconds);
    return nanoseconds / 1000u;
}

static void fuxi_bt_wait_us(void *context, unsigned microseconds)
{
    (void)context;
    delay((int)microseconds);
}

static void fuxi_bt_print_probe(enum fuxi_bt_status status, const struct fuxi_bt_result *result)
{
    printf("FUXI BT: probe status=%s cleanup=%s tx=%u rx=%u drained=%u frames=%u ignored=%u polls=%u elapsed_us=%llu controller_status=%#x valid=%u\n",
        fuxi_bt_status_name(status), fuxi_bt_status_name(result->cleanup),
        result->tx_bytes, result->rx_bytes, result->drained_bytes, result->frames,
        result->ignored_frames, result->polls, result->elapsed_us,
        (unsigned)result->controller_status, (unsigned)result->version_valid);
    if (result->reply_size == sizeof(result->reply)) {
        /* 原始版本回應（H4 0x04 起 21 位元組），解析有疑問時不必再跑一趟就能對照。 */
        static const char digits[] = "0123456789abcdef";
        char hex[sizeof(result->reply) * 2 + 1];
        for (unsigned index = 0; index < sizeof(result->reply); index++) {
            hex[index * 2] = digits[result->reply[index] >> 4];
            hex[index * 2 + 1] = digits[result->reply[index] & 15];
        }
        hex[sizeof(hex) - 1] = 0;
        printf("FUXI BT: reply %s\n", hex);
    }
    if (result->version_valid) {
        printf("FUXI BT: QCA version product=%#x soc=%#x rom=%#x patch=%#x\n",
            result->version.product, result->version.soc,
            (unsigned)result->version.rom, (unsigned)result->version.patch);
    }
}

/*
 * fuxi,bt=3：等 WLAN_EN 穩定拉高（WCN 電源軌由 WLAN 開好）連續 15 秒，最多等 300 秒；
 * 之後開 SE6 時脈與腳位、拉 BT_EN、以 115200 送 QCA 版本查詢，結束後全部還原。
 */
#define FUXI_BT_WLAN_STEADY_US 15000000ull
#define FUXI_BT_WLAN_DEADLINE_US 300000000ull
#define FUXI_BT_WLAN_POLL_US 250000u

static void fuxi_bt_board_session(void)
{
    const struct fuxi_bt_board_io io = {
        NULL, fuxi_bt_read32, fuxi_bt_write32, fuxi_bt_now_us, fuxi_bt_wait_us
    };
    struct fuxi_bt_board *board = &fuxi_bt_board_state;
    struct fuxi_bt_uart_ops ops;
    struct fuxi_bt_result result;
    enum fuxi_bt_status status, cleanup;
    const uint64_t start = fuxi_bt_now_us(NULL);
    uint64_t steady = 0, now = start;
    bool steady_seen = false;
    for (;;) {
        bool ready = false;
        status = fuxi_bt_board_wlan_ready(&io, &ready);
        now = fuxi_bt_now_us(NULL);
        if (status != FUXI_BT_OK) {
            printf("FUXI BT: board WLAN_EN read status=%s; BT_EN untouched\n",
                fuxi_bt_status_name(status));
            return;
        }
        if (!ready) {
            steady_seen = false;
        } else if (!steady_seen) {
            steady_seen = true;
            steady = now;
        }
        if (steady_seen && now - steady >= FUXI_BT_WLAN_STEADY_US) {
            break;
        }
        if (now - start >= FUXI_BT_WLAN_DEADLINE_US) {
            printf("FUXI BT: board WLAN_EN not steady high for 15 s within 300 s; BT_EN untouched\n");
            return;
        }
        fuxi_bt_wait_us(NULL, FUXI_BT_WLAN_POLL_US);
    }
    printf("FUXI BT: board WLAN_EN steady after %llu ms\n", (now - start) / 1000u);
    status = fuxi_bt_board_power_on(board, &io);
    printf("FUXI BT: board power status=%s stage=%s value=%#x gpll0_mode=%#x gpll0_user=%#x vote=%#x added=%#x rcg_cfg=%#x->%#x qup=%#x fw=%#x sw_ctrl=%u->%u\n",
        fuxi_bt_status_name(status), fuxi_bt_board_stage_name(board->stage),
        board->failed_value, board->gpll0_mode, board->gpll0_user, board->vote,
        board->added_votes, board->rcg_saved[0], board->rcg_cfg, board->qup_version,
        board->firmware, board->sw_ctrl_before, board->sw_ctrl_after);
    if (status == FUXI_BT_OK) {
        fuxi_bt_board_uart_ops(board, &ops);
        status = fuxi_bt_probe_run(1, &ops, &result);
        fuxi_bt_print_probe(status, &result);
        printf("FUXI BT: fifo state=%u error=%s cleanup=%s fault=%u reg=%#x%s tx=%llu/%llu rx=%llu discarded=%llu m_irq=%#x s_irq=%#x depth=%u/%u\n",
            (unsigned)board->fifo.state, fuxi_bt_status_name(board->fifo.error),
            fuxi_bt_status_name(board->fifo.cleanup), (unsigned)board->fifo.io_fault,
            board->fifo.failed_register, board->fifo.failed_write ? " write" : "",
            board->fifo.tx_accepted, board->fifo.tx_completed, board->fifo.rx_delivered,
            board->fifo.rx_discarded, board->fifo.master_irq, board->fifo.secondary_irq,
            board->fifo.tx_depth, board->fifo.rx_depth);
    }
    cleanup = fuxi_bt_board_power_off(board);
    printf("FUXI BT: board restore status=%s\n", fuxi_bt_status_name(cleanup));
}

static void fuxi_bt_worker(void *argument, wait_result_t wait_result)
{
    struct fuxi_bt_snapshot snapshot;
    enum fuxi_bt_status status;
    (void)argument;
    (void)wait_result;
    status = fuxi_bt_snapshot_read(fuxi_bt_read32, NULL, &snapshot);
    printf("FUXI BT: survey status=%s vote=%#x gpll0_vote=%#x off_mask=%#x engine_read=%u\n",
        fuxi_bt_status_name(status), snapshot.vote, snapshot.gpll0_vote,
        snapshot.off_mask, (unsigned)snapshot.engine_read);
    if (status == FUXI_BT_OK) {
        printf("FUXI BT: branches core=%#x s_ahb=%#x m_ahb=%#x core2x=%#x se6=%#x\n",
            snapshot.branches[0], snapshot.branches[1], snapshot.branches[2],
            snapshot.branches[3], snapshot.branches[4]);
        printf("FUXI BT: rcg cmd=%#x cfg=%#x m=%#x n=%#x d=%#x dfs=%#x\n",
            snapshot.rcg[0], snapshot.rcg[1], snapshot.rcg[2], snapshot.rcg[3],
            snapshot.rcg[4], snapshot.rcg[5]);
        for (unsigned index = 0; index < 8; index++) {
            printf("FUXI BT: gpio%u ctl=%#x io=%#x\n", 76 + index,
                snapshot.pin_ctl[index], snapshot.pin_io[index]);
        }
        if (snapshot.engine_read) {
            printf("FUXI BT: engine wrapper=%#x fw=%#x protocol=%u if_disable=%#x status=%#x m_irq=%#x s_irq=%#x\n",
                snapshot.wrapper_version, snapshot.firmware,
                (snapshot.firmware >> 8) & 0xff, snapshot.interface_disable,
                snapshot.engine_status, snapshot.master_irq, snapshot.secondary_irq);
        }
    }
    fuxi_bt_unmap();
    if (status == FUXI_BT_OK && fuxi_bt_mode == 2) {
        struct fuxi_bt_result result;
        const struct fuxi_bt_uart_ops *ops = NULL;
        if (__atomic_load_n(&fuxi_bt_registration, __ATOMIC_ACQUIRE) == 2) {
            ops = &fuxi_bt_uart;
        }
        status = fuxi_bt_probe_run(1, ops, &result);
        fuxi_bt_print_probe(status, &result);
    } else if (status == FUXI_BT_OK && fuxi_bt_mode == 3) {
        fuxi_bt_board_session();
        fuxi_bt_unmap();
    }
    thread_terminate(current_thread());
}

/* 命令列已滿：沒有 fuxibt 時讀 ADT /chosen 的 u32 "fuxi,bt"。 */
static int fuxi_bt_adt_mode(void)
{
    DTEntry chosen;
    const void *property = NULL;
    unsigned int bytes = 0;
    uint32_t value = 0;
    if (SecureDTLookupEntry(NULL, "/chosen", &chosen) == kSuccess &&
        SecureDTGetProperty(chosen, "fuxi,bt", &property, &bytes) == kSuccess &&
        property && bytes == sizeof(value)) {
        memcpy(&value, property, sizeof(value));
    }
    return value > 0x7fffffffu ? -1 : (int)value;
}

void fuxi_bt_init(void)
{
    int mode = 0;
    unsigned expected = 0;
    thread_t worker;
    if (!PE_parse_boot_argn("fuxibt", &mode, sizeof(mode))) {
        mode = fuxi_bt_adt_mode();
    }
    if (mode == 0) {
        return;
    }
    if (mode != 1 && mode != 2 && mode != 3) {
        printf("FUXI BT: mode %d rejected (fuxibt / fuxi,bt)\n", mode);
        return;
    }
    if (!__atomic_compare_exchange_n(&fuxi_bt_started, &expected, 1,
        false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        return;
    }
    fuxi_bt_mode = (unsigned)mode;
    if (kernel_thread_start(fuxi_bt_worker, NULL, &worker) != KERN_SUCCESS) {
        printf("FUXI BT: worker start failed\n");
        return;
    }
    thread_deallocate(worker);
}
#endif
