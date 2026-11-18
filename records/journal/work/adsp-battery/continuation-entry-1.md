
## 2026-11-15 ~00:30 hardware lane ("000") step 2: audio DSP + battery manager `fuxiadsp` (offline, phone untouched)

- Previous 000 session (1ed6041d) stopped at its usage limit at 23:47 with the code written but never compiled or wired
  into the build. This session finished it. The phone stays with the hybrid lane (0027 written 23:48); not touched.
- Kernel source worktree `work\adsp-battery\ksrc` (branch `adsp-battery` of kdraws-src from eafc778 = backlight):
  d5c44c3 (patch 0117 + 0106), f1a0846 (0111 regenerated: its sweet_ufs.c hunk moved), 478bf32 (phase 2).
  - `xnu/fuxi-adsp/` -> new patch **0117** (`tools/sync-fuxi-adsp.py`; 13 .c into bsd/conf/files after sweet_usb.c,
    headers to bsd/dev; LICENSE.UniXNU-sheng already shipped by 0098, checked identical). Port of UniXNU-sheng
    6880068 AdspProbe.cpp / AdspFirmware.c / ShengBattery.cpp; Qcom*.c, FatVolume.c, ShengBattmgr.c, ShengQrtr.c copied
    unchanged. Differences from sheng: IPCC/RSC polled (SPI 229 and SPI 5 masked in the GICD first: no handler here),
    windows via kernel_map VA + pmap entries (never ml_io_map), carveout windows unmapped by pmap_remove before
    auth_and_reset with the VA kept, firmware only from modem_a/modem_b in place, refused (survey only) with fuxiwlan.
  - 0106 (`sweet_ufs.c`): read-only `fuxi_ufs_part_find` / `fuxi_ufs_part_read` for GPT partitions on LUNs 1-5
    (LUN switched for one READ(10) under sweet_ufs_lock and restored; FUXI SCSI policy unchanged; refused with
    fuxi_unixnu_ufs=1); `fuxi_adsp_init()` called after `fuxi_wlan_init()`.
  - Modes: `fuxiadsp=N` or ADT `/chosen` u32 `fuxi,adsp` (the boot-args field is 607/608 full): 1 survey (reads only),
    2 start the DSP (SMP2P, AOSS load_state, lcx/lmx proxy votes on TCS 1, PAS 36 + PAS 1, GLINK, IPCRTR locator,
    PMIC_RTR_ADSP_APPS) and log `FUXI BATTERY:` lines, 3 also SweetBattery publishes the readings (phase 2: percent
    >= 1, never critical, charger state only when known; xnu/fuxi-adsp/SweetBattery.cpp + fuxi_adsp_battery.h, the
    0062 file plus the new source, carried by 0117). docs-lanes/adsp.md has the stages and log lines.
- Checks: NDK clang 17 `--target=arm64-apple-ios16.0 -ffreestanding -fsyntax-only` with stub headers
  (`work\adsp-battery\hostcheck`) clean for all 13 C files (-Wall -Wextra -Wshadow -Wsign-compare); bsd/conf/files
  chunks of all patches applied in order on the real xnu-8796.141.3 list (fetched read-only) - 0117 lands after
  sweet_usb.c; Alpine guest test (`work\adsp-battery\guest-run-fw.py` + `fwtest-share`, modem_a backup attached
  read-only as vdc): the kernel's fuxi_adsp_fw.c + FatVolume.c + QcomMdt.c read adsp_dtb (16184 B, 1 load) and adsp
  (39721400 B, 57 loads, hash = phdr 58) byte-identical to an independent Python join, metadata 4044 / 8524 B
  identical, placements fill 0x20b8 / 0x4680000 of the carveouts, every UFS read inside the partition (588 reads).
- CI: 43613488060 failed only at sync-fuxi-prof --check (0111 offset) -> fixed; **43613785715 OK** (phase 1: all 13
  files compiled, 0 errors, only xnu-wide style warnings); 43614748612 (phase 2) running.
- Windows notes: upstream sync/check tools need `run_lf.py` AND `GIT_CONFIG_PARAMETERS="'core.autocrlf=false'"` (git
  apply in temp dirs otherwise writes CRLF and the byte compares fail); sync-fuxi-sys / sync-fuxi-wifi-ios fail on
  Windows at the base too. The Bash tool turns `\\n` inside heredocs into real newlines: write such scripts with the
  editor.
- Loader tool: `Codex-Xiaomi13-GPU-20261109\prepare-adt-variant-loader.py <out> <src loader> <artifact> chosen:fuxi,adsp=N`
  (prepare-kernel-variant-loader.py plus /chosen u32 properties; same payload/loader checks). Not run yet.
- On-device plan (when the phone is free and the user agrees): bl4 + adsp kernel, mode 1, then 2, then 3, each a
  fastboot boot (no write). ADT root extents must match the phone (verify-native-map). Look for `FUXI ADSP: survey`,
  `firmware volume modem_a`, `ready after N ms`, `channel PMIC_RTR_ADSP_APPS up`, `FUXI BATTERY: percent=`; compare
  with Android `dumpsys battery` before mode 3.
