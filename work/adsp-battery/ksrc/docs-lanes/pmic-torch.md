# PM8550 torch control

`fuxi,pmic=1` surveys the PMIC. Mode 2 runs one 40 mA, 80 ms pulse with a
100 ms hardware timer. The initial mode 2 device run returned success and
restored all saved registers. Visible light and the Control Center path are
separate acceptance checks.

Mode 3 maps the same owner-0 flash channel, starts an idle worker, and exposes
the `kern.fuxitorch` integer. Writes admit root or the platform-signed
SpringBoard process, including its normal mobile UID. Values 1 through 4 request 20, 40,
60 or 80 mA; zero stops. Each write renews a two-second lease. Mode 3 now
uses continuous torch output. It writes the current and software-strobe
configuration once, disables the flash timeout, and keeps the module and
channel enabled until stop, lease expiration or a failed
health check. Its 20 ms health checks only read registers. An unchanged
level never writes registers. A change between nonzero levels checks the
existing configuration and fault status, updates only channel 0 target
current at offset `0x42`, verifies the new configuration and fault status,
and preserves the original idle snapshot for the eventual stop.

This replaces the old mode 3 sequence of 80 ms pulses and per-pulse
restoration. In the 2026-11-16 manual run
`native-hw000torchmanual-user-boot-1`, the user confirmed physical light but
reported visible blinking. Successful pulse counts did not establish
usable continuous illumination.

The register sequence follows the continuous torch path in Linux v6.12
`drivers/leds/flash/leds-qcom-flash.c`, specifically
`qcom_flash_led_brightness_set`: 5 mA current resolution, zero flash timeout,
module enable and software channel strobe. Mode 2 retains its bounded pulse
implementation. No thermal thresholds, boost settings or channel ownership
are changed.

Live current updates follow Qualcomm's `qti_flash_led_enable` in
`drivers/leds/leds-qti-flash.c`, pinned at Android kernel/msm commit
`b6410c3f75259c0ca2df45a01838d2e46272723e`. Its already-enabled torch path
returns after configuring current, before timer or strobe setup:
https://android.googlesource.com/kernel/msm/+/b6410c3f75259c0ca2df45a01838d2e46272723e/drivers/leds/leds-qti-flash.c
The current resolution stays fixed at 5 mA, so the fuxi live update needs
only the target current write. The existing 20/40/60/80 mA limits remain.
In `native-hw000torchsteady-user-boot-1` on 2026-11-16, the user confirmed
continuous light at a fixed level but observed a blink while changing
brightness. That version stopped and restarted for every level change.
The live update correction still requires separate physical observation.

Mode 3 reads all three fault status bytes and verifies its configuration
during each health check. Stop disables the channel and module, requires two
consecutive off observations, and restores the saved configuration only
after confirmation. Errors latch the worker off until reboot, with one
shutdown attempt and no automatic restart. The two-second lease handles
lost user-space renewals while the kernel worker and SPMI remain operational.
Continuous mode disables the flash timer and therefore does not claim an
autonomous hardware cutoff during a stalled kernel or failed SPMI bus.

Both implementations accept only flash type 0x18, subtype 7, an idle
module and clear fault status. Its write allowlist is 0x3e, 0x42, 0x46,
0x49, 0x4a and 0x4e. If output disable cannot be verified, saved configuration
is not restored. No boost ownership is changed.

The SpringBoard library adapts AVFlashlight only when the mode 3 sysctl is
available and all selected Objective-C method signatures match iOS 16.
Its level argument and return use `float`. The adapted initialization calls
NSObject initialization without creating an Apple camera-server object.
The original deallocation path already accepts a null private implementation.
The library renews the selected level every 500 ms; renewal and stop writes
share one mutex. A SpringBoard crash therefore stops renewal.

`tools/test-fuxi-torch-pulse.py` exercises the production register sequence,
all four current levels, injected failures, dropped writes and restoration.
`tools/test-fuxi-torch-runtime.py` exercises the production lease state,
caller admission, renewal, expiration, invalid levels, overflow and latched failure. These
checks do not establish visible light or continuous output quality.
`tools/test-fuxi-torch-steady.py --sanitize` adds four modeled 120-second
holds with exactly one enable transition, 100 requested levels including
upward and downward changes, and all nonzero level pairs without cycling
the output. It checks explicit stop, lease expiration, injected failures at
every update read, failed and dropped current writes, configuration changes
and fault status before and after a current update, and no restart after
failure. Physical brightness transitions remain a manual device check.

The survey also reads haptic boost offset 0x41 and additional haptic
configuration offsets. The boost channel is owner 3. No haptic writes are
introduced by this change.

## 2026-11-16 shutdown readback checkpoint

The iter3 device audit ended after nine completed pulses. The failing pulse
returned `-6`: both disable writes returned success, but the first channel
readback was `1` while the module readback was `0`. The later stopped survey
read both as zero. Its 80 ms sleep measured 81.020 ms. This establishes a
shutdown readback mismatch, not a proven thermal fault or a fully identified
SPMI/hardware cause.

The next experiment retains the original enable sequence, 80 ms pulse,
`0x8a` timer, current limits and reboot-only failure latch. Shutdown now
requires two consecutive channel/module off observations, with at most four
pairs and 1 ms waits between pairs. A read failure aborts confirmation. Fault
status is checked again after confirmation, before saved configuration is
restored. Exhaustion retains the timer and waits for its deadline as before;
there is no re-enable or failure-latch reset. Host models exercise delayed
readback, persistent mismatches and injected read/write errors. This remains
an experiment until an actual device run demonstrates the result.

The following 120-second request did not complete: shutdown confirmation
succeeded, all fault status reads were zero, and saved writes completed, but
the saved current-register read at offset `0x42` returned a transport error.
The worker remained latched off. Its audit still distinguishes this from a
disable mismatch or thermal fault. The next diagnostic records up to eight
raw SPMI rejection statuses, including APID, owner and failure/denied/dropped
bits. It does not retry, change the control sequence or clear the latch.
