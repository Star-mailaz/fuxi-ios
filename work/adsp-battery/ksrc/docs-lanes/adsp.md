# Audio DSP and battery manager (`fuxiadsp`)

Patch 0117 (`tools/sync-fuxi-adsp.py`, canonical sources `xnu/fuxi-adsp/`) starts the audio DSP (ADSP, LPASS) from XNU
and talks to the battery manager that runs on it. It is a port of UniXNU-sheng's `AdspProbe.cpp`, `AdspFirmware.c` and
`ShengBattery.cpp` (6880068, BSD-2-Clause-Patent; the protocol modules `Qcom*.c`, `FatVolume.c`, `ShengBattmgr.c` and
`ShengQrtr.c` are copied unchanged). sheng is the Xiaomi Pad 6S Pro, also SM8550; its DSP, battery readings, PD/PPS
charging and the GLINK/QRTR stack are verified on hardware there.

Off by default. Boot argument `fuxiadsp=N`, or the ADT `/chosen` u32 `fuxi,adsp` when the command line is full:

| N | What happens |
|---|---|
| 0 | nothing |
| 1 | survey only: maps SMEM, TCSR, IPCC, AOSS, the apps RSC and the GIC distributor, reads the SMEM partition and items, the DSP's SMP2P state, the AOSS link words, the RSC id and the GIC enables of SPI 229/5, logs one `FUXI ADSP: survey` line; writes nothing |
| 2 | also starts the DSP and brings up SMP2P, GLINK, the IPC router's service locator and the battery manager client (log only) |
| 3 | as 2, and SweetBattery publishes the battery manager's readings to powerd (phase 2) |

`fuxiadsp=2` is refused (survey only) when `fuxiwlan` is set until combined hardware validation is complete.
Both drivers now hold the same blocking mutex in `fuxi_rpmh_shared.c` for the entire RSC transaction.
An uncertain request or failed cleanup quarantines the shared RSC for the remainder of the boot.
ADSP restores its IRQ-enable bit and clears its wait mask after completion; a timeout returns an error.
The portable `fuxi_rpmh_arb.h` model remains separate from this production mutex.

## Bring-up (mode 2)

One kernel thread, started from `sweet_ufs_init` once the UFS driver is ready:

1. Firmware from `modem_a` (else `modem_b`) in place: `sweet_ufs.c` gained read-only `fuxi_ufs_part_find` /
   `fuxi_ufs_part_read` for the GPT partitions of LUNs 1-5 (LUN switched under `sweet_ufs_lock` for one READ(10) and
   restored; the FUXI SCSI policy still refuses every write and non-READ off LUN 0; refused with `fuxi_unixnu_ufs=1`).
   `fuxi_adsp_fw.c` reads the FAT16 volume and joins the split images `image/adsp_dtb.bNN` and `image/adsp.bNN`.
   Checked offline against the 2026-11-07 `modem_a` backup: both images are relocatable ELF32 that fill exactly the
   carveouts (adsp 57 load segments in 0x9ea00000 + 0x4680000, adsp_dtb 1 in 0x9e980000 + 0x80000).
2. SMP2P item 429 (ours) allocated under TCSR mutex 3, "master-kernel" entry.
3. Doorbells: SPI 229 (IPCC) and SPI 5 (RSC) are **masked** in the distributor (this kernel has no handler for them;
   sleh would EOI an ownerless level line forever); the IPCC receive register is polled instead (1 ms during bring-up,
   2 ms for 500 ms after any traffic, else 200 ms). IPCC receive enabled for LPASS signals 0/2 and AOP signal 0.
4. AOSS QMP link, `load_state adsp on`.
5. cmd-db copy, `lcx.lvl` / `lmx.lvl` proxy votes at the highest level through active TCS 1 (WLAN uses 0), completion
   polled (100 ms bound). Dropped again at the DSP's handover bit, or on any later failure.
6. PAS 36 (adsp_dtb) and PAS 1 (adsp): metadata in contiguous memory (init_image), mem_setup, segments written through a
   write-combined window that is unmapped (PTEs removed, VA kept) before auth_and_reset. Ready (slave-kernel bit 1)
   within 5 s, else shutdown + crash reason from SMEM item 423.
7. GLINK items 478/479 (ours) and 480 (the DSP's), version handshake; channels `IPCRTR` (service locator) and
   `PMIC_RTR_ADSP_APPS` (battery manager).

## Battery manager client (phase 1: read and log)

`fuxi_adsp_battery.c` runs ShengBattmgr's cycle (one request in flight, 2 s per request, a refresh every 60 s and at
each notification) in a thread call and logs each finished cycle as `FUXI BATTERY: percent=... mV=... mA=... temp=...`
(the first three and every tenth also as `FUXI BATTERY: raw ...`). With mode 2 nothing is published to powerd:
SweetBattery keeps its 100 % default, so the Fuxi readings can be checked against Android first (single cell; sheng adds
two gauges, and ShengBattmgr falls back to the battery's capacity property when the gauge pair does not answer).

## Phase 2: SweetBattery from the DSP (mode 3)

`iokit/Kernel/arm/SweetBattery.cpp` (0062) gains a third source (`xnu/fuxi-adsp/SweetBattery.cpp`, carried by 0117;
`bsd/dev/fuxi_adsp_battery.h` is the shared plain-data reading). With `fuxiadsp=3` it starts its timer even without
`sweetbattery=1`, polls every 10 s until the first reading and every 30 s after, and publishes the latest plausible
reading: charge known, 2.5-4.8 V when the voltage was read, the percentage at least 1 (a misread 0 must not make iOS shut
down; the PMIC cuts off an empty cell by itself), never a critical level, mAh against the reported full / design
capacity (4500 mAh when not reported), the charger state only when known (an unknown state never publishes a
disconnect), temperature when valid, cycles, time remaining. Until a reading exists, and with modes 0-2, the source
behaves exactly as before. Log: `FUXI BATTERY: first reading for SweetBattery: N%`, then
`SWEET BATTERY: ADSP battery manager, N% ...` once.

## Log lines

- `FUXI ADSP: survey items=... slave-kernel=... aoss=... rsc_drv=... gic_ipcc_en=... gic_rsc_en=...`
- `FUXI UFS: firmware partition "modem_a" on LUN n ...`, `FUXI ADSP: firmware volume ...`, `FUXI ADSP: firmware adsp ...`
- `FUXI ADSP: aoss load_state adsp on`, `cmd-db lcx.lvl ...`, `rpmh vote lcx=.. lmx=.. done=1`
- `FUXI ADSP: adsp_dtb authenticated and started`, `adsp authenticated and reset; waiting for ready`, `ready after N ms`
- `FUXI ADSP: glink version agreed`, `channel IPCRTR up`, `channel PMIC_RTR_ADSP_APPS up`
- `FUXI ADSP: failed at stage S error E (scm x0=.. x1=..)`: S is the step (3 firmware, 4 SMP2P, 5 doorbells, 6 AOSS,
  7 rails, 8 adsp_dtb, 9 load, 10 auth_and_reset, 11 ready, 12 GLINK)
- `FUXI ADSP: stage=... ipcc=... glink in=.. out=.. qrtr ...` every 30 s ten times, then every 10 min

## Speaker amplifiers (`fuxiamp`, first step of sound)

`fuxi_amp.c` (also in 0117, with UniXNU-sheng's `GeniI2c.c` unchanged) looks at the two CS35L41 amplifiers on QUP2 SE0
I2C. It does not need the DSP. Boot argument `fuxiamp=N` or ADT `/chosen` u32 `fuxi,amp`; started from `fuxi_adsp_init`
with its own switch.

Board facts (live DT): `i2c@880000` (QUP2 SE0, SPI 373), `cs35l41@40` "B" reset GPIO 183 and `cs35l41@42` "T" reset GPIO
182 (active low), SDA gpio0 / SCL gpio1 = function 2 `qup2_se0_l0/l1_mirb` (pinctrl-sm8550.c), 2 mA, pull-up. The
node has `dmas`; whether the engine is FIFO-capable or GSI-only (as touch's QUP1 SE4 is) is what mode 1 reads.
gcc-sm8550.c: votes 0x52010 bits 0-4 (wrap2 core, s_ahb, m_ahb, core_2x, s0), halts 0x233d4 / 0x233d0 / 0x233cc /
0x23004 / 0x1e004, SE0 clock source 0x1e010 (DFS). sheng runs its amplifier bus 2 on this same engine and pins.

| N | What happens |
|---|---|
| 1 | reads only: votes, GPLL0, the five QUP2 branches, the SE0 DFS state and its 19.2 MHz level, the four pins (ctl/io), the GIC enable of SPI 373; the engine (protocol, `GENI_IF_DISABLE` bit 0 = FIFO locked, clock config, SCL counters, FIFO depths, M_IRQ) only when all five branches read plainly on |
| 2 | sheng's setupClocks / setupPins / setupBus (GPLL0 + QUP2 votes, I2C pins, engine at 400 kHz from the 19.2 MHz level when unconfigured, FIFO mode), SPI 373 masked first, then per amplifier: reset low 2 ms, high, 10 ms, read DEVID (0x35a40), REVID, IRQ1_STATUS3/4 (OTP boot), back into reset. Nothing is written to the amplifiers; pins and votes are restored |

Log: `FUXI AMP: survey ...`, `FUXI AMP: pins ...`, `FUXI AMP: engine ...` (or `not read: QUP2 clocks off`), then for mode 2
`FUXI AMP: amp B@0x40 answers devid=0x35a40 (CS35L41) ...` and `FUXI AMP: bring-up stopped at step 6 ...`. Step numbers:
1 clocks did not run, 2 pins set, 3 engine is not I2C, 4 no 19.2 MHz level / engine programmed, 5 GIC mask or FIFO refused
(GSI only), 6 both amplifiers read.

## Flash and haptics PMIC

`fuxipmic=N`, or ADT `/chosen` u32 `fuxi,pmic`, is independent of the DSP switch and defaults to off.
Mode 1 only reads the v7 observer channels. Hardware run `native-hw000provider-ram9g-pmic-boot-1`
identified flash SID 1/0xee00, APID 591 owned by EE 0, type 0x18/subtype 7 (four channels);
haptics configuration/pattern SID 7/0xf000 and 0xf100 are APIDs 631/632 owned by EE 0.
The haptics boost at 0xf200 is APID 556 owned by EE 3; no ownership change or boost write is attempted.

Mode 2 also requests one flash-channel-0 torch pulse: 40 mA, 80 ms, with a 100 ms hardware timer
programmed and read back before enabling. It refuses an active module, active channels, faults,
an unexpected peripheral type, or a write channel not owned by EE 0. Only timer, current, resolution,
strobe, module-enable and channel-enable registers are writable. The routine disables the output
and restores all six saved registers; a timeout quarantines the channel. This is an opt-in hardware
diagnostic, not an iOS flashlight implementation or proof of visible light.

`tools/test-fuxi-torch-pulse.py` compiles the exact sequence against a register model, including
read/write failures, dropped writes, timeout quarantine, timer ordering and saved-state restoration.

## Allocated high-memory check

ADT `/chosen` u32 `fuxi,ramtest=1` starts one test worker, independently of the DSP mode.
It accepts only the 9 GiB layout (`dram-size=0x23e000000`, GPU scratch
`0xafe000000+0x2000000`) and otherwise leaves memory alone. The default is off.
Twenty seconds after starting, the worker asks XNU for a 128 MiB data allocation without
waiting for free pages. It validates every allocated physical page against the usable RAM
aperture before writing, and requires at least one page above the old 5 GiB boundary.
It never writes to arbitrary physical addresses, firmware carveouts or the GPU scratch region.

Four address-dependent 64-bit patterns are filled, cleaned and invalidated from the data cache,
then checked after a short delay. Each pass reports its actual high-memory coverage; the first
mismatch stops the test. The allocation is released on every path after a successful allocation.
This is an allocated-memory sample, not a test of all 9 GiB or a long-duration pressure test.
`tools/test-fuxi-ramtest.py` checks the production range gate and injects every single-bit error
in a non-power-of-two buffer, plus a word-alias corruption. Kernel compilation and device
results are recorded separately.
