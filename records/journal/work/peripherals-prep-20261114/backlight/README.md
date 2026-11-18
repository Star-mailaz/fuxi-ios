# Fuxi 背光適配分析與 DSI0 AppleARMBacklight 補丁

## 問題根因（對照 `kdraws-src` 與 `unixnu-fuxi` 交叉驗證）

1. 既有 `0109-fuxi-backlight.patch`（`fuxibacklight=1|2|3`）：
   - `FuxiBacklight` 僅繼承 `IODisplay`（未繼承或符合 `AppleARMBacklight`），因此 `CoreBrightness` 的 `-[CBDisplayContaineriOS findBacklight]`（要求 `backlight-control = true` **且** `IOObjectConformsTo(service, "AppleARMBacklight")`）不會將其綁定為內建螢幕背光。
   - `FuxiBacklight::setProperties()` 亦僅寫入 `hardware=untouched` 日誌，未曾操作任何硬體暫存器。
2. 小米 13 實機驗證來源（`unixnu-fuxi/package/AppleARMBacklight.cpp` + `dtb/fuxi-live.dtb`）：
   - 小米 13 面板（`xiaomi m3 38 0c 0a sec cmd mode dsc dsi panel`）使用 DSI0 控制器 (`0xae94000`) TPG 命令 DMA 傳送 MIPI DCS `0x51`（`inverted-dbv` 高位元組優先；`mi,mdss-dsi-fac-bl-max-level = 0x7ff = 2047`，`min = 0x4`，實務下限鉗制 `8` 以免全黑）。
   - XNU-8796 核心內建並**無** `AppleARMBacklight` 類別，因此可直接定義原生的 `class AppleARMBacklight : public IODisplay`（無須 vtable 竄改），同時滿足 `CoreBrightness` 搜尋條件與 `backboardd` 權限白名單。

## 本目錄準備內容

- **`patches/0117-fuxi-backlight-dsi.patch`**：完全向後相容 `0109`（保留 `fuxibacklight=1|2|3` 原行為不變），新增獨立檔案 `FuxiDsiBacklight.cpp` 與 `fuxi_dsi_backlight_logic.h`：
  - **`fuxibacklight=4`**（建議首測）：啟用 `FuxiDsiBacklight : public AppleARMBacklight`，映射 DSI0 `0xae94000`，以獨立 `IOWorkLoop` + `16ms IOTimerEventSource` 執行 `FadePeriod` 漸變並寫入 DCS `0x51`，超時/錯誤時自動恢復保存的 DSI 暫存器並熔斷 (`fHalted`) 以免卡死掃描輸出。關閉 `AppleCLCD` 電源訊息轉發以避免模式 2 的休眠重鎖問題。
  - **`fuxibacklight=5`**：與模式 4 相同，額外開啟 `AppleCLCD` 的 `0xe0000230`/`0xe0000210` 電源興趣通知供對照測試。
- **`verify_backlight_dsi.py`**：於本機執行 `git apply --check`（含 `kdraws-src` 與 `ios-fuxi` 的 `SweetFramebuffer.cpp`）、NDK Clang C++14 (`--target=aarch64-linux-android33 -Wall -Wextra -Werror -c`) 編譯檢查、以及 DCS `0x51` 編碼／漸變／鉗制邏輯單元測試。
