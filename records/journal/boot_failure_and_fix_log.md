# Xiaomi 13 (`fuxi`) iOS 17 / XNU (`xnu-12377`) Boot Failure & Fix Engineering Log

This document records every boot failure, root cause, disassembly/kernel finding, and binary/configuration fix encountered while booting Apple iOS 17 (`xnu-12377 / 24A446`) purely in RAM (`fastboot boot`) on the Xiaomi 13 (`fuxi`, Qualcomm Snapdragon 8 Gen 2 / SM8550).

---

## Summary Table of Boot Attempts

| Boot # | Reached Stage | Failure / Halt Log Signature | Root Cause | Fix Applied |
|---|---|---|---|---|
| **Boot 1** | `bootseed_init` | `panic: Expected 256 seed bytes from bootloader, but got 64` | `xnu-12377` requires 4 SHA-512-sized random seed words (256 bytes); legacy ADT generator supplied only 64 bytes. | Switched to `tools/mkadt-fuxi27.py` to generate 256-byte entropy seeds. |
| **Boot 2** | `kern_trustcache` | `panic: image4 interface not available @kern_trustcache.c:592` | TrustCache initialization requires Image4 parsing interfaces provided by Apple's closed-source `AppleImage4` kext, which was not prelinked into the kernel. | Wrote `tools/ios27-prelink.py` to extract and prelink 39 official Apple kexts from the release kernelcache. |
| **Boot 3** | `FuxiRoot27` | `FUXI ROOT27: manifest hash mismatch` | Writing the root image through Android's `/data/` logical volume (`dm-8`) passed through hardware metadata encryption (`dm-default-key`), leaving ciphertext on UFS sectors read by XNU. | Inspected F2FS physical extents on `sda32` and built `scratch/stream_extents_dev` to stream plaintext directly to physical UFS sectors. |
| **Boot 4–5** | `FuxiRoot27` | `FUXI ROOT27: manifest hash mismatch` | Writing while Android/TWRP was active allowed block cache / inline encryption interference so sectors were not flushed in plaintext. | Switched to a raw TCP port 9999 extent stream writer with per-block SHA-256 verification; confirmed extent 0 hash (`efd0e91a...`) matched the host image 100%. |
| **Boot 6** | `bsd_init` | `panic: rootvp not authenticated after mounting @bsd_init.c:972` | Mounted APFS root `disk0s1`, but the unpacked IPSW root image lacked an Apple seal signature, failing `FSIOC_KERNEL_ROOTAUTH`. | Added `fuxi_root27_norootauth=1` to kernel boot-args to bypass root volume authentication. |
| **Boot 7** | `load_init_program` | `panic: Kernel data abort. at pc 0xfffffff00afbc080` (`upl_page_present(pl, 0x7fff)`) | Executed `load_init_program` for `/sbin/launchd`, but Apple's closed-source APFS kext had a `struct upl` layout mismatch against open-source `xnu-12377`, causing an invalid pointer dereference. | Passed `--drop-apfs` to `ios27-prelink.py` and enabled XNU's built-in read-only APFS module (Patch 0008, Dada-APFS). |
| **Boot 8** | `IOFindBSDRoot` | `Waiting on <dict><key>IOPropertyMatch</key><key>UUID</key><string>DADD93F8-DBBF-4B17-A1DF-0F11E64172F7</string></dict>` timeout | After dropping Apple's closed-source APFS kext, APFS child volume `IOMedia` nodes with UUID `DADD93F8...` were no longer synthesized; `FuxiRoot27` exposed `disk0` with physical window UUID `2ABE836E-EB6D-4C24-B639-FDEDDD5154B2`. | Regenerated `fuxi27-root.adt` with `--root-uuid 2ABE836E-EB6D-4C24-B639-FDEDDD5154B2`. |
| **Boot 9** | `check_signature` | `AMFI: '/sbin/launchd': unsuitable CT policy 0 ... killing init (pid 1): dyld signature cannot be verified` | Dada-APFS mounted root and Cryptex volumes and paged in binaries (`pagein 32768 bytes`), but the payload lacked a TrustCache bundle, causing AMFI to SIGKILL PID 1. | Bundled all 3 IPSW TrustCache modules (2,851 entries) via `tools/ios27-root.py trust-bundle` and passed `--trustcache` to `mkpayload.py`. |
| **Boot 10** | `launchd` (userland) | `ERROR: [launchd:1] EXC_GUARD AST: type=0x1 flavor=0x43 code=0x2000004300800407` -> `FATAL exception: type=0xc reason=0x17` | **Breakthrough**: entered iOS 17 `launchd` userland and printed `"hello"` and version string! However, lacking `fuxi_launchd_ramdisk=1`, `launchd` attempted full hardware boot tasks (`fsck`/SEP/container checks), triggering `EXC_GUARD`. | Added `fuxi_launchd_ramdisk=1` (exposes `rd=md0` to `launchd`) and `fuxi_proc_log=1` to kernel cmdline. |
| **Boot 11** | `dyld` / `launchd` | `fuxi: fcntl pid 1 fd 1..43 cmd 97` all 43 dyld chunks registered, `Restore environment starting.` printed, then killed by `EXC_GUARD AST: type=0x1 flavor=0x43 (kGUARD_EXC_STRICT_REPLY)` | **Major progress**: all 43 `dyld_shared_cache` chunks loaded and `launchd` reached `Restore environment starting.`. `DEVELOPMENT` kernel defaulted `task_exc_guard_default` to strict Mach reply-port enforcement. | Added `task_exc_guard_default=0` to kernel cmdline. |
| **Boot 12** | `cpu_common.c` | `panic(cpu 5 caller ...): cpu_common.c:946 Assertion failed: getCpuDatap()->cpu_signal == SIGPdisabled (0x8 == 0x80000000)` | During `launchd` scheduling under SMP (`cpus=7`), SM8550 GICv3 dropped IPI signals across secondary cores, failing CPU 5's `cpu_signal` assertion. | Switched to single-core bring-up config per `docs-lanes/ios27.md` (`--cpus 1` in ADT, `cpus=1` in cmdline), keeping core 0 for XNU and `cpu@100` for the USB monitor. |
| **Boot 13** | `launchd` / `EXC_GUARD` | `ERROR: [launchd:1] EXC_GUARD AST: type=0x1 flavor=0x43 target=0x800407 code=0x2000004300800407 subcode=0x300000000000011` -> `[launchd: killed] exiting with signal 9` | After `Restore environment starting.`, `launchd` called `mach_ports_register` with disposition `0x11` (`MOVE_SEND`). `DEVELOPMENT` kernel enforced `ool_port_array_enforced=1` (`IPC_POLICY_OOL_PORT_ARRAY`), requiring `COPY_SEND` (`0x13`), causing Policy 7 fatal `EXC_GUARD`. | 1. Patched `_ool_port_array_enforced` from `1` to `0`;<br>2. Changed Policy 7 and Policy 4 actions from `3` (fatal) to `1` (ignore);<br>3. Patched `_mach_port_guard_ast` so all flavors respect `task_exc_guard_default=0`;<br>4. Added `ool_port_array_enforced=0 enforce_strict_reply=0 sheng-no-lc=1` to cmdline. |
| **Boot 14** | `launchd` pre-main | `fuxi: sig 6 pid 1 pc 0x1eee4a8c0 lr 0x1eee6bb48` -> `exit pid 1 launchd status 0x6 ns 7 code 0x1 could not set up inheritance port` | **Breakthrough**: `EXC_GUARD` completely eliminated! `launchd` then called `mach_ports_register` for its inheritance port, which `_kernelrpc_mach_ports_register3` rejected under strict IPC naked-send stashing checks. | 1. Binary-patched `ipc_can_stash_naked_send` to return `1`;<br>2. NOPed failure branches inside `_kernelrpc_mach_ports_register3`. |
| **Boot 15** | `launchd` pre-main | `fuxi: exit pid 1 launchd status 0x6 ns 7 code 0x1 could not set up inheritance port` | In MIG server demux `__X_kernelrpc_mach_ports_register3` (`0xfffffff00adb1204`), kernel expected 3 inline descriptors (`msgh_descriptor_count == 3`, `size == 0x54`), while iOS 17 `libsystem_kernel.dylib` sent 1 OOL port array (`count == 1`). MIG returned `-304` (`MIG_BAD_ARGUMENTS`). | 1. Patched `__X_kernelrpc_mach_ports_register3` entry (offset `0x3dad214`) to jump to completion;<br>2. Forced `RetCode = 0` (`KERN_SUCCESS`) on epilogue error paths (`0x3dad2ac`, `0x3dad2d4`). |
| **Boot 16** | `launchd` `dispatch_main` | Child processes (`xpcproxy`) exited immediately with `fuxi: exit pid ... xpcproxy status 0x5 ns 2 code 0x5` (`SIGTRAP`) | **Historic breakthrough**: PID 1 (`/sbin/launchd`) finished init, entered `dispatch_main`, and spawned system daemons including `SpringBoard` (PID 5). However, child processes (`xpcproxy`) hit `SIGTRAP` before printing userland stack traces. | Injected userland backtrace logging inside kernel `psignal_internal` to capture `PC`, `LR`, and return address chain on `SIGTRAP`. |
| **Boot 17** | Child runtime init (`libxpc_initializer`) | `fuxi: sig 5 pid ... lr ... "Kernel bug: mach_ports_lookup() failed."` | Userland `libxpc_initializer` called `mach_ports_lookup()` (`msgh_id 3404`), providing a 64-byte receive buffer for 1 OOL descriptor (56-byte reply), whereas native `_X_kernelrpc_mach_ports_lookup3` emitted 3 inline descriptors (84-byte reply), causing `MACH_RCV_TOO_LARGE` (`0x10004004`) -> `__os_crash` -> `brk #1`. | Wrote `scripts/patch_kernel_lookup.py` to rewrite `_X_kernelrpc_mach_ports_lookup3` (`0xfffffff00adb1368`, 312 bytes), dynamically allocating a kernel port buffer, PAC-signing pointers, and packing an iOS 17-compatible OOL reply message. |
| **Boot 18** | Userland daemon startup | `panic(cpu 0 caller 0xfffffff00b5670c0): kfree: addr ..., size 24 found in heap data.* instead of * @kalloc.c:2783` | **Major progress**: `mach_ports_lookup()` fixed! `launchd` spawned 70+ processes (PID 2–70) without `xpcproxy` `SIGTRAP`. Panic came from `kalloc_data(24, 0)` allocating in `KHEAP_DATA_BUFFERS`, while copyout called `kfree_ext` with `kalloc_type_view_3960 | 1` (`KHEAP_DEFAULT`). | 1. Switched allocation to `kalloc_ext(ipc_kmsg_copyout_ool_ports_descriptor.kalloc_type_view_3960 | 1, 24, 0, 0)`;<br>2. Patched `kfree_zone` type-confusion check (`0xfffffff00ace78e4`) to skip `kfree_heap_confusion_panic`. |
| **Boot 19** | Userland daemon startup | Zero kernel panics! `launchd` spawned 300+ processes (PID 2–300+). Child `xpcproxy` exited on `SIGTRAP` after `dyld` load: `pc 0x1fca598ec lr 0x1fca41080` (slide `0x2ae48000`). | **Kernel stable**: 1.19 MB console output with zero panics.<br>**Child `SIGTRAP` root cause**: unslid PC `0x1d1c118ec` (`brk #1`) = `"Configuration error: Invalid bootstrap port."`. Because Boot 16 bypassed `__X_kernelrpc_mach_ports_register3` without calling the implementation, `launchd->itk_registered[0]` stayed `NULL`, so children read `ports[0] = 0`. | Wrote `scripts/patch_kernel_register.py` to rewrite `__X_kernelrpc_mach_ports_register3` (`0xfffffff00adb1204`, 356 bytes): unpack OOL descriptor, PAC-verify buffer & ports, call `_kernelrpc_mach_ports_register3` to store `itk_registered[0]`, and zero descriptor count so send rights are preserved. |
| **Boot 20** | `launchd` inheritance port registration | `launchd` reported `could not set up inheritance port` again | `patch_kernel_register.py` hardcoded `cmp w11, #3`, rejecting `launchd`'s `count = 1` call with `-304` (`MIG_BAD_ARGUMENTS`). | Updated `patch_kernel_register.py` to support variable descriptor count `0 <= count <= 3`. |
| **Boot 21** | Full userland `exec` | All ObjC processes crashed: `couldn't dlopen libobjc-trampolines.dylib: dlopen(/usr/lib/libobjc-trampolines.dylib, 0x0106): tried: '/usr/lib/libobjc-trampolines.dylib' (no such file, not in dyld cache)` | iOS 16/17 moved ObjC/FFI trampolines into SystemOS Cryptex (`/private/preboot/Cryptexes/OS/usr/lib/`). With `dyld_flags=8`, `dyld` opened `/usr/lib/...` directly on the root volume without a symlink and hit `ENOENT`. | Wrote `scripts/patch_kernel_trampoline.py` hooking `lookup_check_for_resolve_prefix` (`0xfffffff00af614e0`) to transparently redirect to `/private/preboot/Cryptexes/OS/usr/lib/...`. |
| **Boot 22** | **Historic breakthrough: `SpringBoard` ran stably!** Userland services running concurrently | 1. Device rebooted after ~85–90s;<br>2. `logd` crashed on `SIGTRAP` (`0x100b34160`);<br>3. `contextstored` crashed on `SIGTRAP` (`0x1ae4068c0`);<br>4. `backboardd` crashed on `SIGABRT` (`0x1c2617198`). | 1. **90s reboot**: `probe.c:1472` set a 90s watchdog (`MON_DEADLINE`) and `scripts/do_boot.py` omitted `--reset-minutes 30`, causing PSCI `reboot()`;<br>2. **`logd`**: `/private/var/db/diagnostics` owned by `501:20` (expected `272:272`, `0751`) on read-only root -> `EROFS` -> `"BUG IN LIBTRACE: Failed to migrate directory"`;<br>3. **`contextstored`/`donotdisturbd`**: `MobileKeyBag` `MKBEventsRegister` failed without SEP (`AppleKeyStore`);<br>4. **`backboardd`**: uncaught C++ exception in watchdog/global device preference observer due to missing display/SEP services. | 1. Added `--reset-minutes 30` to `scripts/do_boot.py`;<br>2. Planned VFS redirection/attribute spoofing or union mount for `logd` and `/private/var`. |
| **Boot 23** | **Milestone: broke past 90s limit! Ran 300s, spawned 431 processes, `SpringBoard` ran across 6 generations** | 1. Ran full 300s monitor window with zero reboots;<br>2. Captured `1080x2400` `framebuffer.png` showing kernel console text;<br>3. `SpringBoard` reached `job state = running` across 6 generations (`PID 5, 144, 200, 258, 325, 384`);<br>4. Core services (`runningboardd`, `powerd`, `mobiletimerd`, `sleepd`, `passd`, `chronod`) stayed running;<br>5. Background daemons (`locationd`, `mediaserverd`, `contextstored`, `UserEventAgent`, `backboardd`) respawned in loops. | 1. **90s timeout fixed** via 60s refresh packets;<br>2. **`SpringBoard` exits**: clean `exit(255)` (`status 0xffffff00`) triggered when `backboardd` disconnected;<br>3. **Daemon exit breakdown**: `locationd` (61x `SIGABRT`, no GPS/baseband), `mediaserverd` (48x `SIGKILL`, audio watchdog), `donotdisturbd`/`contextstored` (25x `SIGTRAP`, no SEP/keybag), `UserEventAgent` (23x `SIGTRAP`, no system keybag), `logd` (1x `SIGTRAP`, read-only diagnostics). | 1. Verified `--reset-minutes 30`;<br>2. Designed VFS lookup redirection & `vn_stat` spoofing for `logd` plus `EXC_GUARD` / `backboardd` survival patches. |
| **Boot 24** | **Major advance: `runningboardd` survived 300s! Crash rate dropped 51%, `EXC_GUARD` eliminated** | 1. Ran 300s; total exits fell from 431 to 212 (-51%);<br>2. `runningboardd` (PID 5) stayed alive 300s with 0 crashes;<br>3. `SpringBoard` (PIDs `6, 143, 200, 255, 315, 375`) reached `running` every generation, exiting 255 only on `backboardd` disconnect;<br>4. Captured `1080x2400` `framebuffer.png`;<br>5. `logd` (PID 69) and `backboardd` (PID 36) still restarted. | 1. **`EXC_GUARD` suppressed** by `_PROC_VIOLATED_GUARD__SEND_EXC_GUARD` patch;<br>2. **`logd` residue**: real device APFS root had `uid=0, gid=0` (not `501`), `timesync`/`uuidtext`/`.migrated` were missing, and `stat()` called `_lookup` rather than `lookup_check_for_resolve_prefix`;<br>3. **`backboardd` residue**: `p_comm` at offset `0x5d4` (4-byte aligned, not 8-byte), and `SIGABRT` came from Mach exception handling. | 1. Virtualized `logd` paths & ownership in `vn_stat_noauth` and `_lookup`;<br>2. Switched `p_comm` compare to dual 32-bit `ldur` and targeted exit interception. |
| **Boot 25** | `SpringBoard` scheduled stably | `backboardd` still exited 11 times (`SpringBoard` restarted 6 generations); build script missed updating `boot.img` | 1. `backboardd` crashed via Mach exception tail-calling `_exit_with_mach_exception` -> `_exit_with_reason`, bypassing `postsig_locked`;<br>2. `kernel.json` SHA-256 mismatch caused `mkpayload.py` to skip rebuilding the patched kernel. | 1. Unified thread-exit interception at `_exit_with_reason` (`0xfffffff00b238664`);<br>2. Automated `kernel.json` `candidate_sha256` updates. |
| **Boot 26** | `_hook_exit_with_reason` runtime | `panic(cpu 0 caller ...): Mutex 0xfffffff880036058 is unexpectedly not owned by thread ... @lock_mtx.c:148` | **`_hook_exit_with_reason` triggered!** Hook mistakenly treated 5th arg `rwlock_held` as `p->p_mlock` lock ownership and called `proc_unlock(p)` before `_exit_with_reason` ever acquired `p_mlock`. | 1. Removed `proc_unlock(p)` from `L_intercept_thread`;<br>2. Added `kprintf("fuxi: intercepted thread exit in %s\n", ...)` before `_thread_terminate_self()`;<br>3. Rebuilt Boot 27 image. |
| **Boot 27** | VFS lookup hook runtime | `panic: Kernel data abort. at pc 0xfffffff00b62da0c ... far: 0x0000000000000100` | `patch_kernel_boot27.py` refactored `_hook_lookup_prefix` and dereferenced `x1` (`flags=0x100`) via `ldr x2, [x1]`, faulting on `0x100`. | Restored verified `patch_kernel_trampoline.py` implementation (read `x0`, set `*flagsp=0x80000000`, `*prefixlenp=0`); rebuilt Boot 28 image. |

---

## Detailed Failure Deep Dives

### 1. Boot 3–5: Qualcomm Hardware Inline Encryption (`dm-default-key`)
- **Log Symptom**: `FuxiRoot27` failed manifest checksum verification when reading the first 4,096 bytes from UFS storage, seeing random-looking hashes.
- **Root Cause**: Xiaomi 13's `fstab` enables `metadata_encryption=aes-256-xts:wrappedkey_v0`. Normal filesystem writes inside Android/TWRP (`/data/...`) pass through Qualcomm's Inline Crypto Engine (ICE), whereas XNU's UFS SCSI driver issues raw physical-sector DMA reads and therefore reads un-decrypted ciphertext.
- **Resolution**:
  - Queried the file's physical F2FS sector extents (`FIEMAP`).
  - Wrote native writer tools (such as `scratch/stream_extents_dev`) to open `/dev/block/sda32` directly and write plaintext strictly to the mapped physical extents while `userdata` is unmounted.

---

### 2. Boot 7: Closed-Source Apple APFS Kext UPL ABI Mismatch
- **Log Symptom**:
  ```text
  fuxi: root volume authentication skipped (fuxi_root27_norootauth=1)
  Debugger synchronization timed out
  panic(cpu 0 caller 0xfffffff00b5a2878): Kernel data abort. at pc 0xfffffff00afbc080, lr 0xfffffff00afbc070
  far: 0x0fffffff00055f9a
  ```
- **Root Cause**:
  Apple's precompiled `com.apple.filesystems.apfs` kext from iOS 16/17 kernelcache calls `upl_page_present(pl, page)` during `vnop_read`. Field offsets in `struct upl` differ between Apple's internal kernelcache build and open-source `xnu-12377`, dereferencing bogus address `0x0fffffff00055f9a`.
- **Resolution**:
  - Added `--drop-apfs` to `tools/ios27-prelink.py` to exclude Apple's closed-source APFS kext.
  - Enabled XNU's in-tree read-only APFS module (Patch 0008, `hakios-arm64e-dada`), providing `apfs_vfsops` / `apfs_vnops` without UPL ABI conflicts.

---

### 3. Boot 8: Root Device UUID Mismatch (`root-matching`)
- **Log Symptom**:
  ```text
  Waiting on <dict ID="0"><key>IOProviderClass</key><string ID="1">IOMedia</string>
  <key>IOPropertyMatch</key><dict ID="2"><key>UUID</key><string ID="3">DADD93F8-DBBF-4B17-A1DF-0F11E64172F7</string></dict></dict>
  ```
- **Root Cause**:
  - Apple's APFS kext enumerates child `IOMedia` volumes inside an APFS container using the volume UUID (`DADD93F8...`).
  - Under built-in Dada-APFS, `FuxiRoot27` exposes `disk0` using the OS window's SHA-256-derived UUID (`2ABE836E-EB6D-4C24-B639-FDEDDD5154B2`).
  - Because `/chosen/root-matching` in the ADT still expected `DADD93F8...`, `IOFindBSDRoot` waited indefinitely.
- **Resolution**:
  Passed `--root-uuid 2ABE836E-EB6D-4C24-B639-FDEDDD5154B2` when generating the ADT so `IOFindBSDRoot` matches `disk0` directly.

---

### 4. Boot 9: AMFI CoreTrust Policy & Missing TrustCache
- **Log Symptom**:
  ```text
  apfs: volume 0 "SydneyUpdate20H392.D22D221OS" ... 142313 files
  fuxi: cryptex SystemOS (disk2s1) at /private/preboot/Cryptexes/OS: 0
  fuxi: cryptex SystemOS (disk2s1 /System/Library/Caches/com.apple.dyld) at /System/Library/Caches/com.apple.dyld: 0
  fuxi: cryptex AppOS (disk1s1) at /private/preboot/Cryptexes/App: 0
  load_init_program: attempting to load /sbin/launchd
  AMFI: '/sbin/launchd': unsuitable CT policy 0 for this platform/device, rejecting signature.
  AMFI: '/usr/lib/dyld': unsuitable CT policy 0 for this platform/device, rejecting signature.
  AMFI: hook..execve() killing init (pid 1): dyld signature cannot be verified.
  panic(cpu 0 caller ...): unexpected SIGKILL of launchd
  ```
- **Root Cause**:
  - AMFI (`AppleMobileFileIntegrity`) requires core iOS executables (`/sbin/launchd`, `/usr/lib/dyld`) to have their `cdhash` registered in an external or static TrustCache.
  - Boot 9 omitted `--trustcache` when running `mkpayload.py`, leaving `no external trust caches found` and triggering `SIGKILL` on PID 1.
- **Resolution**:
  - Extracted 3 official TrustCache files from firmware assets:
    - `087-86698-044.dmg.trustcache` (OS volume: 2,760 entries including `launchd` and `dyld`)
    - `087-86593-047.dmg.trustcache` (SystemOS volume: 61 entries)
    - `087-86715-047.dmg.trustcache` (AppOS volume: 30 entries)
  - Merged all 2,851 entries into `resources/ios27.tc` using `tools/ios27-root.py trust-bundle` and passed `--trustcache <WORKSPACE>/resources/ios27.tc` when building `payload27-dada.bin`.

---

### 5. Boot 10: Entering iOS 17 `launchd` Userland & `EXC_GUARD`
- **Log Symptom**:
  ```text
  shared_region: 0x944236b6fcf57791 [1(launchd)] check_np(0x16f0f6b90) vm_shared_region_start_address() returned 0x1
  com.apple.xpc.launchd|1970-01-01 00:01:10.455785 <Notice>: boot-mode set by sysctl: main
  com.apple.xpc.launchd|1970-01-01 00:01:10.461709 <Notice>: hello
  com.apple.xpc.launchd|1970-01-01 00:01:10.462398 <Notice>: Darwin Bootstrapper Version 7.0.0: Thu Feb  1 20:33:09 PST 2024; root:libxpc_executables-2462.140.4.702.1~1/launchd/RELEASE_ARM64
  com.apple.xpc.launchd|1970-01-01 00:01:10.463011 <Notice>: boot-args = ...
  ERROR: [launchd:1] EXC_GUARD AST: type=0x1 flavor=0x43 target=0x800407 code=0x2000004300800407 subcode=0x300000000000011
  ERROR: [launchd:1] FATAL exception: type=0xc reason=0x17 code=0x2000004300800407 subcode=0x300000000000011
  [launchd: killed] exiting with signal 9, force exiting the process
  pid 1 exited -- exit reason namespace 23 subcode 0x2000004300800407
  ```
- **Root Cause**:
  - **Milestone**: iOS 17 `/sbin/launchd` and `dyld` loaded, bound `shared_region`, and printed `"hello"` and `Darwin Bootstrapper Version 7.0.0`.
  - Checking `sysctlbyname("kern.bootargs")` without `rd=md0`, `launchd` ran full hardware container/`fsck`/SEP checks, hitting missing IOKit container objects and triggering `EXC_GUARD`.
- **Resolution**:
  - Added `fuxi_launchd_ramdisk=1` (per Patch 0018, appends ` rd=md0` when userland queries `kern.bootargs`) and `fuxi_proc_log=1` for process exit stack logging.

---

### 6. Boot 11: Full `dyld_shared_cache` Load & Strict Reply Port Exception
- **Log Symptom**:
  ```text
  fuxi: fcntl pid 1 fd 1 cmd 97 /System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64 -> 0
  ...
  fuxi: fcntl pid 1 fd 43 cmd 97 /System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64.42.dyldlinkedit -> 0
  com.apple.xpc.launchd: boot-args = ... rd=md0
  com.apple.xpc.launchd: Restore environment starting.
  ERROR: [launchd:1] EXC_GUARD AST: type=0x1 flavor=0x43 target=0x800407 code=0x2000004300800407 subcode=0x300000000000011
  ERROR: [launchd:1] FATAL exception: type=0xc reason=0x17 code=0x2000004300800407 subcode=0x300000000000011
  [launchd: killed] exiting with signal 9, force exiting the process
  fuxi: exit pid 1 launchd status 0x9 ns 23 code 0x2000004300800407
  panic(cpu 0 caller 0xfffffff00b5ce150): initproc exited -- exit reason namespace 23 subcode 0x2000004300800407
  ```
- **Root Cause**:
  - All 43 Cryptex `dyld_shared_cache` slices registered cleanly via `fcntl(F_ADDFILESIGS_RETURN)` and `launchd` reached `Restore environment starting.`.
  - `type=0x1` (`GUARD_TYPE_MACH_PORT`), `flavor=0x43` (`kGUARD_EXC_STRICT_REPLY` `0x40` | `kGUARD_EXC_MOD_REFS` `0x02` | `kGUARD_EXC_DESTROY` `0x01`): XNU `DEVELOPMENT` defaults `task_exc_guard_default` to strict Mach port guard AST traps.
- **Resolution**:
  - Added `task_exc_guard_default=0` to kernel cmdline.

---

### 7. Boot 12: SMP Cross-Core `SIGP` Assertion Panic
- **Log Symptom**:
  ```text
  panic(cpu 5 caller 0xfffffff00b5a2878): cpu_common.c:946 Assertion failed: getCpuDatap()->cpu_signal == SIGPdisabled (0x8 == 0x80000000, 8 == 2147483648)
  at pc 0xfffffff00b5a0c80, lr 0xfffffff00aee74d4 (saved state: 0xfffffffb2cd9cb70)
  ```
- **Root Cause**:
  Under `cpus=7`, SM8550's GICv3 distributor intermittently dropped IPI signals during secondary core wakeup/sync, leaving CPU 5's `cpu_signal` inconsistent at `cpu_common.c:946`.
- **Resolution**:
  Per `docs-lanes/ios27.md`, switched to single-core bring-up (`--cpus 1` in `fuxi27-root.adt`, `cpus=1` in cmdline), keeping core 0 for XNU and `cpu@100` for the USB monitor.

---

### 8. Boot 13: Mach Port Security Policy (`ool_port_array_enforced` / Policy 7) Killing `launchd`
- **Log Symptom**:
  ```text
  com.apple.xpc.launchd: boot-args = ... rd=md0
  com.apple.xpc.launchd: Restore environment starting.
  ERROR: [launchd:1] EXC_GUARD AST: type=0x1 flavor=0x43 target=0x800407 code=0x2000004300800407 subcode=0x300000000000011
  ERROR: [launchd:1] FATAL exception: type=0xc reason=0x17 code=0x2000004300800407 subcode=0x300000000000011
  [launchd: killed] exiting with signal 9, force exiting the process
  fuxi: exit pid 1 launchd status 0x9 ns 23 code 0x2000004300800407 
  pid 1 exited -- exit reason namespace 23 subcode 0x2000004300800407, description none
  ```
- **Disassembly Findings**:
  1. Decompiling iOS 17 `/sbin/launchd` after `"Restore environment starting."`: it calls `_setsid`, `_chdir("/")`, `_setlogin("root")`, `_mach_ports_register(task, &port, 1)`, and `_xpc_mach_send_create_with_disposition(port, 0x11)`.
  2. In XNU `_ipc_sec_policy_array`, Policy 7 (`IPC_POLICY_OOL_PORT_ARRAY`) checks `_ool_port_array_enforced` (default `1` in `DEVELOPMENT`), requiring `MACH_MSG_TYPE_COPY_SEND` (`0x13`), whereas `launchd` passed `0x11` (`MACH_MSG_TYPE_MOVE_SEND`).
  3. `_ipc_triage_policy_violation` selected `action = 3` (guard exception) -> `_mach_port_guard_exception` set `AST_GUARD` -> `_mach_port_guard_ast` saw `flavor <= 0x80`, bypassed `task_exc_guard_default=0`, and killed PID 1 with `SIGKILL`.
- **Resolution**:
  1. Created `scripts/patch_kernel_guard.py`:
     - Set `_ool_port_array_enforced` (offset `0xde119b`) from `0x01` to `0x00`.
     - Set Policy 7 (`0xde19f0`) and Policy 4 actions in `_ipc_sec_policy_array` from `0x03` to `0x01` (ignore).
     - Changed `b.hi +0x28` in `_mach_port_guard_ast` (offset `0x3cac900`) to unconditional `b +0x28` so `task_exc_guard_default=0` applies uniformly.
     - Updated `kernel.json` SHA-256.
  2. Added `ool_port_array_enforced=0 enforce_strict_reply=0 sheng-no-lc=1` to cmdline.

---

### 9. Boot 14: Inheritance Port Registration Failure (`could not set up inheritance port`)
- **Log Symptom**:
  ```text
  com.apple.xpc.launchd: Restore environment starting.
  fuxi: sig 6 pid 1 pc 0x1eee4a8c0 lr 0x1eee6bb48 fp 0x16f9b8990 x0 0x7 x1 0x1 x2 0x0 slide 0x2c82c000
  fuxi: bt 0: 0x1c261e8c0 0x1c263fb48 0x1c263fae4 0xd3c5840c
  fuxi: bt 4: 0xd3c31f4c 0xd3f84344 0x0 0x0
  fuxi: exit pid 1 launchd status 0x6 ns 7 code 0x1 could not set up inheritance port
  pid 1 exited -- exit reason namespace 7 subcode 0x1, description could not set up inheritance port
  panic(cpu 0 caller 0xfffffff00b5ce150): initproc exited -- exit reason namespace 7 subcode 0x1 description: could not set up inheritance port
  ```
- **Disassembly Findings**:
  1. `EXC_GUARD` was gone; `launchd` itself called `abort_with_reason(7, 1, "could not set up inheritance port", 0)` (`SIGABRT`, namespace `7`).
  2. In `launchd` at `0x100016e14`:
     ```arm64
     0x100016e00: mov  x19, x0                 ; inheritance port
     0x100016e04: str  w0, [sp, #0x20]
     0x100016e08: ldr  w0, [x20]               ; mach_task_self_
     0x100016e0c: add  x1, sp, #0x20          ; &inheritance_port
     0x100016e10: mov  w2, #0x1                ; count = 1
     0x100016e14: bl   _mach_ports_register
     0x100016e18: cbnz w0, 0x100016f40
     ...
     0x100016f1c: bl   _dispatch_activate
     0x100016f20: bl   _dispatch_main
     ...
     0x100016f40: adr  x0, "could not set up inheritance port"
     0x100016f48: bl   abort_with_reason(7, 1, x0, 0)
     ```
  3. In XNU `_kernelrpc_mach_ports_register3` (`0xfffffff00ace2954`), `ipc_can_stash_naked_send` (`0xfffffff00acb0490`) returned `0`, returning `0x11` (`KERN_POLICY_LIMIT`).
- **Resolution (Boot 15)**:
  1. Wrote `scripts/patch_kernel_inheritance.py`:
     - Patched `ipc_can_stash_naked_send` (offset `0x3cac490`) to `pacibsp; mov w0, #1; retab; nop`.
     - NOPed conditional rejection branches (`0x3cde98c`, `0x3cde998`, `0x3cde9a4`) and active-state check (`0x3cde9b4`) in `_kernelrpc_mach_ports_register3`.
  2. Updated `candidate_sha256` in `kernel.json` and rebuilt payload/boot image.

---

### 10. Boot 15: MIG Demux Check Failure (`MIG_BAD_ARGUMENTS`)
- **Log Symptom**:
  ```text
  com.apple.xpc.launchd|1970-01-01 00:01:05.778496 <Notice>: Restore environment starting.
  fuxi: sig 6 pid 1 pc 0x1de9328c0 lr 0x1de953b48 fp 0x16f0af990 x0 0x7 x1 0x1 x2 0x0 slide 0x1c314000
  fuxi: exit pid 1 launchd status 0x6 ns 7 code 0x1 could not set up inheritance port
  pid 1 exited -- exit reason namespace 7 subcode 0x1, description could not set up inheritance port
  panic(cpu 0 caller 0xfffffff00b5ce150): initproc exited -- exit reason namespace 7 subcode 0x1 description: could not set up inheritance port
  ```
- **Disassembly Findings**:
  1. In MIG server demux `__X_kernelrpc_mach_ports_register3` (`0xfffffff00adb1204`, file offset `0x3dad204`):
     ```arm64
     0xfffffff00adb1214: ldr  w8, [x0]
     0xfffffff00adb1218: tbz  w8, #0x1f, #0xfffffff00adb12ac  ; complex message check
     0xfffffff00adb121c: ldr  w8, [x0, #0x20]
     0xfffffff00adb1220: cmp  w8, #3                           ; descriptor count == 3
     0xfffffff00adb1224: b.ne #0xfffffff00adb12ac
     0xfffffff00adb1228: ldr  w8, [x0, #4]
     0xfffffff00adb122c: cmp  w8, #0x54                        ; msgh_size == 84
     0xfffffff00adb1230: b.ne #0xfffffff00adb12ac
     ```
  2. Root cause: in `osfmk/mach/task.defs`, `LIBSYSCALL_INTERFACE` compiles userland `libsystem_kernel.dylib` to send 1 **OOL port array** descriptor (`type = 2, count = 1`), whereas the kernel was built without `LIBSYSCALL_INTERFACE` and demanded 3 inline descriptors (`count = 3, size = 0x54`). Demux immediately returned `-304` (`MIG_BAD_ARGUMENTS`).
- **Resolution (Boot 16)**:
  1. At `__X_kernelrpc_mach_ports_register3` (`0x3dad214`, `0xfffffff00adb1214`), jumped unconditionally (`b #0xfffffff00adb12ac`, `26000014`) to epilogue and forced `mov w8, #0` (`08008052`) at `0xfffffff00adb12ac` and `0xfffffff00adb12d4`.
  2. Rebuilt Boot 16 kernel, payload, and boot image.

---

### 11. Boot 18: Kernel Heap Isolation Confusion Panic (`kfree_heap_confusion_panic`)
- **Log Symptom**:
  ```text
  panic(cpu 0 caller 0xfffffff00b5670c0): kfree: addr 0xfffffe8000456c60, size 24 found in heap data.kalloc.32 instead of default.kalloc.32 @kalloc.c:2783
  Debugger synchronization timed out
  ```
- **Root Cause**:
  Boot 17's `mach_ports_lookup3` OOL reply buffer was allocated with `kalloc_data(24, 0)` (`KHEAP_DATA_BUFFERS`), while `ipc_kmsg_copyout_descriptors` freed it via `kfree_ext` expecting `ipc_kmsg_copyout_ool_ports_descriptor.kalloc_type_view_3960 | 1` (`KHEAP_DEFAULT`).
- **Resolution**:
  1. Updated `scripts/patch_kernel_lookup.py` to allocate with `kalloc_ext(ipc_kmsg_copyout_ool_ports_descriptor.kalloc_type_view_3960 | 1, 24, 0, 0)`.
  2. Patched `kfree_zone` heap check (`0x3ce38e4`, `0xfffffff00ace78e4`) from `b.eq +0x18` to `b +0x18` (`0x14000006`).

---

### 12. Boot 19: Child Process Crash `"Configuration error: Invalid bootstrap port."`
- **Log Symptom**:
  ```text
  fuxi: sig 5 pid 300 pc 0x1fca598ec lr 0x1fca41080 fp 0x16f078530 x0 0x100def000 x1 0x200000003 x2 0x1800001513 slide 0x2ae48000
  fuxi: bt 0: 0x1d1c118ec 0x1d1bf9080 0x1d1c2d79c 0x1a463842c
  fuxi: exit pid 300 xpcproxy status 0x5 ns 2 code 0x5 
  com.apple.xpc.launchd|1970-01-01 00:01:45.499630 (user/501/com.apple.runningboardd [300]) <Notice>: xpcproxy exited due to SIGTRAP | sent by exc handler[300]
  ```
- **Disassembly Findings**:
  1. Boot 19 emitted 1.19 MB of console logs with zero kernel panics.
  2. Unslid `0x1d1c118ec` (`brk #1`) in `dyld_shared_cache_arm64.25` referenced `"Configuration error: Invalid bootstrap port."` in `libxpc`:
     ```arm64
     bl mach_ports_lookup(mach_task_self(), &ports, &count)
     ldr w9, [ports]
     add w9, w9, #1
     cmp w9, #1
     b.ls crash_invalid_bootstrap_port
     ```
  3. Because Boot 16 skipped calling `_kernelrpc_mach_ports_register3`, `launchd->itk_registered[0]` stayed `NULL`, so children inherited `ports[0] = 0`.
- **Resolution (Boot 20)**:
  Wrote `scripts/patch_kernel_register.py` to replace `__X_kernelrpc_mach_ports_register3` (`0xfffffff00adb1204`, 312B padded to 356B):
  1. Unpack userland OOL port array descriptor;
  2. PAC-authenticate buffer pointer (key `0x25da`) and port pointers (key `0x362f`);
  3. Call native `_kernelrpc_mach_ports_register3(target_task, port0, port1, port2)` to populate `target_task->itk_registered[0]`;
  4. Zero `count` (`str wzr, [x19, #0x30]`) so `ipc_kmsg_clean_descriptors` frees the temporary buffer without destroying send rights;
  5. Release task reference via `task_deallocate_grp(target_task, 2)` and return standard MIG reply (`RetCode = 0`, `msgh_size = 0x2c`).

---

### 13. Boot 20: `launchd` Again Reported `could not set up inheritance port`
- **Log Symptom**:
  ```text
  fuxi: sig 6 pid 1 pc 0x1f0d368c0 lr 0x1f0d57b48 fp 0x16ee2b990 x0 0x7 x1 0x1 x2 0x0 slide 0x1e718000
  fuxi: exit pid 1 launchd status 0x6 ns 7 code 0x1 could not set up inheritance port
  pid 1 exited -- exit reason namespace 7 subcode 0x1, description could not set up inheritance port
  panic(cpu 0 caller 0xfffffff00b5ce150): initproc exited -- exit reason namespace 7 subcode 0x1 description: could not set up inheritance port
  ```
- **Root Cause**:
  `launchd` passed `count = 1`, whereas initial `patch_kernel_register.py` required `cmp w11, #3; b.ne Lbad_args`, returning `-304` (`MIG_BAD_ARGUMENTS`).
- **Resolution (Boot 21)**:
  Updated `scripts/patch_kernel_register.py` to accept `0 <= count <= 3` (`cmp w11, #3; b.hi Lbad_args`), zero-initialize 3 stack slots, PAC-authenticate `count` entries, call `_kernelrpc_mach_ports_register3`, and release references cleanly.

---

### 14. Boot 21: All Userland Processes Exec'd; `SpringBoard` Crashed on Missing `libobjc-trampolines.dylib`
- **Log Symptom**:
  `launchd` entered `dispatch_main`, `xpcproxy` exited cleanly (`status 0x0`), and services launched:
  ```text
  fuxi: exec pid 128 /System/Library/CoreServices/SpringBoard.app/SpringBoard: 0
  fuxi: exec pid 132 /System/Library/PrivateFrameworks/SleepDaemon.framework/sleepd: 0
  fuxi: exec pid 134 /usr/sbin/mDNSResponder: 0
  com.apple.xpc.launchd (user/501/com.apple.runningboardd [5]) <Notice>: job state = running
  com.apple.xpc.launchd (user/501/com.apple.powerd [19]) <Notice>: job state = running
  ```
  ObjC processes then aborted:
  ```text
  fuxi: exit pid 128 SpringBoard status 0x6 ns 8 code 0x1 couldn't dlopen libobjc-trampolines.dylib: dlopen(/usr/lib/libobjc-trampolines.dylib, 0x0106): tried: '/usr/lib/libobjc-trampolines.dylib' (no such file, not in dyld cache)
  Process[128] crashed: SpringBoard. Too many corpses being created.
  ```
- **Root Cause**:
  `libobjc-trampolines.dylib` and `libffi-trampolines.dylib` reside in SystemOS Cryptex (`/private/preboot/Cryptexes/OS/usr/lib/`). With `dyld_flags=8`, `dyld` opened `/usr/lib/...` directly without a root symlink and received `ENOENT`.
- **Resolution (Boot 22)**:
  1. Verified CDHashes in `resources/ios27.tc` (`libobjc-trampolines.dylib`: `67c97863...`, `libffi-trampolines.dylib`: `f66d0b31...`).
  2. Created `scripts/patch_kernel_trampoline.py` hooking `lookup_check_for_resolve_prefix` (`0xfffffff00af614e0`) to rewrite those lookups in place to `/private/preboot/Cryptexes/OS/usr/lib/...`.

---

### 15. Boot 22: Historic Breakthrough — `SpringBoard` Spawned & Ran Stably; Daemon Analysis
- **Log Symptom**:
  - Trampoline redirection hit cleanly; `SpringBoard` (PID 5) entered `service state: running` with zero crashes.
  - Active services included `com.apple.CommCenter` (PID 65), `com.apple.mobiletimerd` (PID 27), `com.apple.logd_helper` (PID 71, exited `0x0`), `coresymbolicationd`, and `bluetoothd`.
  - Device rebooted to Fastboot/Charging after ~85–90 seconds.
- **Root Cause Analysis**:
  1. **90s Auto-Reboot**: `ios-fuxi/shim/fuxi-probe/probe.c:1472` initialized `monitor_report[MON_DEADLINE] = cntpct_el0 + cntfrq_el0 * 90`, and line 795 called PSCI `reboot()` once expired because `scripts/do_boot.py` omitted `--reset-minutes 30` (command `0x54`).
  2. **`logd` (`SIGTRAP` / `0x100b25160`)**: `/usr/libexec/logd` function `0x100016538` checked `/private/var/db/diagnostics` and `/private/var/db/uuidtext` expecting `uid=272, gid=272, mode=0751` and `.migrated`; on read-only root it hit `EROFS` (30) -> `"BUG IN LIBTRACE: Failed to migrate directory"` -> `brk #1`.
  3. **`contextstored` & `donotdisturbd` (`SIGTRAP` / `0x1ae4068c0`)**: `MKBEventsRegister` failed without SEP (`AppleKeyStore`) and `/private/var/keybags/systembag.kb`.
  4. **`backboardd` (`SIGABRT` / `0x1c2617198`)**: Uncaught ObjC/C++ exception in `addGlobalDevicePreferencesObserver:` (`_dispatch_client_callout`) due to missing `CADisplay` / `IOMobileFramebuffer`.

---

### 16. Boot 23: Milestone — Passed 90s Limit, Ran 300s, Spawned 431 Processes, 6-Gen `SpringBoard`
- **Configuration Change**: Added `--reset-minutes 30` in `scripts/do_boot.py` (refresh packet `0x54` every 60s).
- **Observed Results**:
  1. **Zero 90s Reboot**: Ran the full 300-second (5-minute) monitor session cleanly.
  2. **Scale**: Spawned **431 processes (max PID 432)** while PID 1 maintained 12 worker threads.
  3. **`SpringBoard` across 6 generations**: PIDs `5, 144, 200, 258, 325, 384` all reached `job state = running`; each exit was clean `status 0xffffff00` (exit 255) when `backboardd` exited.
  4. **Stable Core Daemons**: `runningboardd` (6), `powerd` (19), `mobiletimerd` (27), `sleepd` (49), `passd` (53), `chronod` (75, 143, 201...), `cloudkeychainproxy3` (98).
  5. **Native `1080x2400` Framebuffer Capture**: Captured `resources/boot23-logs/framebuffer.png` and `framebuffer.bgra` (9.9 MB), verifying 4,165 sampled text pixels across `x=[0, 1060], y=[10, 2390]`.
- **Crash Taxonomy**:
  | Binary Path | Count | Signal | Root Cause |
  |---|---|---|---|
  | `/usr/libexec/locationd` | 61 | `SIGABRT` (6) | Missing Qualcomm GPS/baseband client. |
  | `/usr/sbin/mediaserverd` | 48 | `SIGKILL` (9) | Audio watchdog timeout (no Apple Audio DSP). |
  | `donotdisturbd` | 25 | `SIGTRAP` (5) | Missing SEP `AppleKeyStore` and `/private/var/keybags/systembag.kb`. |
  | `contextstored` | 25 | `SIGTRAP` (5) | Missing SEP `AppleKeyStore` and `/private/var/keybags/systembag.kb`. |
  | `/usr/libexec/UserEventAgent` | 23 | `SIGTRAP` (5) | Missing system keybag and `/private/var` write access. |
  | `/usr/libexec/backboardd` | 11 | `SIGABRT` (6) | C++ exception in global device preferences observer without Display/SEP. |
  | `ACCHWComponentAuthService` | 11 | `SIGKILL` (9) | Missing Lightning/MFi auth hardware. |
  | `/usr/libexec/lockdownd` | 3 | `SIGTRAP` (5) | Missing pairing records and keybag. |
  | `/usr/libexec/lsd` | 2 | `SIGABRT` (6) | Unable to write LaunchServices DB in `/private/var/db/lsd`. |
  | `/usr/libexec/logd` | 1 | `SIGTRAP` (5) | Read-only `/private/var/db/diagnostics` lacking `.migrated`. |

---

### 17. Boot 24: `runningboardd` Survived 300s; Exits Dropped 51%; `EXC_GUARD` Eliminated
- **Patches (`scripts/patch_kernel_boot24.py`)**:
  1. Hooked `_lookup_check_for_resolve_prefix`;
  2. Hooked `_vn_stat_noauth` at `0xfffffff00af909e4`;
  3. Hooked `postsig_locked` at `0xfffffff00b257d8c`;
  4. Replaced `_PROC_VIOLATED_GUARD__SEND_EXC_GUARD` at `0xfffffff00ad3046c` with `pacibsp; mov w0, #0; retab; nop`.
- **Results**:
  - `runningboardd` (PID 5) stayed alive all 300s with **0 crashes / 0 restarts**.
  - Total process exits fell from 431 to 212 (-51%).
  - `SpringBoard` (PIDs `6, 143, 200, 255, 315, 375`) ran across 6 generations, exiting 255 only on `backboardd` disconnect.
  - Captured `resources/boot24-logs/framebuffer.png` (`1080x2400`, 118 KB).
- **Remaining Findings**:
  - On real device APFS, `/private/var/db/diagnostics` was owned by `uid=0, gid=0` (not `501`), `timesync`/`uuidtext`/`.migrated` did not exist, and normal `stat()` called `_lookup` rather than `_lookup_check_for_resolve_prefix`.
  - `p->p_comm` at offset `0x5d4` is 4-byte aligned, requiring dual 32-bit `ldur` loads.

---

### 18. Boot 25: `logd` Survived 285s (0 Crashes); Located `backboardd` True Exit Path
- **Patches (`scripts/patch_kernel_boot25.py`)**:
  1. In-place path truncation at `0xfffffff00af60018` (`_hook_namei`) redirecting `.migrated`, `timesync`, `uuidtext` to parent directory `"."`;
  2. Spoofed `st_uid=272, st_gid=272, mode=0751/0755` for `logd` at `0xfffffff00af909e4` (`_hook_vn_stat`);
  3. Hooked `postsig_locked` (`0xfffffff00b257d8c`) and `_PROC_VIOLATED_GUARD__SEND_EXC_GUARD` (`0xfffffff00ad3046c`).
- **Results**:
  - `logd` (PID 72) entered `running` and stayed alive for the remaining 285 seconds until monitor completion with **0 crashes**.
  - `runningboardd` (PID 6) stayed alive all 300 seconds, absorbing 23 `EXC_GUARD AST` events.
  - `SpringBoard` ran across 6 generations (PIDs `5, 143, 199, 258, 321, 380`); captured `resources/boot25-logs/framebuffer.png` (`1080x2400`, 124 KB).
- **True `backboardd` Exit Path**:
  `backboardd` aborted inside a GCD worker (`abort()` -> `__pthread_kill`), which ran `ux_exception` -> `_exit_with_fatal_exception_and_notify` -> `_exit_with_mach_exception` (`0xfffffff00b23b3a8`), tail-calling (`b 0xfffffff00b238664`) into `_exit_with_reason` and completely bypassing `postsig_locked`.
- **Boot 26 Plan**:
  Hook `_exit_with_reason` (`0xfffffff00b238664`) directly so crashing threads in `backboardd` / `logd` terminate only the crashing thread via `_thread_terminate_self()` (`0xfffffff00ad3b028`), leaving the main process and Mach ports alive.

---

### 19. Boot 26: `_exit_with_reason` Hook Triggered; Mutex Panic from Spurious `proc_unlock`
- **Patches (`scripts/patch_kernel_boot26.py`)**:
  Hooked `_exit_with_reason` (`0xfffffff00b238664`) redirecting `backboardd` / `logd` (`sig 5/6`) to `L_intercept_thread`.
- **Log Symptom**:
  `notifyd:70` survived `EXC_GUARD AST`. When `logd` (PID 69) hit `sig 5`, `_hook_exit_with_reason` fired, immediately triggering:
  ```text
  fuxi: sig 5 pid 69 pc 0x10014f160 lr 0x10014f044 fp 0x16fcc8550 x0 0x1e x1 0x103 x2 0x103 slide 0x3824000
  fuxi: bt 0: 0xfc92b160 0xfc92b044 0xfc91ce04 0x1a4624344
  panic(cpu 0 caller 0xfffffff00b567b8c): Mutex 0xfffffff880036058 is unexpectedly not owned by thread 0xfffffff799a64d20 @lock_mtx.c:148
  ```
- **Root Cause**:
  At entry to `exit_with_reason` (`0xfffffff00b238664`), `proc_lock(p)` has **not** yet been acquired (acquired later at `0xfffffff00b2386f8`); 5th argument `w4` is `rwlock_held`, not `p_mlock`. Calling `proc_unlock(p)` on an unowned mutex triggered `@lock_mtx.c:148`.
- **Resolution (Boot 27)**:
  Removed `proc_unlock` from `L_intercept_thread`, printed `kprintf("fuxi: intercepted thread exit in %s\n", p->p_comm)`, and called `_thread_terminate_self()` (`0xfffffff00ad3b028`) lock-free.

---

### 20. Boot 27: `_hook_lookup_prefix` Register Confusion Data Abort (`far: 0x100`)
- **Log Symptom**:
  ```text
  panic(cpu 0 caller 0xfffffff00b5a2878): Kernel data abort. at pc 0xfffffff00b62da0c, lr 0x59e982f00af60334 (saved state: 0xfffffffacf894730)
        x0:  0xfffffff3979d5648 x1:  0x0000000000000100  x2:  0x0000000000000019  x3:  0xfffffffacf894adc
        pc:  0xfffffff00b62da0c cpsr: 0x62400204         esr: 0x0000000096000004  far: 0x0000000000000100
  ```
- **Root Cause**:
  At `0xfffffff00af6031c..30`, `x0` is the path buffer, `x1` is `flags` (`0x100 = CN_RESOLVE_PREFIX`), `w2` is `pathlen`, `x3` is `flagsp`, and `x4` is `prefixlenp`. `patch_kernel_boot27.py` dereferenced `x1` (`ldr x2, [x1]`), faulting on `0x100`.
- **Resolution (Boot 28)**:
  Restored the verified `_hook_lookup_prefix` from `patch_kernel_trampoline.py` (`x0` prefix matching, `*flagsp = 0x80000000`, `*prefixlenp = 0`) while retaining Boot 27's lock-free `_hook_exit_with_reason`. Executed `scripts/patch_kernel_boot28.py` (`candidate_sha256` `4201199c...`).

---

### 21. Boot 28: Zero Panics for 300+ Seconds; `SpringBoard`/`backboardd` Survived; Headless Mode Diagnosed
- **Execution Summary**:
  - Completed full 300-second run (`exit 0`, zero panics, zero watchdog timeouts), capturing `boot.log` (568 KB), `framebuffer.png` (125 KB), `display-after.bin` (432 B), `native-report.bin` (152 B), and `progress.jsonl` (355 KB).
  - `SpringBoard` (PID 6), `backboardd` (PID 36), `runningboardd` (PID 5), and `logd` (PID 69) all stayed `RUNNING` with **0 exits** across 300s (101+ PIDs spawned, 68 background services resident).
- **Why No UI Rendered**:
  1. **Headless Mode**: `backboardd` checks `StartWindowServer: headless (display:%u/server:%u)` via `IOMobileFramebuffer` enumerating `/arm-io` `device_type == "display-subsystem"`. `ios-fuxi/tools/mkadt-fuxi27.py` only populated `intc` under `/arm-io` and omitted `/arm-io/disp0`, forcing `BKDisplayIsHeadless = true`.
  2. **Console Overwrite (`PE_Video_Console`)**: Boot-arg `-v` kept early console bound to `0xb8000000`, while missing `ios27.tc` injection caused `mediaserverd` AMFI rejections (`0x8`) every 5s.
  3. **Missing ADT Properties**: `/arm-io/wdt` lacked `no-pmu: 1`, `/device-tree/buttons` lacked `home-button-type: 2`, and `/device-tree/defaults` lacked `no-effaceable-storage: 1`.

---

### 22. Boot 29: ADT Display Node Injection (`disp0`/`wdt`/`buttons`), Full TrustCache & Console Quieting
- **Applied Fixes**:
  1. **Updated `ios-fuxi/tools/mkadt-fuxi27.py`**:
     - Added `/arm-io/disp0` (`device_type = 'display-subsystem'`, `compatible = 'sweet,display'`, `canvas-width = 1125`, `canvas-height = 2436`).
     - Added `/arm-io/wdt` (`no-pmu = 1`), `/device-tree/buttons` (`home-button-type = 2`, `opposed-power-vol-buttons = 1`), and `/device-tree/defaults` (`no-effaceable-storage = 1`).
     - Regenerated `resources/fuxi27-root.adt` (20,576 bytes, 357 extents).
  2. **Static TrustCache Injection**:
     - Added `--trustcache resources/ios27.tc` in `mkpayload.py`, registering `TrustCache` (`<0x8c6b24000, 0x10ba0>`, 3 modules) in `/chosen/memory-map`.
  3. **Console Quieting**:
     - Added `sweetfb_noconsole=1` to boot-args.
  4. **Repacked & Launched**:
     - Rebuilt `resources/payload27-dada.bin` (93,528,560 bytes) and `fuxi-xnu-boot.img`, verified with `scripts/watch_and_boot29.py`.
