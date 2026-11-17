# HTC host-only preparation checkpoint

This independent C11 parser and diagnostic observer are not linked into WLAN,
the kernel build, CE, WMI or a loader. `FUXI_HTC_DEFAULT_ACTIVE` is always zero.
Initialization does not enable observation. No boot argument, MMIO, DMA,
allocation, device operation, service connect or transmit path is added.

## Primary protocol evidence

- Linux v6.12 [ath12k htc.h](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/htc.h#L18): two little-endian words form the eight-byte HTC header; endpoint, flags, payload length and trailer length have distinct fields.
- [READY and CONNECT_RESPONSE](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/htc.h#L99): base READY is eight bytes, extended READY is twelve; credit count/size are u16, maximum endpoints is u8. CONNECT_RESPONSE is twelve bytes plus declared metadata.
- [Trailer records](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/htc.h#L131): four-byte record headers, followed by `len` body bytes; credit reports are four bytes each.
- [Credit handling](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/htc.c#L145): each report's endpoint owns its credit increment, not the outer frame's endpoint. Repeated reports for the same endpoint are additive, not duplicate grants to discard.
- [Receive and control handling](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/htc.c#L252): trailer length is included in payload length; control messages use endpoint zero. Local bounds are nine endpoints, 4096 frame bytes and 256 control bytes.

These are protocol references, not Fuxi HTC hardware evidence. No sheng firmware
or inferred sheng endpoint/credit allocation is used.

## Conservative single-frame policy

`fuxi_htc_parse_frame()` checks all bytes before committing its output. Errors
leave the caller's output unchanged. Unaligned input is decoded bytewise.
The caller supplies the exact received frame length, not DMA-buffer capacity;
transport padding, bundled frames, unknown flags/records and nonzero reserved
padding are rejected. NULL trailer record bodies are bounded but not interpreted.
Future READY extensions are rejected rather than silently truncated. Unknown
control message IDs are copied as bounded `CONTROL_OTHER` observations, not
treated as replies. Failed CONNECT responses are decoded without assigning an
endpoint. Successful responses must name a nonzero local endpoint and message
size; live advertised endpoint limits and pending-service correlation remain
the existing transport owner's responsibility.

Credit deltas are indexed by the report endpoint, with at most 62 reports and
63 trailer records. The parser does not replenish or spend credits, replace
endpoint maps, auto-allocate READY credits, complete pending transactions or
change credit-flow policy. Original service/endpoint/credit consistency and
locking stay with their existing owner.

`fuxi_htc_observe()` emits one copied, fully validated observation per frame,
at most sixteen callbacks per initialization. Inactive, malformed, exhausted
and recursively invoked calls do not deliver callbacks. The callback borrows
the immutable observation only until return; it must not retain its pointer or
reinitialize the observer from inside the callback. The caller must serialize
all observer access; the reentrancy guard is not a cross-thread lock. This prep
module neither adds nor removes the existing shared RPMh lock or ADSP guard.

## Host check

```text
python -B tools/test-fuxi-htc-prep.py
```

The test compiles the production C file and an independent synthetic wire peer
in a temporary directory. POSIX uses `CC`/`cc` with ASan and UBSan. Windows uses
the installed MSVC development environment and ASan. `--arm64-compiler` can
add a freestanding arm64 iOS compile-only check using an explicit clang path.
No source mirror, aggregate patch, build script, firmware or phone is touched.
