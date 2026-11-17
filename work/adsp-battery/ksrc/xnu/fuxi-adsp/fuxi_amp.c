/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* FUXI speaker amplifiers: two Cirrus CS35L41 on QUP2 SE0 I2C (live DT i2c@880000: cs35l41@40 "B", reset GPIO 183; cs35l41@42
 * "T", reset GPIO 182, both active low; pins gpio0 SDA / gpio1 SCL, function 2 = qup2_se0_l0/l1_mirb, 2 mA, pull-up; engine SPI
 * 373, level). Boot argument fuxiamp, or ADT /chosen u32 "fuxi,amp" (the command line is full):
 *   1  survey, reads only: the GCC votes 0x52008 / 0x52010 / 0x52018, the five QUP2 branches (core 0x233d4, s_ahb 0x233d0, m_ahb
 *      0x233cc, core_2x 0x23004, s0 0x1e004; gcc-sm8550.c), the SE0 clock source 0x1e010 (DFS state, which level is 19.2 MHz) and
 *      the four pins; only when all five branches run, also the engine: protocol, FIFO lock (GENI_IF_DISABLE bit 0 set means the
 *      engine is GSI only, as touch's QUP1 SE4 is), clock configuration, SCL counters and FIFO depths.
 *   2  brings the bus up as UniXNU-sheng AudioProbe.cpp setupClocks / setupPins / setupBus do for this same engine on sheng
 *      (6880068): GPLL0 and the five QUP2 votes, the I2C pins, the engine at 400 kHz from the 19.2 MHz DFS level if the boot stages
 *      left it unconfigured, FIFO mode (GeniI2c.c, sheng's, unchanged); SPI 373 is masked in the distributor first (no handler
 *      here, every transfer is polled). Then each amplifier comes out of reset (its eGPIO taken from the LPASS island, low 2 ms,
 *      high, 10 ms for its OTP boot; the pad's input is logged low and high) and DEVID
 *      0x0 (0x35a40 expected), REVID 0x4, IRQ1_STATUS3 0x10018 and IRQ1_STATUS4 0x1001c (OTP boot error / done) are read. Nothing
 *      is written to the amplifiers. At the end both are held in reset again and the pins and votes go back to what they were.
 * Facts: QUP2 SE0 window 0x880000 + 0x4000, GCC 0x100000, TLMM 0xf100000 (0x1000 per pin: ctl, io at +4), GICD 0x17100000.
 * Windows are mapped with kernel_map VA and pmap entries (never ml_io_map), as fuxi_adsp.c does. */
#include <pexpert/arm64/board_config.h>
#if defined(FUXI)
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <vm/vm_kern.h>
#include <vm/pmap.h>
#include "GeniI2c.h"

extern kern_return_t pmap_enter_options_addr(pmap_t, vm_map_offset_t, uint64_t, vm_prot_t, vm_prot_t, unsigned, boolean_t,
    unsigned, void *);
extern kern_return_t kernel_thread_start(thread_continue_t, void *, thread_t *);
extern kern_return_t thread_terminate(thread_t);
extern void thread_deallocate(thread_t);
extern void IOSleep(unsigned milliseconds);
void fuxi_amp_init(void);

#define FM_GCC 0x100000ull
#define FM_TLMM 0xf100000ull
#define FM_SE 0x880000ull
#define FM_GICD 0x17100000ull
#define FM_INTID_SE (32u + 373u)
#define FM_VOTE1 0x52008u
#define FM_VOTE2 0x52010u
#define FM_VOTE2_BITS 0x1fu        /* wrap2 core 0, s_ahb 1, m_ahb 2, core_2x 3, s0 4 */
#define FM_GPLL0_VOTE 0x52018u     /* bit 0 */
#define FM_GPLL0_MODE 0x0u         /* bit 31 lock detect */
#define FM_RCG 0x1e010u            /* gcc_qupv3_wrap2_s0_clk_src */
#define FM_CLK_OFF (1u << 31)
#define FM_SCL_COUNTERS (5u << 20 | 11u << 10 | 22u) /* 400 kHz from 19.2 MHz (i2c-qcom-geni.c): high 5, low 11, cycle 22 */
#define FM_CLK_CFG (2u << 4 | 1u)                     /* divider 2, enable */
#define FM_DEVID 0x35a40u
/* GPIO 182/183 are eGPIOs (pinctrl-sm8550.c: egpio_present bit 11, egpio_enable bit 12, egpio_func 9). The boot stages leave them
 * at 0x801: present, enable clear = the LPASS island TLMM owns the pad, so the APPS io register drives nothing. pinctrl-msm sets
 * enable whenever it muxes a non-egpio function (the DT's cirrus_reset_default: gpio, output-high, 16 mA, no bias). amp2 (ksrc
 * 417dcf3) wrote 1 << 9 alone, kept the island as owner, and both amplifiers stayed in reset: NACK at 0x40 and 0x42. */
#define FM_EGPIO_PRESENT (1u << 11)
#define FM_EGPIO_ENABLE (1u << 12)
#define FM_RESET_CTL (1u << 9 | 7u << 6)  /* GPIO, output enabled, 16 mA, no pull */

static const uint32_t kHalts[5] = {0x233d4u, 0x233d0u, 0x233ccu, 0x23004u, 0x1e004u};
static const unsigned kPins[4] = {0, 1, 183, 182};    /* SDA, SCL, reset B, reset T */
static const uint8_t kAddr[2] = {0x40, 0x42};
static const unsigned kReset[2] = {183, 182};
static const char kName[2] = {'B', 'T'};

/* ---- MMIO windows (16 KiB pages) ---- */
struct fm_window { uint64_t pa; vm_size_t size; vm_offset_t va; };
static struct fm_window gGcc0 = {FM_GCC, 0x4000, 0}, gGcc1c = {FM_GCC + 0x1c000, 0x4000, 0}, gGcc20 = {FM_GCC + 0x20000, 0x4000, 0},
    gGcc50 = {FM_GCC + 0x50000, 0x4000, 0}, gSe = {FM_SE, 0x4000, 0}, gGicd = {FM_GICD, 0x4000, 0};
static struct fm_window gPin[4];

static kern_return_t fm_map(struct fm_window *w)
{
    vm_offset_t va = 0;
    if (w->va) return KERN_SUCCESS;
    if (!w->size || (w->pa & PAGE_MASK) || (w->size & PAGE_MASK)) return KERN_INVALID_ARGUMENT;
    kern_return_t kr = kmem_alloc(kernel_map, &va, w->size, KMA_VAONLY | KMA_KOBJECT | KMA_NOPAGEWAIT, VM_KERN_MEMORY_IOKIT);
    if (kr != KERN_SUCCESS) return kr;
    for (vm_size_t off = 0; off < w->size; off += PAGE_SIZE) {
        kr = pmap_enter_options_addr(kernel_pmap, va + off, w->pa + off, VM_PROT_READ | VM_PROT_WRITE, VM_PROT_NONE, VM_WIMG_IO, TRUE,
            PMAP_OPTIONS_NOWAIT, NULL);
        if (kr != KERN_SUCCESS) {
            pmap_remove(kernel_pmap, va, va + w->size);
            return kr; /* VA kept reserved, as in fuxi_adsp.c */
        }
    }
    w->va = va;
    return KERN_SUCCESS;
}
static uint32_t rd(const struct fm_window *w, uint64_t pa) { return *(volatile uint32_t *)(w->va + (pa - w->pa)); }
static void wr(const struct fm_window *w, uint64_t pa, uint32_t value)
{
    *(volatile uint32_t *)(w->va + (pa - w->pa)) = value;
    __asm__ volatile("dsb sy" ::: "memory");
}
/* A GCC register by its offset from the GCC base. */
static const struct fm_window *gccWin(uint32_t off)
{
    const uint64_t pa = FM_GCC + off;
    const struct fm_window *w[4] = {&gGcc0, &gGcc1c, &gGcc20, &gGcc50};
    for (unsigned i = 0; i < 4; ++i) if (pa >= w[i]->pa && pa + 4 <= w[i]->pa + w[i]->size) return w[i];
    return NULL;
}
static uint32_t gcc(uint32_t off) { return rd(gccWin(off), FM_GCC + off); }
static void gccWr(uint32_t off, uint32_t value) { wr(gccWin(off), FM_GCC + off, value); }
static uint64_t pinPa(unsigned gpio) { return FM_TLMM + (uint64_t)gpio * 0x1000u; }
static uint32_t pinCtl(unsigned i) { return rd(&gPin[i], pinPa(kPins[i])); }
static uint32_t pinIo(unsigned i) { return rd(&gPin[i], pinPa(kPins[i]) + 4); }
static unsigned pinIndex(unsigned gpio) { for (unsigned i = 0; i < 4; ++i) if (kPins[i] == gpio) return i; return 0; }

/* ---- clocks ---- */
/* sheng's test: a branch is running unless it reports CLK_OFF without being under hardware control (bit 1). */
static int branchesRun(uint32_t *mask)
{
    int ok = 1;
    uint32_t off = 0;
    for (unsigned i = 0; i < 5; ++i) {
        const uint32_t v = gcc(kHalts[i]);
        if ((v & FM_CLK_OFF) && !(v & 2u)) { ok = 0; off |= 1u << i; }
    }
    if (mask) *mask = off;
    return ok;
}
/* The DFS level of the SE0 clock source that runs at 19.2 MHz (TCXO, no divider, no M/N), or -1. */
static int level19m2(void)
{
    for (unsigned l = 0; l < 8; ++l) {
        const uint32_t cfg = gcc(FM_RCG + 0x1c + 4 * l);
        const unsigned src = (cfg >> 8) & 7, mode = (cfg >> 12) & 3, hid = cfg & 0x1f;
        if (src == 0 && mode == 0 && hid <= 1) return (int)l; /* hid 0 or 1: divide by 1 */
    }
    return -1;
}

/* ---- the GIC: SPI 373 masked (polled engine, no handler in this kernel owns the line) ---- */
static void gicMask(unsigned intid)
{
    wr(&gGicd, FM_GICD + 0x180 + (intid / 32) * 4, 1u << (intid % 32));
    for (unsigned n = 0; (rd(&gGicd, FM_GICD) & 0x80000000u) && n < 100000; n++) delay(1); /* GICD_CTLR.RWP */
}
static int gicEnabled(unsigned intid) { return (rd(&gGicd, FM_GICD + 0x100 + (intid / 32) * 4) >> (intid % 32)) & 1; }

/* ---- the engine ---- */
static uint32_t ioRd(void *ctx, uint32_t reg) { (void)ctx; return rd(&gSe, FM_SE + reg); }
static void ioWr(void *ctx, uint32_t reg, uint32_t value) { (void)ctx; wr(&gSe, FM_SE + reg, value); }
static GeniI2c gBus;

/* One register read on the bus (32-bit address, 32-bit data, both big-endian on the wire): 1 and *value, or 0. Polled in 20 us steps,
 * 20 ms per stage of GeniI2c's cancel/abort ladder, as sheng's transfer(). */
static int ampRead(uint8_t address, uint32_t reg, uint32_t *value)
{
    const uint8_t bytes[4] = {(uint8_t)(reg >> 24), (uint8_t)(reg >> 16), (uint8_t)(reg >> 8), (uint8_t)reg};
    gBus.address = address;
    if (geni_i2c_start_read_bytes(&gBus, bytes, 4, 4)) return 0;
    for (int stages = 3; stages > 0;) {
        for (unsigned i = 0; i < 1000; ++i) {
            const int r = geni_i2c_poll(&gBus);
            if (r == GeniDone) { *value = __builtin_bswap32(gBus.rx); return 1; }
            if (r == GeniFailed) return 0;
            delay(20);
        }
        if (geni_i2c_timeout(&gBus) != GeniPending) return 0;
        --stages;
    }
    return 0;
}

/* The survey reads the engine only with every branch plainly on (CLK_OFF clear, hardware control or not): a read of an unclocked
 * block stalls the bus. */
static int branchesOn(void)
{
    for (unsigned i = 0; i < 5; ++i) if (gcc(kHalts[i]) & FM_CLK_OFF) return 0;
    return 1;
}

static void survey(int *running)
{
    uint32_t off = 0;
    const int run = branchesRun(&off) && branchesOn();
    const int level = level19m2();
    printf("FUXI AMP: survey vote 0x52008=%#x 0x52010=%#x gpll0=%#x/%#x branches core=%#x s_ahb=%#x m_ahb=%#x core2x=%#x s0=%#x "
        "(off mask %#x) rcg cmd=%#x dfsr=%#x level19.2=%d gic_se_en=%d\n", gcc(FM_VOTE1), gcc(FM_VOTE2), gcc(FM_GPLL0_VOTE),
        gcc(FM_GPLL0_MODE), gcc(kHalts[0]), gcc(kHalts[1]), gcc(kHalts[2]), gcc(kHalts[3]), gcc(kHalts[4]), off, gcc(FM_RCG),
        gcc(FM_RCG + 0x14), level, gicEnabled(FM_INTID_SE));
    printf("FUXI AMP: pins gpio0 %#x/%#x gpio1 %#x/%#x gpio183 %#x/%#x gpio182 %#x/%#x (ctl/io)\n", pinCtl(0), pinIo(0), pinCtl(1),
        pinIo(1), pinCtl(2), pinIo(2), pinCtl(3), pinIo(3));
    if (run) {
        printf("FUXI AMP: engine fw=%#x proto=%u if_disable=%#x (%s) clk_cfg=%#x clk_sel=%#x scl=%#x hw0=%#x hw1=%#x m_irq=%#x/%#x\n",
            ioRd(NULL, GENI_FW_REVISION), (ioRd(NULL, GENI_FW_REVISION) >> 8) & 0xff, ioRd(NULL, GENI_IF_DISABLE),
            (ioRd(NULL, GENI_IF_DISABLE) & 1u) ? "FIFO locked: GSI only" : "FIFO usable", ioRd(NULL, GENI_CLK_CFG), ioRd(NULL, 0x7c),
            ioRd(NULL, GENI_SCL_COUNTERS), ioRd(NULL, GENI_HW_PARAM_0), ioRd(NULL, GENI_HW_PARAM_1), ioRd(NULL, GENI_M_IRQ_STATUS),
            ioRd(NULL, GENI_M_IRQ_EN));
    } else {
        printf("FUXI AMP: engine not read: QUP2 clocks off\n");
    }
    *running = run;
}

/* Mode 2. Saved state is put back on every exit path. */
static void bringUp(int wasRunning)
{
    uint32_t savedCtl[4], savedIo[4];
    for (unsigned i = 0; i < 4; ++i) { savedCtl[i] = pinCtl(i); savedIo[i] = pinIo(i); }
    const uint32_t savedVote2 = gcc(FM_VOTE2), savedGpll0 = gcc(FM_GPLL0_VOTE);
    int bus = 0, step = 0;
    uint32_t config = 0;

    /* clocks */
    gccWr(FM_GPLL0_VOTE, savedGpll0 | 1u);
    for (unsigned i = 0; i < 10000 && !(gcc(FM_GPLL0_MODE) & FM_CLK_OFF); ++i) delay(10); /* bit 31: lock detect */
    gccWr(FM_VOTE2, savedVote2 | FM_VOTE2_BITS);
    int run = 0;
    for (unsigned i = 0; i < 2000 && !(run = branchesRun(NULL)); ++i) delay(10);
    step = 1;
    if (!run) goto out; /* never touch an engine without running clocks */

    /* pins: I2C function 2, 2 mA, pull-up (DT active state) */
    for (unsigned i = 0; i < 2; ++i) wr(&gPin[i], pinPa(kPins[i]), 2u << 2 | 0u << 6 | 3u);
    step = 2;

    /* the engine */
    const uint32_t proto = (ioRd(NULL, GENI_FW_REVISION) >> 8) & 0xff;
    if (proto != GENI_PROTO_I2C) goto out;
    step = 3;
    if (!(ioRd(NULL, GENI_CLK_CFG) & 1u) || !ioRd(NULL, GENI_SCL_COUNTERS)) {
        const int level = level19m2();
        if (level < 0) goto out;
        ioWr(NULL, 0x28, ioRd(NULL, 0x28) | 0x7fu);   /* clock gating controls on */
        ioWr(NULL, 0xe30, ioRd(NULL, 0xe30) | 0xfu);  /* DMA clock gating controls on */
        ioWr(NULL, 0x24, 0x7fu);                      /* default output control */
        ioWr(NULL, 0x20, 1u);                         /* force default */
        ioWr(NULL, 0xe18, 0);                         /* no GSI events */
        ioWr(NULL, 0x7c, (uint32_t)level);
        ioWr(NULL, GENI_CLK_CFG, FM_CLK_CFG);
        ioWr(NULL, GENI_SCL_COUNTERS, FM_SCL_COUNTERS);
    }
    step = 4;
    gicMask(FM_INTID_SE);
    if (gicEnabled(FM_INTID_SE)) goto out;
    const GeniIo io = {ioRd, ioWr, NULL};
    if (geni_i2c_prepare(&gBus, &io, kAddr[0], &config)) goto out; /* also refuses a GSI-only engine */
    bus = 1;
    step = 5;

    /* the amplifiers, one at a time */
    for (unsigned a = 0; a < 2; ++a) {
        const unsigned p = pinIndex(kReset[a]);
        const uint32_t egpio = (savedCtl[p] & FM_EGPIO_PRESENT) ? FM_EGPIO_ENABLE : 0;
        wr(&gPin[p], pinPa(kReset[a]) + 4, 0);           /* output low */
        wr(&gPin[p], pinPa(kReset[a]), egpio | FM_RESET_CTL); /* APPS takes the pad (eGPIO), GPIO out, 16 mA */
        IOSleep(2);
        const uint32_t ctlNow = pinCtl(p), lowIn = pinIo(p) & 1u;
        wr(&gPin[p], pinPa(kReset[a]) + 4, 1u << 1);     /* release */
        IOSleep(10);
        const uint32_t highIn = pinIo(p) & 1u;
        uint32_t devid = 0, revid = 0, st3 = 0, st4 = 0;
        const int ok = ampRead(kAddr[a], 0x0, &devid);
        const int ok2 = ok && ampRead(kAddr[a], 0x4, &revid) && ampRead(kAddr[a], 0x10018, &st3) && ampRead(kAddr[a], 0x1001c, &st4);
        printf("FUXI AMP: amp %c@%#x %s devid=%#x%s revid=%#x irq1_status3=%#x irq1_status4=%#x (geni error %u status %#x done %u "
            "failed %u timeouts %u; reset gpio%u ctl %#x in low/high %u/%u)\n", kName[a], kAddr[a], ok2 ? "answers" : ok ? "partly" :
            "no answer", devid, devid == FM_DEVID ? " (CS35L41)" : "", revid, st3, st4, gBus.error, gBus.error_status, gBus.done,
            gBus.failed, gBus.timeouts, kReset[a], ctlNow, lowIn, highIn);
        wr(&gPin[p], pinPa(kReset[a]) + 4, 0);           /* back into reset */
    }
    step = 6;
out:
    /* Put back what the boot stages left: reset pins first (still low while their old configuration returns), then the I2C pins and
     * the votes. A clock the boot stages had running stays running. */
    for (unsigned i = 0; i < 4; ++i) {
        wr(&gPin[i], pinPa(kPins[i]) + 4, savedIo[i] & ~1u);
        wr(&gPin[i], pinPa(kPins[i]), savedCtl[i]);
    }
    if (!wasRunning) {
        gccWr(FM_VOTE2, savedVote2);
        gccWr(FM_GPLL0_VOTE, savedGpll0);
    }
    printf("FUXI AMP: bring-up stopped at step %d (6 = both read; bus %s, config %#x); pins%s restored\n", step,
        bus ? "prepared" : "not prepared", config, wasRunning ? "" : " and votes");
}

/* Boot argument fuxiamp, else ADT /chosen u32 "fuxi,amp". */
static unsigned fm_mode(void)
{
    unsigned mode = 0;
    DTEntry chosen;
    const void *prop;
    unsigned bytes;
    if (PE_parse_boot_argn("fuxiamp", &mode, sizeof(mode))) return mode;
    if (SecureDTLookupEntry(NULL, "/chosen", &chosen) == kSuccess &&
        SecureDTGetProperty(chosen, "fuxi,amp", &prop, &bytes) == kSuccess && bytes == sizeof(uint32_t))
        memcpy(&mode, prop, sizeof(mode));
    return mode;
}

static void ampThread(void *arg, wait_result_t result)
{
    (void)result;
    const unsigned mode = (unsigned)(uintptr_t)arg;
    int ok = fm_map(&gGcc0) == KERN_SUCCESS && fm_map(&gGcc1c) == KERN_SUCCESS && fm_map(&gGcc20) == KERN_SUCCESS &&
        fm_map(&gGcc50) == KERN_SUCCESS && fm_map(&gSe) == KERN_SUCCESS && fm_map(&gGicd) == KERN_SUCCESS;
    for (unsigned i = 0; ok && i < 4; ++i) {
        gPin[i].pa = pinPa(kPins[i]) & ~(uint64_t)0x3fffu;
        gPin[i].size = 0x4000;
        for (unsigned j = 0; j < i; ++j) if (gPin[j].pa == gPin[i].pa) gPin[i].va = gPin[j].va; /* gpio0 and gpio1 share a page */
        ok = fm_map(&gPin[i]) == KERN_SUCCESS;
    }
    if (!ok) {
        printf("FUXI AMP: mapping failed\n");
    } else {
        int running = 0;
        survey(&running);
        if (mode >= 2) bringUp(running);
    }
    thread_terminate(current_thread());
}

/* Called from fuxi_adsp_init (sweet_ufs.c, after the UFS driver is ready). */
void fuxi_amp_init(void)
{
    static int started;
    thread_t thread = NULL;
    const unsigned mode = fm_mode();
    if (!mode || started) return;
    started = 1;
    if (kernel_thread_start(ampThread, (void *)(uintptr_t)(mode > 2 ? 2 : mode), &thread) != KERN_SUCCESS) {
        printf("FUXI AMP: no thread\n");
        return;
    }
    thread_deallocate(thread);
    printf("FUXI AMP: started mode %u\n", mode > 2 ? 2 : mode);
}
#endif /* FUXI */
