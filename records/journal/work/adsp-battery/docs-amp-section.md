
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
