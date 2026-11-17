# Fuxi ath12k board adapter

The existing WLAN diagnostic reached FW_READY, INI, CFG and a successful
WLAN_MODE response with upstream WCN7850 firmware and the PMK8550 GPIO3 sleep
clock enabled. Its legacy path intentionally stops before CE/HTC/WMI.

The new board adapter is disabled by default. Its diagnostic opt-in requires
`fuxiwlan=1 fuxiwlanath=1 fuxiwlanmlo=192`, the native module entry points,
the CNSS IOVA pool, and no legacy QRTR, probe, sequence, keep or partial-stop
selectors. Invalid combinations are rejected before WLAN power writes. ADSP
must remain disabled for this experiment.

The legacy board code owns power, PCIe and SMMU setup through step 18.
The native module then exclusively owns MHI, QMI, CE, HTC and WMI from PBL;
legacy steps 19 through 28 are skipped. The adapter supplies the complete
2 MiB BAR, a 128 MiB Normal-NC DMA arena, bounded allocations, narrow PCI
configuration accesses and polling callbacks. The first 4 KiB of the arena
is reserved for an MSI sink and cannot be allocated to module buffers.

DMA map and free operations require owned allocations and matching pointer,
bus address and length. Invalid operations latch the adapter failed.
The module's dma_kfree callback supplies zero length and bus address; that
specific pair resolves an exact live allocation base through owned metadata.
It does not admit interior pointers, stale buffers, the MSI sink, or a
partially missing coherent-free identity.
Containment stops DMA and detaches the owned SMMU mapping before releasing
the arena. Metadata and cached firmware are released only after the arena
has been released; failed containment retains the allocations.

Firmware is read from `/usr/local/share/fuxi/wlan/`: `amss20.bin`, `m3.bin`,
`board-2.bin` and `regdb_xiaomi.bin`. Only these names are admitted. The root
currently needs `board-2.bin` staged before the experiment can start.
Firmware, phone device trees and Apple binaries are not CI inputs.

Before module initialization, the adapter installs the required native
control transport. After module stage 4, its diagnostic client attaches a
session, obtains the connection generation through an INFO request, and
submits one wildcard SCAN request through the real cfg80211 control queue.
Reply sequence, session, generation, status and complete framing must match.
Both an accepted scan reply and a successful SCAN_DONE event are required;
an aborted event or command error cannot pass. The client has no password,
association, key or packet operations. It polls for at most 90 seconds,
prints at most 64 BSS records, stops the module and enters common containment.
It does not expose a native userspace socket, iOS Wi-Fi settings interface,
connection, IP traffic or persistent networking yet.

Host validation includes 236471 native MSVC ASan checks and 30000 allocator
transitions, PCI write-one-to-clear preservation, release ordering and
idempotence. A separate comparison against the pinned module ABI checks four
structure sizes and alignments, every field offset and platform callbacks.
The M6, M6i, M6o, Rails and W18 production extraction regressions also pass
with wasm32 ASan/UBSan after the adapter changes.

The module object has been built separately from pinned public sources.
`FUXI_ATH12K_OBJECT` optionally adds that exact verified object to the plain
arm64 kernel link. `tools/ci/ath12k-link.py` checks its SHA256, Mach-O header,
kernel ABI flags, source lock, imports and entry points before staging.
The existing iOS 16 XNU build uses the macOS 15.5 SDK build profile, so
module objects use `arm64-apple-macos15.5`, `-mkernel` and
`-mgeneral-regs-only`. Both input and linked kernel must have the matching
Mach-O platform and minimum version. The initial iOS-targeted object was
rejected at final linking; it is no longer admitted.

The replacement module is pinned to CI run `43894744787`, harness commit
`cb63de2e6b6fc4a4c63cf8f00c1710cf24f6bb84`, object SHA256
`78178a345c8573a13aa1781221b18ea993b0b8716defb09ba4543e494ad4f6e1`.
It contains 125 public source objects with the existing source lock and
13 kernel imports.

The variant patch adds the object as a link dependency and retains all 14
board and control entry points. After linking, the build requires those entry points to
be defined in the unstripped kernel and records the object and kernel hashes
in `ath12k-link.json`. Other kernel targets reject the object input.

Only the optional variant defines `FUXI_ATH12K_LINKED`. Ordinary kernels
compile out native module calls and reject the opt-in before power writes.
This replaces unresolved weak imports, which the static kernel link
rejected even when WLAN was disabled at runtime. An extracted production
test compiles and links that absent-module path without providing any
module symbols.

`tools/test-fuxi-ath12k-link.py` checks malformed or ambiguous Mach-O version
commands and the actual pinned bundle, including wrong target, ABI flags,
source lock, imports, exports and corrupted object rejection.

CI run 43896202460 completed the original full XNU build. Its first device
test reached the firmware cache and DMA/SMMU setup, then returned -16 before
PCI probing. The missing control transport made nl80211 initialization
return -EBUSY; the module requires a transport even for diagnostics. The
adapter now supplies a bounded scan-only peer instead of ignoring this
initialization failure. Host tests cover the handshake, actual pinned wire
codec, transport ABI, stale replies/events, malformed frames, command errors
and scan event/reply ordering.

The next local device test passed control initialization, recognized WCN7850,
loaded the firmware and reached MHI Mission Mode (AMSS/M0). DMA ownership
then latched failed because the adapter rejected the module's dma_kfree
sentinel. The sentinel path now resolves the recorded identity while normal
coherent frees retain exact size/address checks. Host regression exercises
release and reuse through both callback forms.

On 2026-11-17, the local 9g kernel with the DMA sentinel fix completed a real
scan: 34 BSS entries across 2.4 and 5 GHz, start error 0, DMA error 0 and
faults 0. The diagnostic then stopped and contained the device; bus mastering
was off and PERST asserted, while MHI reset remained unconfirmed. This is
firmware and radio scan evidence, not Settings, association or traffic evidence.

`fuxiwifiios=2` selects the native iOS station bridge. The wireless worker
owns all module operations. Blocking station requests use a bounded mailbox;
power completes only after the native applied-power event, and scans require
both a successful reply and SCAN_DONE event. INFO supplies the interface MAC;
GET_CHANNELS supplies the channel inventory. The worker stays alive after
publication and keeps its DMA ownership. The optional `fuxiwifitest=1` runs
two power-off/on and station-scan rounds on a separate caller thread. Host
tests cover repeated power generations, directed frequency filters, event
ordering, stale replies and timeouts.

Since 2026-11-17 the bridge also joins open and WPA2-Personal networks over
the same control channel (AUTHENTICATE, ASSOCIATE, RX/TX_EAPOL, SET_KEY,
SET_PORT, SET_OPERSTATE; see `wifi-ios.md`), reads scan results through
GET_BSS with every element instead of the 384-byte module records, and moves
Ethernet frames with the module's exported `nw_wifi_set_events` (rx) and
`nw_wifi_tx`. Both symbols are in the link gate's entry points. The worker no
longer sleeps between steps while `nw_wifi_step` reports moving frames (at
most 64 rounds in a row). `fuxiwifitest=2 fuxiwifitestssid=<name>` tries one
join with a made-up passphrase. All of this is host-tested; device validation
is pending.

The firmware callback provides `wlan_mac.bin` from the existing valid
`/chosen/mac-address-wifi0` identity so the native interface and MobileGestalt
agree across boots. This is the port's existing locally administered identity,
not a recovered factory MAC. The controlled loader's `--wifi-ios` adds a
`wlan` DT discovery node so the existing launchd DT gate can load wifid
without an offline root edit; `--wifi-self-test` enables the station probe.
