- **Kernel CI 43614748612 OK** (phase 2, harness 79948d9 = ksrc 478bf32): SweetBattery.cpp compiled (only its existing
  OSDefineMetaClass warning), no errors. Artifact `fuxi-kernel-adsp-battery` (23347563 B, sha256:d41c0aee...) unpacked to
  `Codex-Xiaomi13-GPU-20261109\kernel-adsp-battery-artifact`: SHA256SUMS OK, cmdline.txt = kernel-bo4096's, kernel sha256
  `e45f9609080afbf8d5d380c9f8121903d9b327c918447fd7298beab8cc6c9ae4` (has the FUXI ADSP / FUXI BATTERY / SWEET BATTERY: ADSP
  / fuxi,adsp / PMIC_RTR_ADSP_APPS strings; also the backlight code, off without fuxibacklight=4).
- Board facts re-checked against the Fuxi live DTB: apps_rsc drv@2 tcs-offset 0xd00, tcs-config ACTIVE x3 first (TCS 1
  is active), IPCC SPI 229 level; smp2p-adsp qcom,smem <443 429>, remote-pid 2, IPCC client 3 signal 2 (SMP2P) / signal 0
  (GLINK); SMEM hwlocks <&tcsr_mutex 3> (syscon 0x1f40000, stride 0x1000); AOSS QMP 0xc300000+0x400; ADSP proxy supplies
  lcxlvl/lmxlvl (DT level 384; the port votes the highest level as sheng does, dropped at handover). The six pd-mapper
  files in modem_a (adspr/adsps/adspua/battmgr/cdspr/modemr.jsn) match ShengQrtr's locator table exactly.
- Loaders (host only, NOT booted): `native-adsp{1,2,3}-user-loader` = prepare-adt-variant-loader.py from
  native-vt6tc-user-loader (same 592-char args, NO fuxibacklight, so ADSP is judged alone) + kernel-adsp-battery-artifact +
  ADT /chosen fuxi,adsp=N. boot.img sha256: 1 `864807e7...1c31`, 2 `b5105f42...c301`, 3 `3a0ce88a...9574`. All three pass
  `verify-loader-safety.py` (new: integrity + kernel = artifact + ADT root extents = managed-native-map-current.json + 20 GiB
  blocks; works for any variant, unlike the stale verify-args-on-loader-payload.py) against the 00:10 mapping.
- Boot tooling: `boot-exp-v.ps1` = boot-exp.ps1 + `-Verifier` (default unchanged; the original is untouched because
  other sessions use it); `work\adsp-battery\run-adsp-boot.ps1 -Mode N` runs it with verify-loader-safety.py, kernel
  kernel-adsp-battery-artifact, and writes `<out>\adsp-summary.txt` (FUXI ADSP/BATTERY/UFS lines) and the Android
  `dumpsys battery` after the return. It refuses while run-monitor/boot-exp/monitor/pull/deploy processes run.
