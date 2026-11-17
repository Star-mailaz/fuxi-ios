# CPU 與 GPU 最終狀態

**查驗日期：2026-11-18（Asia/Taipei）。** 本頁只保留最後已保存、可核對的配置與實測結論，不列版本演變或 A/B 實驗過程。

適用配置：`native-v7wifi-1118-0030-ram9g-srgb-loader`，本機核心 `kernel-local-wifiux2-9g-artifact`。最後查驗的暫時開機為 `native-hw000wifi-rollback-boot-1`，01:12:56 開始。日常 `boot_b` 的目前內容未重新讀取；本次沒有操作手機。

## CPU 調度與頻率

| 項目 | 最終結果 |
| --- | --- |
| CPU 啟用數 | XNU 使用 **7 顆邏輯 CPU**；另 1 顆 A510 保留給 loader USB monitor。Prime 核已啟動，邏輯 CPU 6 對應 MPIDR 0x700。 |
| 調度策略 | 目前為同質 clutch 調度配合 **recommended cores=0x7c**；一般可遷移執行緒的推薦集合為邏輯 **2–6**，即 Gold／Prime。邏輯 0–1 仍保留中斷及綁定執行緒，未關閉小核。完整 AMP／Edge 大小核調度尚未移植。 |
| 調頻啟用 | **`fuxiperf=2` 已生效**；實機有 ready、boosted、cool、idle 統計，並非只有命令列存在。 |
| 輸入加速 | governor 的輸入 boost hold 為 **1500 ms**，熱條件與其他守門可提早降回；持續輸入可更新 hold。 |
| 高檔 LUT 投票 | Silver／Gold／Prime 為 **1228.8／2323.2／2342.4 MHz**，由該次實機 LUT 選出。 |
| CPU 狀態回讀 | 最新趟 boosted 窗口的 EPSS 狀態最高回讀為 **Gold 2323 MHz／Prime 2592 MHz**。這是狀態暫存器換算值，非持續運作頻率或整機效能分數。 |
| 閒置降頻 | **`fuxiperfidle=1000`**；符合閒置條件 1 秒後選 **307.2／499.2／595.2 MHz** 的 idle LUT。最新趟已看到 Gold 499／Prime 595 MHz 回讀及 idle 狀態。 |
| 熱控制 | 該配置的 governor 為 **hot 66°C／limit 72°C／resume 62°C／start 64°C**；快速檢查 20 ms、斜率窗口 200 ms，並保留升溫率與有效感測器檢查。這些是策略門檻，非機身溫度上限保證。 |
| 最新 CPU 溫度 | 該趟 89 筆 CPU governor 統計中，最高值 **70.6°C**；讀值來自 CPU 感測器，不與 USB 主機端另一組 TSENS 讀值混算。 |
| 繪圖執行緒小物件快取 | **`fuxitcache=1` 已生效**，console 明確顯示 `FUXI TCACHE: on`；作用為 bridge 的 **16–512 bytes 小型 Rust 配置**，每個尺寸級別、每執行緒 **64 blocks**。不是全系統的任意物件快取。 |

高檔 LUT 投票與 EPSS 狀態回讀是兩種欄位；Prime 的 2342.4 MHz 投票與 2592 MHz 回讀差異原因尚未確認，兩者保留原值，不推定是超頻或硬體恆定頻率。

## GPU 與顯示管線

| 項目 | 最終結果 |
| --- | --- |
| GPU／繪圖路徑 | **Adreno 740**；iOS Metal 相容路徑經 NativeMetal／bridge、metal2vulkan、Turnip，再透過 NativeAdreno ABI 交給核心。Vulkan 為此路徑的內部後端，不據此宣稱所有 Metal 功能或遊戲相容。 |
| GPU 匯入介面 | 已發布並由 backboardd 開啟 **NativeAdrenoGpuPublished ABI v2／HostImport 16K**。 |
| GPU 調頻配置 | **`fuxigpulevel=24`＝0x18＝cap level 8＋governor bit 0x10**；不是第 24 個 GPU 頻率檔。 |
| GPU 頻率投票 | 有工作時上限投票 **680 MHz**；最後 doorbell 後 **100 ms** 無新工作則降到 **220 MHz**。這是簡單的活動／閒置投票策略，不是負載比例調頻。 |
| 調頻執行證據 | 該趟最後一筆 DCVS 統計為 **ups=64／downs=64／fails=0**；記錄證明高低投票已實際往返，數字不是整趟最終總次數。 |
| GPU 真實時脈 | HFI 投票已獲確認；該 console 仍記錄 **core_measured_khz=unavailable**，因此不把 680／220 MHz 寫成硬體計數器量測頻率。 |
| 記憶體頻寬投票 | 高檔為 **12449218 kB/s**，閒置 floor 為 **2136718 kB/s**；均是頻寬請求，不是實測 DDR 吞吐量。 |
| Turnip 設定 | **`fuxitudebug=nocb` 已生效**；`nocb` 對應關閉 concurrent binning。 |
| Hybrid 快速錄製 | 最新配置**未啟用 `fuxihyb=8`**，也沒有 `fuxitudebug=hyb` 的獨立 Hybrid Turnip 選擇。這兩個是不同的選項，不列為目前已開啟的加速。 |
| swap 等待 | **`fuxiswapwait=0`**：關閉 frontend 在 swap hook 的額外 stored-surface 等待；既有 GPU fence、IOSurface writer 與 scanout 保護仍存在。 |
| VSync 時序 | **`fuxivsynctoff=6000`** 已由核心記錄確認，即 **6000 us／6 ms** 的 TE offset。 |
| 面板模式 | 120 Hz 模式切換成功；最新趟後續 TE 為 **120.7–120.9 Hz**。啟動早期的 `present up to 60 Hz` 訊息不是最後面板狀態。 |
| 顯示緩衝 | double／triple buffering 開關均為 1，後續 scanout 統計可見三個緩衝的 flips。 |
| GPU／CPU 出幀 | 最新 SCANOUT 摘要為 **9600 幀＝9594 GPU＋6 CPU**。15 筆 GPU presents 統計中的 `failed` 均為 0；不推定所有 App 永不崩潰。 |
| scanout 複製耗時 | 最後一筆摘要 `copy_avg_us=4581／copy_max_us=29433`，即約 **4.581／29.433 ms**。此欄位是複製路徑耗時，不是整幀端到端延遲。 |
| 畫面 FPS | **尚無最新配置在統一固定負載下的持續 shown-FPS 驗收值**。面板 TE、compositor 出幀率與真正顯示幀率分開，不用 TE 約 120 Hz 宣稱介面持續 120 FPS。 |
| 顯示與相容性限制 | 網頁已能實際聯網；紫色顯示異常、部分網站／App 的繪圖相容性及長時間壓力驗收仍未完成。 |

## 最終有效參數

```text
cpus=7
fuxiperf=2
fuxicores=0x7c
fuxiperfidle=1000
fuxivsynctoff=6000
fuxiswapwait=0
fuxitcache=1
fuxitudebug=nocb
sweetlog=0
sweetfb_noconsole=2
fuxigpu=1
fuxigpuabi=1
fuximetal=native
fuxigpulevel=24
fuxigpuscanout=1
fuxiscandouble=1
fuxiscantriple=1
fuxipanel120=1
fuxivsyncte=1
```

這是已查驗的效能與顯示參數摘錄，**不是可直接取代原 loader 的完整命令列**。`sweetfb_noconsole=2` 控制螢幕開機文字；它與紀錄是否完整、實際出幀率是不同事項。

## 查驗來源

完整原始檔尚在開發工作區，本倉庫只收錄結論。沒有上傳原始 console、私人資料或裝置映像。

- 最後實機紀錄：`work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-rollback-boot-1/boot.log`，20833 行，SHA-256 `0b17851079287db92ddd9d24edd28d07d2cb2dce00a05d41a21551bfee8fd434`。
- 第 77 行為 TE offset；第 109–111 行為推薦核心與 LUT；第 148–163 行為 GPU 投票、時脈量測狀態與 DCVS 策略；第 1172／1226 行為 Turnip 設定／tcache；第 11549 行為最後一筆 DCVS 計數；第 20781 行為最後一筆 SCANOUT；第 20790 行含 CPU boosted 回讀。
- 同配置較早實機紀錄 `native-hw000wifi-v7wifi-boot-1/boot.log` 與最後紀錄交叉核對。來源 manifest 指向 `kernel-local-wifiux2-9g-artifact`。
- CPU 擁有者：`work/adsp-battery/ksrc/xnu/fuxi-perf/fuxi_perf.c`；頻率回讀以 EPSS +0x20 的低 8 bit ×19.2 MHz 換算，boost vote 另由 LUT 選出。
- GPU 擁有者：`xnu/fuxi-adreno/fuxi_gpu_dcvs.h`、`fuxi_adreno.c` 與 `shim/fuxi-probe/gpu-clock.h`，均位於同一 ksrc。
- 小物件快取、swap hook 與 Hybrid 開關由既有 NativeMetal patch 0015／0013／0019／0020 核對；`nocb` 的意義由本機 Mesa `src/freedreno/vulkan/tu_util.cc` 核對。
- Loader 產生器 `work/adsp-battery/prepare-wlan-w18-loader.py` 的 `DAILY_TUNING` 與實機命令列相符；因此目前配置的 CPU 調頻、核心推薦、tcache、nocb、swap wait 與 6 ms offset 均已保留。
