# W18 WLAN_MODE timeline

## Evidence available on 2026-11-16

The kernel checkout is `work/adsp-battery/ksrc`, branch `adsp-battery`,
HEAD `aab893e`. The current lane source includes the shared RPMh transport.
The ADSP entry point still refuses combined ADSP/WLAN activation pending
hardware validation. The W18 change adds a WLAN diagnostic selector.

`wlan-w16.md` records supplied try15c/try15d observations of FW_READY `0x38`,
successful INI/CFG, and a silent MODE `0x22`. It also records MODE TX
completion, posted RX buffers, AMSS/M0, SYSERR zero, and the raw words
`0xcafecace/0xcafecace/0x14feeb3/0x496`. `wlan-rails.md` describes a supplied
try16 result with `fuxiwlanqrtr=5 fuxiwlanw16=3`.

**The try16 raw boot and complete boot arguments were unavailable in this
workspace audit.** Filename searches including ignored files found no
try15/try16 boot artifact. Searches of local `work` logs and text files found
no `W15 wlan mode normal` or `W16 MODE timeout` transcript. The audit also
checked the harness and the workspace outside `work`. These document reports
are the available historical inputs. Their contents provide no basis for
reconstructing the complete try16 sequence, BDF, MLO/P17 or rail selectors.

The normal M3 path already submits voltage/enable votes for all six external
WCN resources. The rail audit explains their cmd-db associations and the
additional ON-only experiments. RPMh completion and analog pin voltage are
separate measurements. The available evidence establishes submitted votes
and a working digital firmware/QMI path. Internal RF/PHY state and board
calibration suitability remain open.

## Why this diagnostic

The existing W15 timeout records the error words after the ten-second wait.
Its successful FW_READY path first records these words after INI/CFG/MODE
finish or fail. W16 supplies channel context snapshots, but its snapshots
contain no BHI error-word timeline. The current evidence therefore leaves
the first appearance of the debug tuple unresolved.

W18 samples before INI, after INI, after CFG, immediately before the MODE
doorbell, and at the exact MODE TX EOT. A later silent MODE gets two bounded
wait samples and its timeout sample. This identifies the interval containing
a raw-word transition and distinguishes a queued MODE from a host-observed
completion for its specific TRE. The existing W15 reply check continues to
identify transaction success.

The reference ordering and exact wire encodings are documented in W16 and
the independent W15 host peer. Linux v6.12 starts INI/CFG/MODE before live
CE ring setup and HTC startup. P17's vendor HOST_CAP/PHY probes have the
provenance and uncertainty recorded in `wlan-p17.md`. The W18 experiment
selects the diagnostic needed to resolve the error chronology.

Reference protocol and ordering sources are Linux v6.12
[qmi.c](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/qmi.c),
[core.c](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/core.c)
and [mhi.c](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/mhi.c).

## Implemented selector and observations

Append just **`fuxiwlanw18=1`** to the main agent's evidenced short-boot
configuration that already selects `fuxiwlanqrtr=5`. Preserve its actual
other selectors in the captured run record. W18 accepts 0 or 1 at QRTR 5.
Other QRTR selectors ignore it. The absent/zero selector takes the existing
path with zero W18 register reads and logs.

Each sample logs six fault-contained BAR reads in this order.

| Change bit | Register |
| --- | --- |
| `0x01` | BHI_EXECENV |
| `0x02` | MHISTATUS |
| `0x04` | BHI_ERRCODE |
| `0x08` | BHI_ERRDBG1 |
| `0x10` | BHI_ERRDBG2 |
| `0x20` | BHI_ERRDBG3 |

`changed` compares adjacent valid samples. `prior-valid=0` marks an initial
sample or one following an invalid sample. All-ones register values or an
access fault make the sample invalid. A change mask reports changed raw
values. Firmware-specific interpretation still requires independent evidence.

Each sample also includes a sequence number, phase, wall-clock milliseconds
since FW_READY, QMI transaction/message/reply flag, private TX/RX indices,
posted RX count, and the pending MODE TRE address. Six reads are sequential,
so a sample can straddle a device update. The private-index count is host
accounting of posted buffers.

| Phase | Sampling boundary |
| --- | --- |
| `FW_READY before INI` | Accepted ath12k readiness, before the INI request |
| `INI reply/TX drained` | Successful INI response and TX drain |
| `CFG reply/TX drained` | Successful CFG response and TX drain |
| `MODE before doorbell` | MODE transaction prepared, after any selected late rail votes |
| `MODE TX EOT` | Validated channel-20 EOT for the recorded MODE TRE |
| `MODE reply/TX drained` | Successful matching MODE response and TX drain |
| `MODE pending 100 ms` | Existing MODE wait reaches its 100 ms polling budget |
| `MODE pending 1000 ms` | Existing MODE wait reaches its 1000 ms polling budget |
| `MODE timeout` | Existing MODE reply timeout, before containment |
| `QMI wait transport failure` | Event/guard failure during an INI/CFG/MODE wait |

`W18 MODE TX EOT ptr ... bytes ... event ...` prints the exact TRE pointer,
completion length and event words. The current encoded MODE transfer is
52 bytes including QRTR header/padding. A successful response can race
ahead of EOT, so its sample may already have `reply=1`. The pending pointer
clears after EOT, preventing later ring wraps from being counted as another
MODE completion.

A complete immediate success produces six phase samples. A silent MODE
with TX completion produces eight. Existing error paths can terminate
earlier. The wait budgets retain their existing ten-second reply and
two-second observation behavior. Device timing and console output determine
the logged wall-clock duration.

## Single-run judgment

Capture the full loader/kernel arguments, kernel identity, selected file
names/sizes, all W18 lines, adjacent W16 snapshots, and W15 reply/timeout
and containment output from the same boot.

- A debug tuple present at `FW_READY before INI` establishes an earlier
  state. Investigate provisioning/artifact/board evidence in that interval.
- A first change at the INI or CFG drained sample narrows the triggering
  interval to that request and its processing.
- A clean pre-doorbell sample followed by changed words at MODE EOT or a
  wait sample narrows the interval to MODE startup. A raw-word transition
  alone leaves its RF/power/calibration interpretation unresolved.
- A full-length MODE EOT, stable AMSS/M0, posted RX and empty event rings
  strengthens the evidence for firmware-side silence after host-observed
  transfer completion. A missing/short EOT retains a transport question.
- A matching `W15 reply ... msg 0x22 result 0 error 0` and final
  `W15 wlan mode normal ok` establish the existing WLAN-start milestone.
- A transport-failure sample with RDDM, SYSERR or access faults redirects
  investigation to that captured failure. Its validity fields determine
  which raw registers are usable.

## Host checks and integration

`tools/test-fuxi-wlan-w18.py` compiles the production C with the existing
independent W16 synthetic endpoint. Its cases exercise QRTR/selector gating,
all five W16 geometries, exact INI/CFG/MODE bytes, response-before-EOT races,
initial/CFG/MODE debug transitions, 100/1000/10000 ms wait boundaries,
six read-only accesses, unchanged contexts/IPCR buffers, suspicious channel
RP values, repeated TX ring wraps, failed reads, RDDM, and failed-containment
allocation quarantine. `test-fuxi-wlan-m6.py` gains the absent-W18 parser
fixture used by the existing suites.

For source-only parallel work run
`python3 tools/test-fuxi-wlan-w18.py --standalone` with a supported C compiler.
This builds temporary driver/M3 source fixtures and new-file hunks. The
ordinary invocation also checks the canonical repository source mirrors.
The main agent owns canonical 0099 synchronization and the CI entry-point
addition for `python3 tools/test-fuxi-wlan-w18.py`.

Local validation passed W10, W11, W12, W13, W14, W15, W16 and W18, eight
production-C host suites in total. Windows ran the installed Unity
Emscripten toolchain and Node with ASan/UBSan and fatal sanitizer recovery
disabled. The executable target was wasm32. Source-mirror inputs for this
parallel check were generated in memory from the current driver and M3
sources. Canonical 0099 verification and native 64-bit CI are the integration
checks for the main agent. P17 and rail suites remain additional regression
checks for that integration run.

## Remaining milestones and risks

The immediate open milestone is a successful WLAN_MODE response. In this
lane's production entry point, success currently finishes the two-second
indication observation and stops before CE/HTC.

At least three further hardware/protocol checkpoints lead to a basic scan.

1. CE rings, coherent DMA pointers, RX buffers, and bounded interrupt/poll
   servicing, followed by HTC target readiness and service connections.
2. WMI capability/service readiness, initialization, regulatory/channel
   configuration, and firmware-ready completion.
3. Scan command/event handling and delivery of real BSS results through the
   selected iOS-facing control path.

Association and key/authentication handling, usable TX/RX data, and IP
configuration/routing add at least two subsequent checkpoints for a usable
connection. Their implementation and device validation extend beyond this
diagnostic. The unresolved firmware-start failure prevents a credible elapsed
time estimate for scan/connection completion.

The main experimental risk is timing perturbation from the added bounded
reads and console output. Firmware/BDF/regdb/M3 compatibility, board identity,
internal RF/PHY state, and the meaning of the error words remain uncertain.
Host simulations cover software behavior. Native 64-bit kernel compilation,
canonical patch reconstruction, endpoint timing and the new boot result
belong to the main agent's integration/device run.
