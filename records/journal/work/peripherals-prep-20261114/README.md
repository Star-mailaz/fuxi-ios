# Xiaomi 13 (fuxi) iOS 16.7.16 周邊適配離線準備總覽 (`peripherals-prep-20261114`)

> **隔離保證**：本目錄所有補丁、標頭、測試與腳本皆與 `ios-fuxi`、`work/kdraws-src` 及現行 `0025` GPU 測試完全隔離；未觸及任何實機（`adb`/`fastboot`）或 GitHub CI。

## 目錄與產出清單

| 子系統 | 產出檔案 | 目的 | 是否需重編 XNU |
|---|---|---|---|
| **亮度 Backlight** | `backlight/patches/0117-fuxi-backlight-dsi.patch`、`backlight/FuxiDsiBacklight.cpp`、`backlight/fuxi_dsi_backlight_logic.h`、`backlight/verify_backlight_dsi.py` | 保留 `fuxibacklight=1..3` 原邏輯，新增 `fuxibacklight=4`（原生 `AppleARMBacklight` + DSI0 `0xae94000` TPG DMA DCS `0x51` + 16ms `FadePeriod` 漸變）與 `fuxibacklight=5`（含電源興趣通知） | **是** |
| **聲音 Audio** | `audio/patches/0118-fuxi-rpmh-arb-wlan.patch`、`audio/fuxi_rpmh_arb.c`、`audio/fuxi_cs35l41_dt_spec.h`、`audio/BUILD_AND_STAGE_MACOS.md`、`audio/tests_update_hint.md`、`audio/verify_audio_host.py` | 完成 `P-AU2` 步驟之一的跨驅動 Apps RSC (DRV2) TCS 鎖（`FuxiRpmhArb` 合入 `fuxi_wlan.c::rh_send_request`），並備妥 macOS Xcode 建置 `FuxiAudio.driver` (`P-AU0`) 與 live-DT 硬體規格 | `P-AU0` 只需 rootfs + macOS Xcode；`P-AU2+` **是** |
| **Wi-Fi** | `wifi/generate_cmdlines.py`、`wifi/cmdlines.json`、`wifi/cmdlines/*.txt`、`wifi/wifi_fw_expected.json`、`wifi/verify_wifi_prep.py` | 產生並驗證全部 `< 608` 位元組的開機參數組合（`fuxiwifiios=1` 假體 UI、`fuxiwlan*` `P17` + `wlan-rails` 診斷）與 WCN7850 韌體 SHA256 清單 | `fuxiwifiios=1` 與 `P17` **免重編**（`0025` 已含）；802.11 資料面 **是** |
| **電池 Battery** | `battery/fuxi_battery_hw_spec.h`、`battery/verify_battery_spec.py` | 核對 SPMI v7 (`0x0c400000..`)、`PM8550B SID 7`、`PMK8550 vadc@9000` 9 個 ADC 通道與 ADSP `pmic_glink` (`PMIC_RTR_ADSP_APPS`) 依賴關係 | 真實電量 **是**（目前 `SweetBattery` 靜態 100% 已啟用） |
| **藍牙 Bluetooth** | `bluetooth/fuxi_bt_hw_spec.h`、`bluetooth/fuxi_h4_framer.{h,c}`、`bluetooth/unblock_bt_prep.md`、`bluetooth/verify_bt_host.py` | 核對 QUP2 SE6 HS-UART (`0x898000`, SPI `0x1cd`, GPIO `81/82`) 硬體規格、備妥可獨立編譯之 H4 UART framing 狀態機與 `sweetnoexec` 解封注意事項 | **是**（尚缺 `/dev/uart.bluetooth`, `/dev/btreset`, BCM↔QCA 轉譯與韌體） |
| **共用拉取與佈署** | `scripts/pull_fuxi_firmware.ps1`、`scripts/stage_peripherals_root.sh`、`scripts/fdt_inspect.py`、`scripts/patch_check.py`、`verify_all.py` | GPU 測試告一段落後供手動從手機提取 WCN7850 / ADSP / CS35L41 / ACDB 韌體並檢查 SHA256，以及 HFS+ rootfs 離線佈署 | — |

## 本機全數驗證命令

```powershell
python D:\xiaomi13\fuxi_ios\work\peripherals-prep-20261114\verify_all.py
```
