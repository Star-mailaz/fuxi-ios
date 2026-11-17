# Torch timer source checkpoint

## Scope

The production pulse changes only the channel-0 safety-timer setup byte at
offset `0x3e`, from `0x8a` to `0x89`. This lowers the worst source-decoded
duration; it does not relax fault handling or establish a hardware fix.

The existing type `0x18` / subtype `0x07` admission remains mandatory. The
local live DT identifies PM8550 SID 1, flash base `0xee00`, compatible
`qcom,pm8350c-flash-led`. The OEM driver selects four channels for that
compatible and defines the four-channel subtype as `0x07`. Linux v6.12
selects its four-channel register map for type `0x18` / subtype `0x07`,
including channel timers at `0x3e + channel`.

## Primary source contract

Both sources use bit 7 to enable the timer and 10 ms timer steps. The
duration below is the source-derived inverse of their integer programming
formula at exact 10 ms multiples, not a measured PM8550 cutoff.

| Primary source | Programming rule | `0x8a` model | `0x89` model |
| --- | --- | --- | --- |
| MiCode Fuxi OEM | `round(timeout_ms / 10) - 1` | 110 ms | 100 ms |
| Linux v6.12 | `timeout_ms / 10` | 100 ms | 90 ms |

Thus `0x89` retains the enable bit and is at most 100 ms under both pinned
source interpretations. The source disagreement is not resolved by this
checkpoint, and neither interpretation is substituted for device evidence.

- [OEM driver](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/7fad87dc178d09489b74a714e4a525d56f546855/drivers/leds/leds-qti-flash.c#L221):
  commit `7fad87dc178d09489b74a714e4a525d56f546855`, SHA256
  `56e96975b820e8f88b4ae6fcf7acedfb53f577424e9f7d9b16637c86652f514d`;
  `timeout_to_code()`, timer enable/step definitions, subtype and match table.
- [OEM PM8550 DT](https://github.com/MiCode/kernel_devicetree/blob/5647c799a064dfec73332a4fe2ef7aa3fb2f4887/qcom/pm8550.dtsi#L120):
  commit `5647c799a064dfec73332a4fe2ef7aa3fb2f4887`, PM8550 SID 1 flash
  peripheral and `qcom,pm8350c-flash-led` compatible.
- [Linux v6.12 driver](https://github.com/torvalds/linux/blob/v6.12/drivers/leds/flash/leds-qcom-flash.c#L368):
  SHA256 `41575a93352acf5598563bcb943fbdf07931a443fd5ad649dc1d4bd836a0916f`;
  `set_flash_timeout()` and the type/subtype-specific four-channel map.

Both driver bytes were fetched and hash-checked again for this checkpoint.

## Unchanged safety boundaries

- The software pulse wait remains 80,000 us; levels remain 20/40/60/80 mA.
- Lease duration and runtime failure latch are unchanged; no retry or re-enable
  is introduced after failure.
- All three status offsets `0x06`, `0x07`, `0x09` still reject every nonzero
  byte, including post-disable `0x09 bit4`. No normal-status exemption is added.
- Timer write/readback still precedes module/channel enable. The write allowlist,
  bounded two-sample disable confirmation and saved-register restoration stay
  unchanged. Unconfirmed disable still retains the newly programmed timer;
  the existing 110,000 us cleanup wait is unchanged, not a pulse extension.
- Existing canonical integration, `fuxi_pmic.c`, sync and aggregate patch are
  untouched. The main agent owns propagation into the next kernel. Existing
  `timer=100ms` log text is not an autonomous-cutoff measurement.

## Host verification

Run from the source checkout:

```text
python -B tools/test-fuxi-torch-pulse.py
python -B tools/test-fuxi-torch-audit.py
```

The pulse test checks both source decoders over the enable bit and all 128
timer codes, shows that the old byte exceeds the OEM 100 ms source bound,
and runs the production sequence and fault/drop/delayed-readback cases under
both timer models. Each model checks expiration immediately before and at
its own modeled deadline. Every channel enable requires verified `0x89`
and both decoded durations at most 100,000 us.

The audit test checks the actual production timer write/readback ordering,
both source upper bounds, the unchanged 80 ms wait and 1 ms confirmation
wait, and a synthetic post-disable `0x09=0x10` read with transport `rc=0`
that still returns `-5` while configuration restoration succeeds. Existing
read-failure and audit-capacity/time-overflow cases remain covered.

`tools/test-fuxi-torch-runtime.py` has no timer-byte expectation and needs no
source change. Its lease and latch checks remain separate from the two
callback models.

The local checkpoint passed both listed scripts with MSVC 14.50.35717,
C11, `/W4 /WX` and AddressSanitizer. The unchanged runtime test's C body
also passed with the same detected compiler and sanitizer, using a temporary
host build without editing its Python runner. Local UBSan was not run;
the existing non-MSVC runners retain their ASan/UBSan flags.

These are deterministic host/source checks. The modeled `expired` field
is not a physical output observation, and ASan/UBSan cannot prove PMIC timer
start/cancel semantics, oscillator tolerance, optical cutoff, SPMI latency,
or finite physical shutdown.

## Device evidence still missing

The existing `native-hw000torchraw-120s-boot-1` run used the old byte, not
this checkpoint. It confirmed successful transport, bounded off readbacks
and restoration, then failed on a transient post-disable `0x09=0x10`.
Software had already disabled output before the nominal source deadlines;
that trace contains no autonomous-device-cutoff proof.

The main agent's next bounded device diagnostic must preserve the cutoff,
current, lease and failure latch, verify the new byte before enable, and
record per-channel status and timestamped shutdown observations. Even a
successful software-disabled pulse is not autonomous-cutoff acceptance.
The meaning and clear/lifetime behavior of actual PM8550 `0x09 bit4`, the
timer's start/cancel behavior, and physical cutoff remain unverified. This
encoding correction neither explains nor fixes the observed status failure.

## 2026-11-16: first device run with the bounded timer byte

Run 24 used `native-ram9g-torchtimer-audit-loader` with the already verified
`kernel-adsp-cap-timer-ram9g-artifact`. Temporary boot began at 18:43:00;
Android completion, unmapped root and release of the owned locks were
confirmed at 18:49:49. The daily boot partition was not changed. Host TSENS
maximum was 48.5 C. The monitor recorded one recovered USB drop.

The boot image SHA256 is
`d1e812f14d3c23bb1f1ae27a13e881e5190e259336ebe4343b725b12349331de`;
the kernel SHA256 is
`aabeb78f6589b5cef2eafa31c8b353aacb857c64c7894884979c40269d8d4338`.
The existing 80 mA / 120-second tap script was retained, including the
original current, lease, disable checks and failed latch. The kernel and
incoming-FDT guard differ from the older run, so this is not a strict
same-kernel causal A/B.

The USB log at
`work/Codex-Xiaomi13-GPU-20261109/native-hw000torchtimer-120s-boot-1/boot.log`
has SHA256
`b6a59f13bc2bf2c03c715a9589ee9d8a7c735a625422cc3bbf4bdb526b82d8ad`.
The persistent console was saved at 18:50:33 as
`work/adsp-battery/fuxilog/20261116-185033/console.txt`, boot 26,
flush 32, 316021 bytes, SHA256
`c5f241ee3b3556ae7ba711744f7ec47e07ea2c956a1e859492e99a42872b4b35`.
It also contains the second tap after the 120-second wait, beyond the
240-second USB monitor window.

The runtime counted 21 successful pulses before it latched off with
`rc=-6`. The failing transaction was an observer read of SID1 `0xee46`,
APID591, owner0, status `0x9`: DONE plus DROPPED, with no FAILURE or DENIED
bit. In the 49-event audit, event11 writes `0x89` to timer `0x3e` and
event12 verifies it before enable. Event38 reads post-disable `0x09=0`;
the failing audit therefore does not reproduce the older `0x09=0x10`
failure. It does not establish that the older flag can no longer occur.

Configuration restoration writes and their readbacks succeeded. Event47
is the final module-off confirmation read, `offset=0x46 rc=-1`; its
placeholder zero is not a successful off observation. Event48 reads
channels `0x4e=0` successfully. A later bounded diagnostic reads
`module=0 channels=0 status=0/0/0 read-rc=0`. The failure latch and lease
failure remained active; no write retry, ignored status or renewed pulse
was added.

The saved Linux v6.12 `spmi-pmic-arb-v6.12.c` treats DROPPED as `-EIO`.
This trace does not prove why the transaction was dropped or justify
blindly retrying an ambiguous transaction. The next work is the observer
transaction / ownership path. Sustained visible light, the requested
120-second illumination and autonomous hardware cutoff remain unverified.

## Shared arbiter lock (source fix, device effect not yet observed)

Source inspection after the DROPPED read found that `fuxi_pmic.c`
serialized its SPMI arbiter transactions only with the private `fp_lock`.
`fuxi_keys.c` polls the power and volume keys every 20 ms (and reads the
RTC) on the same arbiter (core `0x0c400000`, observer `0x0c440000`,
channels `0x0c500000`) under `sweet_spmi_bus_lock`, and the WLAN P17
sleep-clock code takes that lock too. A torch or haptic transaction could
therefore overlap a key-poll transaction in time. Linux serializes every
arbiter transaction with one lock. This is a plausible cause of the
DROPPED status; it is not proven to be the cause.

`fp_read`, `fp_flash_write` and `fp_haptic_write` now take
`sweet_spmi_bus_lock` for the whole command/poll sequence, inside
`fp_lock` (order: `fp_lock`, then the bus lock; no path takes them in the
other order). There is still no retry: a DROPPED, FAILURE or DENIED status
latches exactly as before, and the pulse limits are unchanged.
`tools/test-fuxi-haptic-survey.py` asserts the lock order, that every
`fp_write32` sits inside the locked region and that no early exit skips
the unlock.

The fix has only been built and host-tested. Whether the 120-second tap
script now completes without a DROPPED read has to be observed on the
device; until then the torch remains unverified.
