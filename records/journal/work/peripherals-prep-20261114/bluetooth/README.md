# Fuxi 藍牙適配分析與 M1/M2 離線準備

## 當前阻塞原因（全數經程式與 DT 驗證）

1. **使用者層封鎖**：目前 `0025` / `metal4` 開機參數明確設定 `sweetnoexec=bluetoothd,fairplayd.H2`，且根檔案系統內 `bluetoothd` / `BlueTool` 相關 job 可能被停用（`disable-launchd-jobs.py`）。
2. **核心驅動全空**：
   - `work/kdraws-src`、`ios-fuxi` 與 `unixnu-fuxi` 均**無任何**藍牙或 HS-UART 驅動。
   - iOS `bluetoothd` 需要 `/dev/uart.bluetooth`（H4 `3000000 bps`）與 `BTReset`（`/dev/btreset`, `/dev/btwake`, `/dev/btpoweroff`）。
   - 小米 13 實機為 WCN7850 (`bt_kiwi`, `qcom,qup_uart@898000`, `BT_EN=gpio81`, `BT_SW_CTRL=gpio82`)，需要 QCA 韌體下載（`hmtbtfw*.tlv`, `hmtnv*.b*`）與共享的 6 路 WCN7850 PMU 電源軌（S5G/L15B/S2G/S4E/S4G/S6G）。
   - iOS `bluetoothd` 僅懂 Apple / Broadcom (`BCM`) vendor HCI 指令，後續還必須在 core/daemon 層實作 Broadcom → QCA 指令轉譯或啟動階段攔截。

## 已準備內容

- **`fuxi_bt_hw_spec.h`**：經 `dtb/fuxi-live.dtb` 交叉驗證的硬體腳位、QUP2 SE6 位址 (`0x898000`)、SPI (`0x1cd`) 與控制 GPIO (`81`/`82`) 規格標頭。
- **`fuxi_h4_framer.h` / `fuxi_h4_framer.c`**：可獨立於 XNU 與宿主端共用的 Bluetooth H4 UART 串流狀態機與 HCI Command 編碼器（已通過 NDK Clang `-Wall -Wextra -Werror` 編譯與 Python 單元驗證）。
- **`unblock_bt_prep.md`**：記錄解除 `sweetnoexec` 與 `launchd` 停用之正確操作與注意事項。

> ⚠️ **安全提醒**：在 `/dev/uart.bluetooth` 與 `/dev/btreset` 驅動尚未進核心前，**切勿**移除 `sweetnoexec=bluetoothd`，否則 `launchd` 會因 `bluetoothd` 找不到裝置而不斷重試崩溃洗版。
