# 解除藍牙 Userland 封鎖前置紀錄（僅供驅動備妥後使用）

## 1. 目前封鎖狀態（0025 / metal4）
- 核心 boot-arg：`sweetnoexec=bluetoothd,fairplayd.H2`（來自 `0095-sweet-noexec-bootarg.patch`）。
- 若要僅解除 `bluetoothd`（保留 `fairplayd.H2` 封鎖）：
  將 cmdline 中的 `sweetnoexec=bluetoothd,fairplayd.H2` 改為 `sweetnoexec=fairplayd.H2`。

## 2. Launchd 狀態檢查
若 rootfs 曾執行過 `tools/disable-launchd-jobs.py` 將藍牙相關 job 標記停用，需在可寫 rootfs 上檢查並恢復 `com.apple.bluetoothd.plist`（及 `BlueTool` 相關 plist）。

## 3. 前置硬條件檢查清單（全數滿足才可移除 `bluetoothd` 封鎖）
- [ ] XNU 已提供 `/dev/uart.bluetooth` (QUP2 SE6 `0x898000`, H4 3000000 bps)
- [ ] XNU 已提供 `/dev/btreset` / `BTReset`（`gpio81` + WCN7850 6 路電源軌協調）
- [ ] 已透過 `scripts/pull_fuxi_firmware.ps1` 拉取並佈署 `hmtbtfw*.tlv` 與 `hmtnv*.b*`
- [ ] 已準備 Broadcom <-> QCA 初始化／vendor 指令相容層
