# Xiaomi 13 (`fuxi` / SM8550) iOS 16.7.10 (Sydney 20H392) Cross-Platform Handover Guide (Windows)

This directory contains the boot package, device images, helper scripts, and complete engineering fix logs handed over from macOS to Windows.

---

## 1. Current Status & Milestones (As of Boot 29)

- **Target Device**: Xiaomi 13 (`fuxi`, Snapdragon 8 Gen 2 / SM8550), serial `<DEVICE_SERIAL>`.
- **RAM-Only Boot Guarantee (Zero-Flash)**:
  - Kernel boot is loaded strictly into RAM via `fastboot boot fuxi-xnu-boot.img`.
  - **Never modifies** Android stock partitions (`boot`, `vendor_boot`, `recovery`, `system`, `vendor`, etc.).
  - Rebooting the device (holding the Power button) cleanly returns to the original Android / MIUI system.
- **Root Filesystem**:
  - Pre-written to UFS 4.0 physical partition `/dev/block/sda32`.
  - Contains the iOS 16.7.10 APFS container with UUID `2ABE836E-EB6D-4C24-B639-FDEDDD5154B2`.
- **Latest Boot Milestone (Boot 29 Breakthrough)**:
  1. **Zero Kernel Panics**: Ran continuously for 300+ seconds while collecting full logs; kernel and watchdog remained 100% stable.
  2. **Core UI Userland Processes Stay Alive**:
     - `SpringBoard` (PID 6): Spawned and remained in `RUNNING` state, **0 exits**.
     - `backboardd` (PID 36): Daemon remained in `RUNNING` state, **0 exits**.
     - `runningboardd` (PID 5): Background process coordinator remained in `RUNNING` state, **0 exits**.
     - `logd` (PID 69): Lock-free multi-thread exception interception kept the process alive.
     - Over 100 processes spawned cumulatively, with 68 background system services resident in memory.
  3. **Device Tree (ADT) & Policy Fixes**:
     - Injected `/arm-io/disp0` display subsystem node (`1125x2436` canvas) into the ADT.
     - Added `/arm-io/wdt` (`no-pmu = 1`) and `/device-tree/buttons` (`home-button-type = 2`).
     - Loaded static TrustCache (3 modules) into AMFI via `/chosen/memory-map`.

---

## 2. File Inventory

| Filename | Description |
| :--- | :--- |
| **`boot_ios.bat`** | **Windows one-click boot script** (double-click to decompress the boot image and invoke `fastboot boot`) |
| **`boot_ios.ps1`** | **Windows PowerShell boot script** (with colored logs and elapsed timing) |
| **`2_boot_ios.bat`** | **Windows one-click boot & live USB monitor script** (launches `run_complete_ios_boot.py`) |
| **`reboot_to_fastboot.bat`** | **ADB reboot-to-Fastboot helper** (double-click while booted in Android to enter bootloader) |
| **`fuxi-xnu-boot.img.gz`** | Compressed Boot 29 boot image (~26 MB compressed, 90 MB uncompressed `fuxi-xnu-boot.img`) |
| **`fuxi_monitor.py`** | Windows hardware monitor script (captures kernel console & framebuffer over the USB probe) |
| **`fuxi27-root.adt`** | Generated Apple Device Tree binary (includes display subsystem and UFS extents table) |
| **`extents27.json`** | `/dev/block/sda32` physical extent mapping table |
| **`ios27.tc`** | Static AMFI TrustCache bundle (3 modules) |
| **`boot29_framebuffer.png`** | Physical framebuffer capture from Boot 29 |
| **`boot29.log.gz`** | Compressed 300-second kernel & userland log from Boot 29 (~568 KB) |
| **`boot_failure_and_fix_log.md`** | Full engineering debugging log documenting root causes and fixes for Boot 1–29 |

---

## 3. Windows Setup & One-Click Boot Guide

### Step 1: Verify USB Drivers (Fastboot Driver)
1. Power off the phone, then hold **Volume Down + Power** to enter Fastboot mode.
2. Connect the phone to the Windows PC via USB.
3. Open **Device Manager**:
   - It should appear under `Android Device` -> `Android Bootloader Interface`.
   - If a yellow warning icon appears, install the Google USB Driver or MiFlash / Xiaomi Fastboot driver.

### Step 2: One-Click iOS Boot
1. Ensure `fastboot` is installed and available on `PATH` (check `fastboot --version` in a terminal, or add Windows `platform-tools` to `PATH`).
2. Double-click **`boot_ios.bat`** (or **`2_boot_ios.bat`** to include live monitoring).
3. The script automatically:
   - Decompresses `fuxi-xnu-boot.img.gz` into `fuxi-xnu-boot.img` if needed;
   - Checks the Fastboot device connection;
   - Runs `fastboot boot fuxi-xnu-boot.img` to load the kernel into device RAM.
4. The display powers on and boots into XNU.

---

## 4. Next Engineering Direction (K5 Display Driver & Graphics Pipeline Alignment)

Userland `SpringBoard` and `backboardd` now stay alive in memory; the remaining bottleneck is:
- **Physical Framebuffer Swap (K5 Milestone)**:
  - Port the `xnu-8796`-verified `SweetFramebuffer.cpp` (or `LegacyDisplayProbe.cpp` from `unixnu-fuxi`) into the running `xnu-12377` prelinked kernel.
  - Register the IOKit `AppleCLCD` service so WindowServer `SwapBegin` / `SwapEnd` copies CoreAnimation-rendered BGRA surfaces into the splash framebuffer at `0xb8000000`, displaying SpringBoard on the physical AMOLED panel.
- See `boot_failure_and_fix_log.md` for full technical derivations and historical patches.
