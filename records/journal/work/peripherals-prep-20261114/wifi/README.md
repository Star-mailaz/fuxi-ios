# Fuxi Wi-Fi 適配分析與離線準備

## 兩階段路線與核心相容狀態

1. **假體 iOS UI 層 (`fuxiwifiios=1`) — 現行 `0025` / `metal4` 核心已內建**：
   - `0104-fuxi-wifi-ios.patch` (`fuxi_wifi_ios.c`) 已編入核心，唯預設關閉 (`fuxiwifiios=0`)，且 iOS 根檔案系統需透過 `tools/enable-wifi-ios.py <MOUNTED_ROOT> --enable-wifid` 解除 `wifid` 的 `_LimitLoadToDeviceTree` / `Disabled` 限制。
   - **預期能力**：讓 `wifid` 與系統設定顯示 Wi-Fi 介面 (`en0`) 與模擬掃描／狀態，僅供 UI 聯調（資料面只回環 `0x88b5`，會丟棄 ARP/IPv4/EAPOL）。
2. **實機 WCN7850 晶片 (`fuxiwlan=1 ...`) — `0099` 核心已含尚未實測之 `P17` / `wlan-rails`**：
   - 先前實機紀錄 `W17 try16` 已走到 `AMSS -> FW_READY -> WLAN_INI OK -> WLAN_CFG OK`，卡在 `WLAN_MODE (0x22)` 無回應。
   - 現行核心中已編入但未實測的診斷旗標：
     - `fuxiwlanmlo=0x17d`（`P17`：開通 TLV `0x33`、強制 MLO TLV、2^n IOVA 對齊、唯讀 PMK8550 gpio3 sleep clock、RDDM 文本掃描）或 `0x1bd`（加開 gpio3 sleep clock）。
     - `fuxiwlanrails=1`（M3 重投票 6 路 WCN 電源軌）與 `fuxiwlanrails=2`（僅於 `WLAN_MODE` 前重投票，不關軌）。
   - **尚未存在於硬碟與核心的缺口**：
     - `firmware/` 目錄目前完全沒有 WCN7850 韌體（`amss20.bin`, `amss.bin`, `bd_m3gl.elf`, `regdb_xiaomi.bin`），需以 `scripts/pull_fuxi_firmware.ps1` 自手機拉取並放入 `/usr/local/share/fuxi/wlan/` (`root:wheel`, `0644`)。
     - 802.11 資料面（MHI/CE TX/RX、HTT/WMI、802.3 <-> 802.11 橋接到 `fuxi_wifi_ios`）尚未開發。

## Boot Cmdline 608 位元組上限分析

XNU-8796 的 `boot_args.CommandLine` 上限為 **608 位元組**（含結尾 NUL，即最多 **607 ASCII 字元**），現行 `0025` base 已佔 **562 位元組**（僅餘 45 位元組）：
- `0025_wifi_ui_fake` (**576 B**)：可直接於原 `0025` 附加 `fuxiwifiios=1`。
- `0025_wifi_ui_plus_backlight_dsi` (**592 B**)：可直接於原 `0025` 附加 `fuxiwifiios=1 fuxibacklight=4`。
- `wcn7850_p17_*` 系列：因長串 `fuxiwlan*` 參數會突破 608 位元組，已透過移除 Metal profiler 除錯旗標 (`sweetsample`, `sweetscan`, `sweetexecswap`, `sweetnull`) 將總長度控制在 607 位元組以內（詳見 `generate_cmdlines.py` 與 `cmdlines.json`）。

## Windows 平台既存腳本註記

執行 `work/kdraws-src` 原腳本驗證時發現兩處僅影響 Windows 主機工具（不影響 Linux/macOS 核心與 CI）的行為：
- `tools/sync-fuxi-wifi-ios.py --check`：Windows `Path.iterdir()` 大小寫不敏感排序導致 `FuxiNetworkStack.cpp` 與 `fuxi_wifi_ios.c` 相對順序異於 macOS/Linux POSIX `sorted()`。
- `tools/sync-fuxi-backlight.py --check`：`subprocess.run(..., text=True)` 讀入 CRLF 造成 `git apply --check` 在 Windows 失敗（LF/CRLF 差異）。
