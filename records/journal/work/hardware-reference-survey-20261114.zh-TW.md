# 小米 13 iOS 16 硬體適配：現成方案調查（2026-11-14）

只做離線調查，沒有碰手機。對象：本機的 `UniXNU`、`unixnu-fuxi`，以及 GitHub 上的 UniXNU 元件與社群移植。

## 結論

同為 SM8550 的 **UniXNU 官方 sheng 移植**（小米平板 6S Pro，[UniXNU/UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng)）已在實機上做到 Wi-Fi、藍牙、聲音、真實電池、USB。另一個 **小米 13 iOS 17 移植**（[Kerfand/UniXNU-Fuxi-Arm64e-iOS17](https://github.com/Kerfand/UniXNU-Fuxi-Arm64e-iOS17)）把亮度做到可用，聲音做到只差最後一步。我們的工作主要是把這些移植到 ios-fuxi 的 iOS 16 核心，不是從零寫。

這些移植的共同基礎是 **ADSP 開機＋SMEM／SMP2P／GLINK／QRTR**（sheng 的 `AdspProbe.cpp`、`AdspFirmware.c`、`QcomSmem`、`QcomGlink`、`QcomQrtr`）。這一層打通之後，電池、聲音、USB 角色切換（UCSI）都能接上，所以應該最先移植它。

## 逐項

| 項目 | 現成方案（來源） | 驗證程度 | 要改的部分（我們是 iOS 16、ios-fuxi 核心） |
|---|---|---|---|
| 亮度 | `unixnu-fuxi/package/AppleARMBacklight.cpp` 的 `fuxi-backlight=dsi`：每個亮度值是一次 DSI0 DCS `0x51` 寫入（TPG 命令 DMA），碰過的暫存器全部存回；以「宣告符合 AppleARMBacklight」讓 CoreBrightness 接手（同名類別會 panic） | 兩個小米 13 移植都用它（ljhhkx529 的 board.toml 預設、Kerfand 寫「亮度可用」） | DSI 在我們這邊由掃描輸出持有（TE 驅動的 START、120 Hz 切換也走同一條命令 DMA），要改成由掃描輸出在兩次傳輸之間代送；它用 `IODelay` 忙等 DMA 完成（最長 50 ms），漸變時每 16 ms 一次，要改成不忙等。agy 的 `0117` 草稿是另開執行緒直接寫 DSI，不建議照用 |
| 電池／充電 | sheng `ShengBattmgr.c`／`ShengBattery.cpp`：經 PMIC GLINK 向 ADSP 電池管理器讀電量、電流、溫度、循環、充電器狀態；ADSP 自己跑充電與 PD／PPS 協商 | sheng 實機：PPS 8.72 V 充電、Mac PD 5 V、電量與溫度讀數正確 | 需要先有 ADSP＋GLINK。小米 13 是單電芯（sheng 是兩顆電量計相加）。發佈給 iOS 的電源屬性跨版本大致穩定 |
| 聲音 | sheng：AudioReach（GPR 通道 adsp_apps）、喇叭 CS35L43 ×6、麥克風 WCD938x、CoreAudio HAL 外掛（`hal/ShengAudioPlugIn.c`）、ADSP 韌體直接從 modem_a 分區的 `/image/adsp*` 載入。Kerfand 小米 13：ADSP、**CS35L41** 功放、HAL 外掛已動 | sheng 實機播放與錄音順暢（`dea464e`）。Kerfand 小米 13 仍無聲：路由要求 HAL 級喇叭保護 `spac` | 小米 13 是 CS35L41（不是 CS35L43）；iOS 16 的 VirtualAudio／HAL 和 iPadOS 27、iOS 17 不同；Kerfand 的作法（ADT 補 product-id、acoustic-id 讓 VirtualAudio 載入調校與路由資料庫）可參考。上游 ios-fuxi 已有未編譯的 `xnu/fuxi-audio`（AudioReach／GPR） |
| Wi-Fi | [UniXNU/Ath12kWifi](https://github.com/UniXNU/Ath12kWifi)（Linux v7.0.14 的 ath12k＋mac80211＋cfg80211 搬上 XNU，搭配 wpa_supplicant 2.12）＋ sheng `WifiProbe.cpp`／`WifiNet.cpp`／`WifiFirmware.c`／`WcnPower.h`（WCN7850 供電、PCIe、MSI、128 MiB DMA 視窗） | sheng 實機（iPadOS 27、macOS 27.3）：開關、掃描 5–13 個網路、WPA2 連線、DHCP、傳輸 | 我們上游自己的 WCN7850 開機卡在第 22 步（PBL `0xef0e0003`），sheng 的板級供電／PCIe 序列是同 SoC 的參考。要換成 fuxi 的 GPIO、電源；Apple 端（Apple80211 使用者端、wifid 的連線結果格式）是 iPadOS 27 專用，要改成 iOS 16 的介面 |
| 藍牙 | [UniXNU/QcaBluetooth](https://github.com/UniXNU/QcaBluetooth)：Linux `btqca.c` 啟動序列經 GENI UART 跑 WCN7850，接 Apple 的 `bluetoothd`（UART.SK 管道、BlueTool XPC 服務） | sheng 實機：配對、重開後重連、A2DP 播放、AirPods 降噪與電量 | 小米 13 的藍牙 UART 在 QUP2 SE6（agy 依 DTB 核對），sheng 是 UART14；bluetoothd／BlueTool 介面是 iPadOS 27 版，要對 iOS 16 調整；需要 WCN7850 藍牙韌體（手機 Android 分區內有） |
| USB（額外） | [UniXNU/QcomDwc3](https://github.com/UniXNU/QcomDwc3)：DWC3 掛在 Apple 自己的 `AppleUSBXDCI`／`AppleUSBXHCI` 下 | sheng 實機：接 Mac 列舉、信任、配對、lockdown、installation_proxy／afc | 角色判斷用 UCSI（經 ADSP 充電器 GLINK 通道）；小米 13 的 retimer、PHY 要核對；目前我們的 USB 只有 loader 監看用的除錯介面 |
| 影片硬體解碼（額外） | sheng `video` 領域：H.264／HEVC 8／10 bit 硬體解碼 | sheng 實作，動態桌布可播 | 可降低看影片時的 CPU 與溫度 |

## 建議順序

1. **亮度**：只動 DSI，不需要 ADSP，風險最低、效果最直接。移植 `fuxi-backlight=dsi` 的 DCS 寫入，改由掃描輸出代送。
2. **ADSP＋GLINK／QRTR 基礎層**：從 sheng 移植，接著做**電池**（真實電量、充電狀態）。
3. **聲音**：在 ADSP 基礎上移植 AudioReach＋CS35L41＋HAL 外掛，參考 Kerfand 卡住的喇叭保護問題。
4. **Wi-Fi**、**藍牙**：先用 sheng 的板級序列把 WCN7850 韌體開起來，再處理 iOS 16 的 Apple 端介面。這兩項工作量最大。

## 授權

UniXNU 的元件混用 BSD-2-Clause-Patent、APSL-2.0 與 GPL-2.0-only（移植自 Linux 的部分，例如 ath12k、btqca、eUSB2／QMP PHY），UniXNU-sheng 倉庫本身沒有宣告授權。自用沒有問題；若要放進公開倉庫（例如 `fuxi-ios-bringup`），GPL 部分要依 GPL 散佈並保留每個檔案的授權標示。上游 ios-fuxi 已經用「附 LICENSE.UniXNU」的方式引入過 UniXNU 程式。

## 本機與線上位置

- 本機：`D:\xiaomi13\fuxi_ios\UniXNU`（框架，`73b35d2`，含 `components.toml`、`devices.toml`）、`D:\xiaomi13\fuxi_ios\unixnu-fuxi`（ljhhkx529 的小米 13 iPadOS 17 移植，亮度在 `package/AppleARMBacklight.cpp`）。
- 線上：`UniXNU/UniXNU-sheng`（`package/` 內 Adsp*、QcomGlink／Qrtr／Smem、ShengBattmgr／ShengBattery、ShengAudio*、Wifi*、Bluetooth*、UsbProbe；`porting.toml` 是各領域的實機證據），`UniXNU/Ath12kWifi`，`UniXNU/QcaBluetooth`，`UniXNU/QcomDwc3`，`Kerfand/UniXNU-Fuxi-Arm64e-iOS17`（小米 13 iOS 17，亮度與聲音的 fuxi 專屬作法）。
- agy 的離線準備：`D:\xiaomi13\fuxi_ios\work\peripherals-prep-20261114`（硬體規格核對與 DTB 數值可沿用；亮度 `0117` 草稿不建議照用）。
