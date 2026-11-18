# Fuxi 音訊適配離線準備指引 (P-AU0 / P-AU1 / P-AU2)

## 已在本目錄準備的內容

1. **`patches/0118-fuxi-rpmh-arb-wlan.patch`**（對應 `docs-lanes/audio.md` **P-AU2**）：
   - 新增 `bsd/dev/fuxi_rpmh_arb.c`（定義全域共享實例 `FuxiRpmhArb fuxi_rpmh_arb`）並加入 `bsd/conf/files`。
   - 將 `bsd/dev/fuxi_wlan.c::rh_send_request()` 的未加鎖 `rh_poisoned` 檢查切換為 `fuxi_rpmh_arb_enter(..., FUXI_RPMH_OWNER_WLAN, 1000000u)` 與全路徑 `fuxi_rpmh_arb_leave(..., ok)`（前置檢核未觸及 TCS 時以 `ok=1` 釋放；程式化 / 觸發 / 超時 / 清理失敗以 `ok=0` 毒化；正常完成以 `ok=1` 釋放）。
2. **`fuxi_cs35l41_dt_spec.h`**：從 `dtb/fuxi-live.dtb` 驗證提取之 I2C (`0x880000`)、雙 `CS35L41` (`0x40`/`0x42`，reset GPIO `183`/`182`) 與 ADSP carveout (`0x9e980000`, `0x9ea00000`) 規格。
3. **`tests_update_hint.md`**：說明合入 `0118` 後，既有的 `tools/test-fuxi-wlan-m6i.py` 與 `tools/test-fuxi-wlan-rails.py` 測試 preamble 需同步補上 `fuxi_rpmh_arb` 假體定義。

## macOS 建置與 Rootfs 佈署步驟 (P-AU0)

> 本步驟需在配備 Xcode / iPhoneOS SDK 的 macOS 主機執行，無法於 Windows 直接編譯 CoreAudio HAL bundle。

1. 編譯 AudioServerPlugin (`FuxiAudio.driver`) 與 SpringBoard snapshot helper：
   ```bash
   cd <kdraws-src 或 ios-fuxi 根目錄>
   bash tools/build-fuxi-sys.sh
   ```
   預期產出位於 build 目錄的 `FuxiAudio.driver`（實作 Speaker / Hawking / Actuator / Codec 假體與 ring buffer 橋接，當前未接 ADSP 時僅安全丟棄封包）。
2. 在可寫入之 HFS+ rootfs 掛載點安裝 HAL 外掛並恢復 `VirtualAudio.plugin`：
   ```bash
   sudo python3 tools/fuxi-sys-root.py \
     --audio-plugin <PATH_TO>/FuxiAudio.driver \
     --restore-virtualaudio \
     <MOUNTED_IOS_ROOT>
   ```
   （註：切勿在未安裝 `FuxiAudio.driver` 時單獨恢復 `VirtualAudio.plugin`，否則 `mediaserverd` 會崩潰。）
3. 若需同時測試 Audio / Haptics 節點，打包 ADT 時可依需求附加：
   ```bash
   python3 tools/mkadt-fuxi.py --live-fdt dtb/fuxi-live.dtb --d22ap-adt <D22AP_ADT> --product-haptics ...
   ```

## 仍缺的實機前置條件 (P-AU2 ~ P-AU9)

- 尚未從手機提取 ADSP 韌體（`adsp.mdt/.b*`, `adsp_dtb.mdt/.b*`）、ACDB 拓撲（`Tutu_acdb_cal.acdb`, `Tutu_workspaceFileXml.qwsp`）與 Cirrus `cs35l41*` 檔案（可使用 `scripts/pull_fuxi_firmware.ps1` 後續拉取）。
- XNU 尚缺 ADSP PAS/SCM 擁有者（或 loader stage-2 交接）、GLINK `adsp_apps` / SMEM / IPCC / TCSR hwspinlock、`GENI I2C` 與 `CS35L41` 非 GPL 暫存器初始化序列、IOAudio ring 橋接及 WCD938x SoundWire 麥克風驅動。
