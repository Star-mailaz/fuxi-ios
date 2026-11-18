# Xiaomi 13 (`fuxi` / SM8550) iOS 16.7.10 Cross-Platform Handover & Device Backup Notes

> **Updated**: 2026-11-08  
> **Handover Target**: Continue development on Windows from the macOS environment  
> **Handover Paths**:
> - **Handover Drive (Windows)**: `<HANDOVER_DRIVE>\fuxi-ios-handover\`
> - **Handover Drive (macOS)**: `/Volumes/M26SHARE/from-macos/fuxi-ios-handover/`
> - **Workspace Archive**: `<WORKSPACE>/fuxi-ios-handover/`
> - **Full Engineering Fix Log**: [`boot_failure_and_fix_log.md`](boot_failure_and_fix_log.md)

---

## 1. Device Backup Status & Safety Guarantee

### 1.1 Anti-Brick Partition Backup (21 Core Partitions, SHA-256 Verified)

Before on-device testing, raw sector-by-sector partition images of the Xiaomi 13 (serial `<DEVICE_SERIAL>`) were extracted via ADB root / TWRP and stored locally in `<WORKSPACE>/backup/`:

- **Backup Directory**: `<WORKSPACE>/backup/`
- **Partition Inventory (21 core partitions, ~1.95 GB)**:
  | Image File | Size | Critical Purpose |
  | :--- | :--- | :--- |
  | `persist.img` | 64 MB | **Most critical**: factory sensor calibration, fingerprint calibration data, anti-brick essential |
  | `modemst1.img` / `modemst2.img` | 8 MB / 8 MB | Baseband NVRAM containing device IMEI and RF calibration parameters |
  | `fsg.img` / `fsc.img` | 8 MB / 1 MB | Baseband golden backup and calibration logs |
  | `boot_a.img` / `boot_b.img` | 192 MB / 192 MB | Stock Android kernel boot partitions |
  | `init_boot_a.img` / `init_boot_b.img` | 8 MB / 8 MB | Stock GKI core ramdisk partitions |
  | `vendor_boot_a.img` / `vendor_boot_b.img` | 96 MB / 96 MB | Vendor driver ramdisk and device trees |
  | `recovery_a.img` / `recovery_b.img` | 100 MB / 100 MB | Recovery partitions |
  | `dtbo_a.img` / `dtbo_b.img` | 24 MB / 24 MB | Device Tree Overlay partitions |
  | `dsp_a.img` / `dsp_b.img` | 64 MB / 64 MB | Hexagon DSP firmware partitions |
  | `modem_a.img` / `modem_b.img` | 448 MB / 448 MB | Qualcomm baseband RF firmware partitions |
  | `bluetooth_a.img` / `bluetooth_b.img` | 6 MB / 6 MB | Bluetooth firmware partitions |
  | `checksums.sha256` | 1.6 KB | SHA-256 checksum manifest for all 21 partition images |

### 1.2 Zero-Flash Boot Partition Guarantee
- **Stock Android partitions untouched**: Across all 29 boot iterations, boot images were loaded strictly into RAM with `fastboot boot fuxi-xnu-boot.img`. No `fastboot flash` writes were ever issued against `boot`, `init_boot`, `recovery`, `system`, `vendor`, or `super`.
- **Isolated iOS Root Storage**: The iOS 16.7.10 root filesystem was staged inside an isolated UFS allocation in `/dev/block/sda32`, separate from Android's active OS partitions.
- **Instant Recovery to Stock OS**: Holding the Power button for ~10 seconds reboots the phone directly back into Android / MIUI.

---

## 2. Handover File Inventory

All ready-to-run Windows boot tools were synced to `<HANDOVER_DRIVE>\fuxi-ios-handover\` and `<WORKSPACE>/fuxi-ios-handover/`:

| Filename | Description |
| :--- | :--- |
| **`boot_ios.bat`** | **Windows one-click boot script** (decompresses `fuxi-xnu-boot.img.gz` and runs `fastboot boot`) |
| **`boot_ios.ps1`** | **Windows PowerShell boot script** (colored output and elapsed timing) |
| **`2_boot_ios.bat`** | **Windows one-click boot & USB monitor wrapper** |
| **`reboot_to_fastboot.bat`** | **ADB reboot-to-Fastboot script** (double-click while booted in Android) |
| **`fuxi-xnu-boot.img.gz`** | Compressed Boot 29 boot image (~26 MB, expands to 90 MB, verified) |
| **`fuxi_monitor.py`** | Windows hardware monitor script (captures kernel console logs and screenshots over PyUSB) |
| **`fuxi27-root.adt`** | Latest Apple Device Tree binary (injects `/arm-io/disp0` `1125x2436`, UFS partitions, etc.) |
| **`extents27.json`** | `/dev/block/sda32` physical extent mapping table |
| **`ios27.tc`** | Static AMFI TrustCache bundle (3 modules) |
| **`framebuffer.png`** | Boot 29 physical framebuffer capture |
| **`boot29.log.gz`** | Full 568 KB kernel and userland log from a 300-second Boot 29 run |
| **`boot_failure_and_fix_log.md`** | Complete engineering debug log covering Boot 1–29 root causes and fixes |
| **`README_WINDOWS.md`** | Windows environment setup and operation guide |

---

## 3. Current Progress & Verified Results (As of Boot 29)

1. **Core Processes Kept Alive (Zero Exits)**:
   - `SpringBoard` (PID 6): Spawned and remained `RUNNING` for **300+ seconds with 0 exits**.
   - `backboardd` (PID 36): Window server daemon remained `RUNNING` with **0 exits**.
   - `runningboardd` (PID 5): Process coordinator remained `RUNNING`.
   - 101 processes spawned cumulatively; 68 background system daemons stayed resident with **zero kernel panics and zero watchdog resets**.
2. **Trust Chain & Root Filesystem Mount**:
   - APFS root container (iOS 16.7.10 Sydney 20H392) mounted from UFS `/dev/block/sda32`.
   - All 3 external TrustCache modules loaded into AMFI, resolving code-signing rejections.
3. **ADT Display Subsystem**:
   - Injected `/arm-io/disp0` (`1125x2436` canvas) into the ADT, taking `backboardd` out of headless mode (`headless = false`).

---

## 4. Physical Display Root Cause & Next Step (K5 Milestone)

- **Current Screen Output**: The screen remains on the ABL splash framebuffer (`0xb8000000`), showing XNU kernel console text (`PE_Video_Console`).
- **Root Cause**:
  - Current progress is at **K4** (UFS physical root mount + `launchd` userland + `SpringBoard` survival).
  - Next is **K5 (Display Driver Pipeline Alignment)**: register `AppleCLCD` / `IOMobileFramebuffer` in `xnu-12377` so WindowServer's `SwapEnd` copies CoreAnimation layers into `0xb8000000`, displaying the SpringBoard Lock/Home screen on the AMOLED panel.

---

## 5. Windows Operation Steps

1. Insert the handover drive into the Windows PC (`<HANDOVER_DRIVE>\fuxi-ios-handover\`).
2. Power off the phone, hold **Volume Down + Power** to enter Fastboot mode, and connect via USB.
3. Double-click `boot_ios.bat` to decompress the image and run `fastboot boot fuxi-xnu-boot.img`.
4. The device boots XNU and loads iOS directly in RAM.
