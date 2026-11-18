- **Kernel CI 43616686724 OK** (fuxiamp, harness a37ccac): fuxi_amp.c and GeniI2c.c compiled (style warnings only).
  Artifact -> `Codex-Xiaomi13-GPU-20261109\kernel-adsp-amp-artifact` (SHA256SUMS OK, cmdline = bo4096's), kernel sha256
  `0585ca64c537f8109886a3e9e9017b4104765f72edf0915fbd169f133263c64b` (ADSP phase 1+2, fuxiamp, backlight code).
- Loaders (host only, NOT booted; same 592-char vt6tc-user args, no fuxibacklight; pass verify-loader-safety.py):
  `native-survey-user-loader` = ADT fuxi,adsp=1 + fuxi,amp=1 (both read-only: one boot shows the DSP's SMP2P/AOSS/RSC
  state and the amplifier bus' clocks/pins/FIFO lock), boot.img `9eecd7f5...6c3b`; `native-amp2-user-loader` = fuxi,amp=2,
  boot.img `a2ac4274...21e0`. `work\adsp-battery\run-adsp-boot.ps1 -Loader <name>` now takes any loader (kernel from its
  source.txt). Suggested order when the phone is free: survey -> adsp2 -> amp2 -> adsp3 -> bl4 (brightness).
- At 01:2x the hybrid lane was running 0028 boots (native-layout0028-hyb1-p1-boot-1), so nothing was booted. D: 18 GB free.
