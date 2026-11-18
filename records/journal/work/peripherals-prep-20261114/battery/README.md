# Fuxi 電池 / 充電適配分析與準備狀態

## 現況精確診斷

1. **已啟用（靜態安全回退，無需重編核心）**：
   - `0082-fuxi-ram-bringup.patch` 於 `FUXI` 建置中定義了 `ARM64_BOARD_CONFIG_SWEET`，因此 `0062-sweet-touch-power-battery.patch` 的 `SweetBattery.cpp`（`IOPMPowerSource` / `AppleSmartBatteryManager`）已經包含在 `0025` / `metal4` / `wlan6g` 核心中。
   - 由於 `bsd/dev/sweet_spmi.c` 鎖死 SM7150 SPMI v5（`0x0c440000` 並明確拒絕 `arb_version >= 0x70000000`），在小米 13（SPMI v7）開機時僅印出 `SWEET BATTERY: unsupported SPMI arb=...` 後保持靜態讀數（`100% / 4200 mV / ExternalConnected=1 / Temperature=2500`）。
2. **為何不可在此時套用未驗證的 SPMI 暫存器硬寫補丁**：
   - 經檢視 `dtb/fuxi-live.dtb`：
     - 小米 13 並無獨立 I2C 電量計晶片（無 `bq27z561` 等節點）。
     - 完整電量 `%`、充放電電流 `mA` 與 USB-PD 快充狀態由 ADSP 上的 `pmic_glink`（`/soc/qcom,pmic_glink/qcom,battery_charger`，通道 `PMIC_RTR_ADSP_APPS` + PM8550B `SID 7` + SMB139x）提供。
     - `PMK8550 (SID 0)` 上的 `vadc@9000` (`qcom,spmi-adc5-gen3`) 則暴露了 `pm8550b_vbat_sns_qbg` (`0x78f`)、`pm8550b_vph_pwr` (`0x78e`) 與溫度通道 (`0x703`, `0x718`, `0x747`, `0x749`, `0x74d`)，但該 VADC Gen3 的 SPMI 觸發/校準格式尚未在 Fuxi 實機探針觀測驗證。

## 已準備內容

- `fuxi_battery_hw_spec.h`：整理並核對完畢的 live DT 實體位址（SPMI v7 `0x0c400000..0x0c500000`、PMK8550 VADC Gen3 `0x9000` 通道 ID、PM8550B SID 7）。
- `verify_battery_spec.py`：以 `dtb/fuxi-live.dtb` 程式化交叉驗證所有通道與位址常數，並以 NDK Clang 執行 `-Wall -Wextra -Werror` 語法/型別檢查。

## 後續實機里程碑順序

1. **短程（不依賴 ADSP，唯讀觀測）**：在既有 `fuxi_keys.c` SPMI v7 `fk_spmi_read` 基礎上，加入以 boot-arg 門控的 `vadc@9000`（`SID 0`）唯讀探針（只讀 VADC STATUS/DATA 與 PM8550B DIE TEMP，不寫充電控制暫存器），實測 `pm8550b_vbat_sns_qbg (0x78f)` 換算曲線後再替換 `SweetBattery` 的靜態 `mV`。
2. **中程（與音訊共線）**：隨音訊 `P-AU2 -> P-AU3` 完成 ADSP PAS + GLINK 後，實作 `PMIC_RTR_ADSP_APPS` 客戶端讀取真實電池 `%` 與負載電流 `mA`。
