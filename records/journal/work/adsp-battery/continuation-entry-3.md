- **Sound step 1, `fuxiamp`** (ksrc 417dcf3, harness a37ccac, kernel CI 43616686724): `xnu/fuxi-adsp/fuxi_amp.c` + UniXNU-sheng
  `GeniI2c.c/h` (unchanged) in 0117; called from `fuxi_adsp_init` with its own switch (`fuxiamp=N` / ADT `fuxi,amp`). Board:
  live DT i2c@880000 = QUP2 SE0 (SPI 373, `dmas` present), cs35l41@40 "B" reset GPIO 183, @42 "T" reset 182, SDA gpio0 / SCL
  gpio1 function 2 (`qup2_se0_l0/l1_mirb`, Linux pinctrl-sm8550.c v6.12), 2 mA pull-up - the same engine and pins as sheng's
  amplifier bus 2. GCC (gcc-sm8550.c v6.12): 0x52010 bits 0-4 = wrap2 core/s_ahb/m_ahb/core_2x/s0, halts 0x233d4/0x233d0/
  0x233cc/0x23004/0x1e004, SE0 RCG 0x1e010. Mode 1 reads only (engine registers only when all five branches read CLK_OFF=0:
  an unclocked read stalls the bus) and answers whether the engine is FIFO-capable or GSI-only (`GENI_IF_DISABLE` bit 0, as
  touch's SE4). Mode 2 = sheng's setupClocks/setupPins/setupBus + SPI 373 masked + per amp reset release, DEVID/REVID/
  IRQ1_STATUS3/4 reads, back into reset, pins and votes restored; nothing written to the amplifiers. docs-lanes/adsp.md
  "Speaker amplifiers". Host syntax check clean. Kerfand/UniXNU-Fuxi-Arm64e-iOS17 `device/package/FuxiCs35l41.c`
  (BSD-2-Clause-Patent, CS35L41 init programs on sheng's runner) is the reference for the later amp configuration.
