# K 系列：核心硬體適配（000 線）

2026-11-14 起在 `work\adsp-battery\ksrc`（zgl97/ios-fuxi `979e2f08` 加本機 88 個提交）做的硬體適配。核心原始碼在 `ksrc\xnu\fuxi-*\`，CI 實際套用的是 harness 的 `xnu\patches\01xx-*.patch`（由 `ksrc\tools\sync-fuxi-*.py` 從原始碼重產）。

共通事項（各項不再重複）：

- **改原始碼後重產補丁**：在 WSL 跑 `python3 tools/sync-fuxi-adsp.py`（ADSP／PMIC／藍牙／音訊都在 0117）、`sync-fuxi-wlan.py`（0104）、`sync-fuxi-h1.py`（0103）、`sync-fuxi-backlight.py`（0109）；Windows 的 Python 會把補丁寫成 CRLF。產生的補丁複製到 harness 的 `xnu\patches\` 再建置。
- **開關優先序**：開機參數（`PE_parse_boot_argn`）先，沒有才讀 ADT `/chosen` 的 u32 屬性。日常命令列 607／608 bytes 已滿，所以新開關都同時提供 ADT 名稱，由 loader 產生器寫進 ADT。
- **預設全部關閉**：開關不給就不碰硬體；日常 loader 只打開已驗收的項目（現況見 B 系列的開機鏈項目）。
- **建置與上機**：照 `records\README.zh-TW.md` 的「共用的復現步驟」。下面的「復現」只寫這一項特有的旗標與要看的 console 行。
- **紀錄出處**：`journal\hw000-adaptation-status.zh-TW.md`（原 `work\hw000-adaptation-status.zh-TW.md`）的段落名，以及 ksrc `docs-lanes\*.md`。

## 電池與 ADSP

### K-001 ADSP 開機與 GLINK 電池讀值
- **日期**：2026-11-15 00:02（d5c44c3）～11-16 02:14 首次讀到正確電量
- **狀態**：採用
- **開關**：`fuxiadsp=<0..4>`，或 ADT `/chosen fuxi,adsp`（u32）。0／不給＝不碰 ADSP；1＝只讀盤點（SMEM 分區與項目、ADSP 的 SMP2P 狀態、AOSS 信箱、RSC、兩條 SPI 的 GIC enable），不寫任何東西；2＝啟動 ADSP 並建立 SMP2P、GLINK、QRTR service locator 與電池管理客戶端，只記錄讀值；3＝另外發布給 iOS（K-002）；4＝測試用假讀值（K-005）。與 `fuxiwlan` 同時設定時自動降為 1，除非 ADT `fuxi,adsp-wlan=1`（K-012）。
- **問題／現象**：iOS 固定顯示 SweetBattery 的預設值（100%、接電、未充電），沒有真實電量。高通平台的電量計、充電器都由音訊 DSP（ADSP／LPASS）上的 battery manager 管，AP 端只能透過 PMIC GLINK 通道問。
- **根因**：XNU 這邊沒有 ADSP 遠端處理器的啟動流程（PAS 認證、carveout 載入、AOSS load_state、RPMh 代投票）和 GLINK／QRTR 協定。
- **做法**：
  - 從 UniXNU-sheng `package/AdspProbe.cpp`／`ShengBattery.cpp`（commit `6880068`，BSD-2-Clause-Patent，授權檔 `xnu\fuxi-adsp\LICENSE.UniXNU-sheng`）移植；協定模組 `QcomGlink.c`、`QcomMdt.c`、`QcomQmp.c`、`QcomQrtr.c`、`QcomRpmh.c`、`QcomScm.h`、`QcomSmem.c`、`QcomSmp2p.c`、`FatVolume.c`、`ShengBattmgr.c`、`ShengQrtr.c` 原樣使用。
  - 本機新寫 `fuxi_adsp.c`（單一核心執行緒擁有全部步驟與協定狀態）、`fuxi_adsp_fw.c`（韌體從 `modem_a` 分區的 FAT 檔案系統原地讀，不另放檔案）、`fuxi_adsp_battery.c`（電池客戶端，通道 `PMIC_RTR_ADSP_APPS`）。
  - 與 sheng 不同處：這顆核心的 GIC 只有 GPU fence 一個 SPI handler，所以不用中斷，改輪詢 IPCC 接收暫存器（啟動中 1 ms，有流量後 500 ms 內每 2 ms，其餘 200 ms）與 RSC 完成狀態；先在 distributor 把 IPCC（SPI 229）與 RSC（SPI 5）遮罩，避免開機階段留下的 level 中斷打爆無主 EOI 路徑。MMIO 與 carveout 用 `kernel_map` VA＋pmap 映射，不用 `ml_io_map`（8 MiB 子映射是 KMA_NOFAIL）。
  - 裝置樹事實（fuxi live DTB，與 sheng 的 SM8550 相同）：`remoteproc-adsp`（`qcom,kalama-adsp-pas`），adsp PAS id 1 在 adspslpi `0x9ea00000`+`0x4680000`，adsp_dtb PAS id 36 在 `0x9e980000`+`0x80000`；SMEM `0x81d00000`+`0x200000`，TCSR mutex 3；smp2p-adsp 項目 443 進／429 出，remote pid 2；IPCC `0x408000`；GLINK 項目 478／479／480；AOSS `0xc300000`+`0x400`；apps RSC DRV 2 在 `0x17a20000`（TCS +`0xd00`）；cmd-db `0x81c60000`。全部在 XNU RAM（`0x8c0000000` 起）之外，`tools\mkadt-fuxi.py` 會拒絕和 reserved-memory 重疊的配置。
  - 韌體分區讀取靠 0106（`sweet_ufs.c`）新增的韌體分區讀取介面。
  - 補丁：harness `xnu\patches\0117-fuxi-adsp.patch`（本機新增）；`tools\sync-fuxi-adsp.py` 由原始碼重產。
- **復現**：
  1. 本機建核心（9g 或 5g 都可，ADSP 與 RAM 配置無關）。
  2. loader：`python -X utf8 work\adsp-battery\prepare-ram9g-loader.py <新 loader 名> <來源 loader> <核心產物>`，命令列加 `fuxiadsp=2`（命令列滿時改由產生器寫 ADT `fuxi,adsp`）。
  3. 上機 `-Seconds 180`。
  4. 預期 console：`FUXI ADSP: firmware adsp … KiB, adsp_dtb … KiB` → `FUXI ADSP: adsp_dtb authenticated and started` → `FUXI ADSP: adsp authenticated and reset; waiting for ready` → `FUXI ADSP: ready after … ms` → `FUXI ADSP: glink version agreed` → `FUXI BATTERY: channel up; notifications requested, first refresh` → `FUXI BATTERY: percent=… mV=… mA=…`。失敗行：`FUXI ADSP: failed at stage %d error %d (scm x0=… x1=…)`、`FUXI ADSP: crash reason …`。
- **主機測試**：`tools\test-fuxi-battery-prep.py`（harness `hw000-preparation.yml` 執行）。
- **驗證紀錄**：11-16 USB 測試開機 `adsp2`：`channel IPCRTR up`、GLINK 通；`adsp2b` 02:14（核心 ksrc 040332a，含 K-003 修正）`FUXI BATTERY: percent=100`、f2=10000，與 Android 同時讀數一致（GATE `percent=100 mV=4443 android_level=100`）：4388–4443 mV、滿充 4268 mAh／設計 4500 mAh、152 次循環。
- **參考來源**：UniXNU-sheng AdspProbe／ShengBattery（`6880068`）；Linux `drivers/remoteproc/qcom_q6v5_pas.c`、`drivers/soc/qcom/pmic_glink.c`、`drivers/power/supply/qcom_battmgr.c`（欄位意義對照）。
- **結論／未完成**：ADSP 啟動與電池讀值穩定。充電控制仍完全由 DSP 韌體負責，核心只送通知啟用請求，不寫其他東西。
- **出處**：journal「Claude 接續（19:10 起）」與「總結（03:40）」段；ksrc `docs-lanes\adsp.md`；記憶 `xiaomi13-adsp-battery`。

### K-002 SweetBattery 發布真實電量
- **日期**：2026-11-15 00:16（478bf32）；2026-11-16 02:22 上機驗證
- **狀態**：採用
- **開關**：`fuxiadsp=3`（或 ADT `fuxi,adsp=3`）。另有舊開關 `sweetbattery=1`（PM6150 電壓估算，只對 sweet 機型有意義，fuxi 不用）。
- **問題／現象**：K-001 只把讀值寫進 log，SpringBoard 的電池圖示、設定頁的電池百分比都還是預設值。
- **根因**：iOS 透過 `IOPMPowerSource` 類別（`AppleSmartBattery` 相容屬性）讀電量；SweetBattery（ios-sweet 繼承的內建服務）只有固定值或 PM6150 估算兩種來源。
- **做法**：`xnu\fuxi-adsp\SweetBattery.cpp` 新增 ADSP 來源：`fuxi_adsp_battery.c` 每輪刷新後呼叫 SweetBattery 更新 `CurrentCapacity`、`Voltage`、`Amperage`、`ExternalConnected`、`IsCharging`、`FullyCharged` 等屬性並送變更通知；讀不到前保留預設值。
- **復現**：loader 用 `fuxiadsp=3`；上機 `-Seconds 180`。預期 console：`SWEET BATTERY: ADSP battery manager, <百分比>% <mV>mV <mA>mA external=<0|1> charging=<0|1>`，之後 `SWEET BATTERY: published #<n> …`。畫面證據：狀態欄電量與設定 → 電池百分比相符。
- **主機測試**：`tools\test-fuxi-battery-publication.py`。
- **驗證紀錄**：11-16 02:22 `adsp3t`（第二輪鏈 bl4→amp2→adsp3t→amp3→bl5t，03:37 跑完）：`SWEET BATTERY: ADSP battery manager, 100% 4367mV -609mA external=1 charging=1`，SpringBoard 的 `IOPMPowerSource` 配對到 SweetBattery，截圖狀態欄有充電符號；巡覽 14 張截圖在 `work\statusbar-fix\sb-compare-adsp3t.png`。
- **參考來源**：ios-sweet SweetBattery 原始實作；Apple `IOPMPowerSource.h` 屬性鍵。
- **結論／未完成**：USB 測試開機已驗；使用者回報日常獨立開機曾仍顯示 100% 充電中（拔線後），待 mtdblk 紀錄（K-019）查。後續修正見 K-006～K-009。
- **出處**：journal「總結（03:40）」段；記憶 `xiaomi13-adsp-battery`。

### K-003 單電芯電量換算
- **日期**：2026-11-16 01:32（040332a）；02:14 上機驗證
- **狀態**：採用
- **開關**：無（隨 `fuxiadsp>=2` 生效）
- **問題／現象**：照 sheng 的算法讀到 48%，同時 Android 顯示 97%。
- **根因**：sheng 的機型是雙電芯，把兩顆電量計的 mAh 相加後再算百分比；小米 13 是單電芯，第二組欄位是 0 或重複值，相加後分母錯誤。battery manager 回報的 percent 欄位是 0.01% 單位（9600＝96%）。
- **做法**：`fuxi_adsp_battery.c` 直接用 battery manager 的 percent 欄位（除以 100）；mAh 原始值只取電量計 1。
- **復現**：同 K-001，比對 `FUXI BATTERY: percent=` 與 Android 設定頁（或 `adb shell dumpsys battery`）同時刻的數值，差距應在 1% 內。
- **主機測試**：`tools\test-fuxi-battery-prep.py` 內的換算案例。
- **驗證紀錄**：`adsp2b` 02:14 讀 100% 對 Android 100%。
- **參考來源**：Linux `qcom_battmgr.c` 的 `BATTMGR_BAT_STATUS` 欄位單位。
- **結論／未完成**：完成。
- **出處**：journal「總結（03:40）」段。

### K-004 充電器種類、真實充電資訊與 10 秒刷新
- **日期**：2026-11-16 02:48（26a4114）～10:55（1b4f5f8）
- **狀態**：採用
- **開關**：無（隨 `fuxiadsp=3`）
- **問題／現象**：充電時 iOS 只知道「有接電」，不知道是 USB SDP 還是 PD 快充；電流數字 60 秒才更新一次，插拔反應慢。
- **根因**：log 的充電器類型原本取 f8（一直是 SDP）；真正的充電器類型在 usb 屬性 f20（`BmUsbAdapter`）。SweetBattery 也沒把充電器類型發佈給 iOS，iOS 只知道「外接電源、充電中」。刷新週期沿用 sheng 的 60 秒。
- **做法**：26a4114 依 f20 決定 adapter family（SDP f20=1 → 500 mA；PD f20=6 → 1.2 A 等）寫進 SweetBattery 的 `AdapterDetails`；1b4f5f8 改用真實的充電器電壓、電流上限，並把刷新週期改為 10 秒（通知到達時仍立即刷新）。
- **復現**：`fuxiadsp=3` 上機，分別接 USB 電腦埠與 PD 充電器。預期 console：`SWEET BATTERY: published #… external=1 … charging=1 … <mA>mA`，`FUXI BATTERY: raw valid=…` 列出 f20 值。
- **主機測試**：`tools\test-fuxi-battery-publication.py`。
- **驗證紀錄**：USB 測試開機中途電源類型從電腦口 SDP（f20=1，輸入上限 500 mA）換成 PD（f20=6，上限 1.2 A），之後電池電流 +289～343 mA、charging=1，f9／f10 4.62–4.65 V、781–831 mA、f21=1200000、f4 為負（充電）；Android 開回來顯示 AC powered。amp3 那趟驗證 26a4114：adapter=`0xe000400a`（PD）。
- **參考來源**：Linux `qcom_battmgr.c` 的 `usb_type` 對應表。
- **結論／未完成**：完成。
- **出處**：journal「Claude 接續（19:10 起）」與「總結（03:40）」段。

### K-005 拔線測試讀值（fuxi,adsp=4）
- **日期**：2026-11-16 07:02（ba65d38）
- **狀態**：實驗（只供測試，不進日常）
- **開關**：`fuxi,adsp=4`（ADT）或 `fuxiadsp=4`。實際執行模式是 3，另外讓 SweetBattery 先收到一筆假讀值。
- **問題／現象**：USB 測試開機時手機一定接著電，無法驗證「拔線、未充電、電量下降」這條顯示路徑。
- **根因**：測試流程本身需要 USB。
- **做法**：`fuxi_adsp_battery.c` 在模式 4 時送一筆固定讀值 57%、未接電、未充電給 SweetBattery，之後真實讀值照常覆蓋。tour 腳本拖動亮度滑桿 8 次並截圖。
- **復現**：loader 寫 ADT `fuxi,adsp=4`、帶 tour 截圖；預期 console：`FUXI BATTERY: TEST (fuxi,adsp=4) SweetBattery now gets a staged reading: 57%, unplugged`。畫面：狀態欄顯示 57%、無閃電符號。
- **主機測試**：`tools\test-fuxi-battery-publication.py`。
- **驗證紀錄**：bl6t 那趟（11-16 07:19–07:39）截圖 `framebuffer-shot19-battery-staged-cc.png` 顯示 57% 未充電。
- **參考來源**：無。
- **結論／未完成**：顯示路徑正確。真正拔線的行為要靠獨立開機＋mtdblk 紀錄（K-019）驗。
- **出處**：journal「Claude 接續（19:10 起）」段。

### K-006 SweetBattery 讀取者紀錄
- **日期**：2026-11-16 07:08（bad6adf）
- **狀態**：採用（診斷）
- **開關**：無（隨 `fuxiadsp=3`）
- **問題／現象**：獨立開機時狀態欄仍顯示「100% 充電中」，不知道是 SweetBattery 沒更新還是 iOS 的讀取者讀到舊值。
- **根因**：查證中（見結論）。
- **做法**：SweetBattery 每次被讀時記錄讀取的行程名：開機後前 16 次全記，之後每次值改變後再記 4 次。
- **復現**：`fuxiadsp=3` 上機，預期 console：`SWEET BATTERY: read #<n> by <行程名> (published #<m>: <百分比>% external=… charging=…)`；若仍是預設值則是 `(still the fallback)`。
- **主機測試**：無（只是 log）。
- **驗證紀錄**：之後各趟 `fuxiadsp=3` 上機的 console 都有這幾行（讀取者行程名照實記錄在各趟 `console.txt`）。
- **參考來源**：無。
- **結論／未完成**：USB 開機時讀取者拿到的是新值；獨立開機的「100% 充電中」要靠 mtdblk 紀錄比對，仍未結案。
- **出處**：journal「更正（07:50）」段。

### K-007 電池欄位逐項過期（TTL）
- **日期**：2026-11-16 14:45（b6ce046）
- **狀態**：採用
- **開關**：`fuxibatttl=<秒>`（預設 90）
- **問題／現象**：ADSP 某一欄位暫時讀不到時，SweetBattery 會一直沿用很久以前的值，例如拔線後仍顯示接電。
- **根因**：原本整筆讀值只要有一欄成功就整筆視為新鮮。
- **做法**：`fuxi_adsp_battery.c` 為每個欄位記錄最後成功時間，超過 TTL 的欄位標為過期；過期的接電／充電狀態不發布，改回保守值。同提交加入 `fuxi-battery-prep` 的新鮮度模型與 `docs-lanes\battery-publication-checkpoint.md`、`battery-freshness.md`。
- **復現**：`fuxiadsp=3`，可縮短 TTL 觀察（`fuxibatttl=30`）。預期 console：`FUXI BATTERY: percent=… (stale)`、`FUXI BATTERY: rejected field <n> value <v>`。
- **主機測試**：`tools\test-fuxi-battery-prep.py`（新鮮度案例）、`tools\test-fuxi-battery-publication.py`。
- **驗證紀錄**：Run 23（`native-hw000rtc-shortpause-boot-1`，11-16 18:11:20）在第 50 次取樣（距上次成功 96.7 s）觸發過期，第 80 次取樣恢復。
- **參考來源**：無。
- **結論／未完成**：完成。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段；ksrc `docs-lanes\battery-freshness.md`、`battery-publication-checkpoint.md`。

### K-008 電池查詢暫停（GET pause）實驗
- **日期**：2026-11-16 16:09（b6be873）～16:36（acb3fcd）；17:21、18:11 上機
- **狀態**：實驗（已驗證，不進日常）
- **開關**：`fuxibatpause=<毫秒>`（0 或 130000）、`fuxibatpausedelay=<毫秒>`；loader 產生器 `prepare-ram9g-loader.py --battery-get-pause-ms 130000 --battery-get-pause-delay-ms <ms> --battery-audit`。
- **問題／現象**：要驗證 K-007 的過期機制在真實「讀不到」時的行為，需要可控地讓 ADSP 查詢停一段時間。
- **根因**：（實驗工具）
- **做法**：`fuxi_adsp_battery.c` 在指定延遲後暫停送 GET 請求指定毫秒數，期間紀錄每次 SweetBattery 的讀取；`--battery-audit` 加讀 HAP525 唯讀證據（同提交）。
- **復現**：`python -X utf8 work\adsp-battery\prepare-ram9g-loader.py <名> <來源> <核心> --battery-get-pause-ms 130000 --battery-audit`，上機 `-Seconds 300`。預期 console：`FUXI BATTERY: poll-pause begin …` 與 `poll-pause end …`。分析：`python -X utf8 work\statusbar-fix\analyze-battery-pause.py <run 資料夾>`。
- **主機測試**：`tools\test-fuxi-battery-pause.py`。
- **驗證紀錄**：Run 20（`native-hw000batpause-hap-boot-1`，17:21:45）暫停 42569→172570 ms；Run 23（`native-hw000rtc-shortpause-boot-1`，18:11:20）暫停 42192→172193 ms，120 次取樣、6 份快照、192 列、0 解析錯誤，報告 `work\statusbar-fix\battery-pause-short-20261116-1817.json`。
- **參考來源**：無。
- **結論／未完成**：過期與恢復都照設計。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段；ksrc `docs-lanes\battery-poll-pause-checkpoint.md`。

### K-009 SweetBattery 改走 IOKit work loop 發布
- **日期**：2026-11-16 21:45（5a8b7e9）
- **狀態**：採用
- **開關**：無
- **問題／現象**：電池客戶端的 thread call 直接改 SweetBattery 屬性，和 iOS 讀屬性的路徑沒有同步，有競態風險。
- **根因**：IOService 屬性更新應在該服務的 work loop 上做。
- **做法**：SweetBattery 加 `IOInterruptEventSource`，電池客戶端只排一個事件，實際更新在 work loop 執行。
- **復現**：同 K-002；console 與先前相同，差別在不再出現交錯的發布序號。
- **主機測試**：`tools\test-fuxi-battery-publication.py`。
- **驗證紀錄**：CI fast 43878944772、9g 43878944603、5g 43878944613（核心 `e59e5cb8…`）。11-17 07:38 聯合趟 `native-hw000wlan-joint1-boot-1`：接電狀態 0↔1 切換正確，140 次查詢 0 逾時。
- **參考來源**：Apple IOKit `IOInterruptEventSource` 用法。
- **結論／未完成**：完成。
- **出處**：journal「Codex 再接續（11-16 21:31 起）」段。

### K-010 充電證據工具
- **日期**：2026-11-16 15:24（a948742）
- **狀態**：採用（工具）
- **開關**：無
- **問題／現象**：充電驗收需要把 console、Android 讀數、時間軸對齊，每次手算容易出錯。
- **根因**：（工具）
- **做法**：`ksrc\tools\fuxi-charge-evidence.py`：讀上機紀錄中的 `FUXI BATTERY:`／`SWEET BATTERY:` 行與 ADT `fuxi,adsp`，輸出插拔事件、電流變化、讀取者的表格與判定。
- **復現**：`python3 tools/fuxi-charge-evidence.py <run 資料夾>/console.txt`（WSL 或 Windows `python -X utf8`）。
- **主機測試**：`tools\test-fuxi-charge-evidence.py`。
- **驗證紀錄**：11-17 聯合 ADSP／WLAN 拔插趟（07:38）、akswrap 趟（電量 4234–4248／4249 mAh）都用它整理。
- **參考來源**：無。
- **結論／未完成**：完成。
- **出處**：ksrc `docs-lanes\charging-acceptance.md`。

## 共用電源與音訊

### K-011 ADSP 與 WLAN 共用 RPMh（序列化與隔離）
- **日期**：2026-11-16 11:26（93201ca）
- **狀態**：採用
- **開關**：無（ADSP 或 WLAN 任一啟用時生效）
- **問題／現象**：ADSP（K-001）和 WLAN（K-041 起）都要對 apps RSC 送 RPMh 投票（lcx／lmx、WLAN 電源軌）。兩邊各自寫 TCS，同時進行時可能互相覆蓋，且某一方失敗後 RSC 狀態不明。
- **根因**：RSC 的 TCS 是共用硬體；沒有互斥鎖，也沒有「狀態不明就停用」的規則。
- **做法**：新增 `xnu\fuxi-adsp\fuxi_rpmh_shared.c`／`.h`：全域 mutex 串行化所有 RPMh 交易；ADSP 用 active TCS 1、WLAN 用 TCS 0；任一交易逾時或完成狀態不符時把共用 RSC 標為隔離（quarantined），之後雙方都不再送。
- **復現**：任一 ADSP 或 WLAN 上機都會用到。異常時預期 console：`FUXI ADSP: rpmh cleanup failed; shared RSC quarantined`；正常時 `FUXI ADSP: rpmh vote lcx=… lmx=… done=1`。
- **主機測試**：`ksrc\tools\test-fuxi-rpmh-shared.py`（`hw000-preparation.yml`）。
- **驗證紀錄**：之後所有 ADSP、WLAN 及聯合趟（K-012）都未觸發隔離。
- **參考來源**：Linux `drivers/soc/qcom/rpmh-rsc.c` 的 TCS 分配與 `tcs_is_free` 規則。
- **結論／未完成**：完成。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段。

### K-012 ADSP 與 WLAN 聯合測試開關
- **日期**：2026-11-17 07:35（72a31b8）；07:38 上機
- **狀態**：實驗（已驗，日常未開）
- **開關**：ADT `fuxi,adsp-wlan=1`。沒有它時，命令列同時有 `fuxiwlan` 與 `fuxiadsp>=2` 會把 ADSP 降為 1（只讀盤點）並記 `FUXI ADSP: fuxiadsp=… refused with fuxiwlan (combined hardware validation pending); surveying only`。
- **問題／現象**：ADSP 與 WLAN 同時啟用還沒驗過共用 RPMh、SMEM、IPCC 的行為，先以預設拒絕保護日常。
- **根因**：（安全閘門）
- **做法**：`fuxi_adsp.c` 的 `fuxi_adsp_mode()` 只有在 ADT `fuxi,adsp-wlan=1` 時才允許和 WLAN 並行。loader 產生器 `prepare-wlan-w18-loader.py --with-adsp` 會同時寫 ADT `fuxi,adsp=3`、`fuxi,pmic=3`、`fuxi,adsp-wlan=1`，並檢查核心含這個開關的字串、命令列沒有 `fuxiadsp=`／`fuxipmic=`。
- **復現**：`python -X utf8 work\adsp-battery\prepare-wlan-w18-loader.py build --like <已驗 native Wi-Fi loader> --artifact <核心> --name <新名> --with-adsp`；上機時間依要觀察的拔插次數決定，中途手動拔插 USB。預期 console：`FUXI ADSP: fuxiadsp=3 alongside fuxiwlan (fuxi,adsp-wlan=1: combined test, shared RSC mutex)`，之後 `FUXI BATTERY:` 與 `FUXI WIFI IOS:` 兩邊都持續輸出。
- **主機測試**：`ksrc\tools\test-fuxi-rpmh-shared.py`。
- **驗證紀錄**：11-17 07:38 `native-hw000wlan-joint1-boot-1`（本機 9g `kernel-local-joint1-9g-artifact`，ADT `fuxi,adsp=3`、`fuxi,pmic=3`、`fuxi,adsp-wlan=1`）：ADSP 與 WLAN 同時起來；拔線時 `FUXI BATTERY` 報 external=0 charging=0，插回 external=1 charging=1，140 輪 0 逾時。同趟使用者手動加入 `<SSID>` 成功，但連上那一刻 securityd 的 AKS sel 10 被拒 `0xe00002c7`（K-059 修）；「日期與時間」卡死（U 系列 fairplayd 項）；mediaserverd 4 次 SIGABRT（同前幾趟）。
- **參考來源**：無。
- **結論／未完成**：聯合運作正常；日常 loader 仍只開 Wi-Fi，ADSP 要等獨立開機的電量顯示問題（K-002 結論）查清再合併。
- **出處**：journal「Codex 再接續（11-16 21:31 起）」之後的 11-17 段落；記憶 `xiaomi13-wlan-state`。

### K-013 CS35L41 喇叭功放盤點
- **日期**：2026-11-15 00:37（417dcf3）；2026-11-16 02:48（26a4114）
- **狀態**：實驗（只讀；未出聲）
- **開關**：`fuxiamp=<1|2>`，或 ADT `fuxi,amp`。1＝只讀盤點：GCC 投票 `0x52008`／`0x52010`／`0x52018`、QUP2 五個 branch（core `0x233d4`、s_ahb `0x233d0`、m_ahb `0x233cc`、core_2x `0x23004`、s0 `0x1e004`）、SE0 時脈源 `0x1e010`、四支腳位；branch 全開時再讀 engine 狀態。2＝照 UniXNU-sheng `AudioProbe.cpp` 的 setupClocks／setupPins／setupBus 把 QUP2 SE0 I2C 帶起來（400 kHz、FIFO 模式），兩顆功放各自解除 reset（低 2 ms、拉高、等 10 ms OTP 開機），讀 DEVID `0x0`、REVID `0x4`、IRQ1_STATUS3 `0x10018`、IRQ1_STATUS4 `0x1001c`，不寫功放；最後重新 reset，腳位與投票還原。
- **問題／現象**：要讓喇叭出聲，得先確認兩顆 CS35L41（`cs35l41@40` 「B」、`@42`「T」）在 I2C 上可存取。
- **根因**：mode 2 第一版（amp2）讀不到功放：reset 腳 gpio182／183 是 eGPIO，開機時 ctl=`0x801`＝歸 LPASS 音訊島，AP 端直接驅動無效；I2C 匯流排、時鐘、engine 本身正常。
- **做法**：`xnu\fuxi-adsp\fuxi_amp.c`、`GeniI2c.c`（sheng 原樣）；26a4114 驅動 reset 前先把 eGPIO 182／183 的 `egpio_enable`（TLMM ctl bit 12）設起來，把腳位從 LPASS 拿回 AP。I2C 腳 gpio0 SDA／gpio1 SCL、function 2（qup2_se0_l0／l1_mirb）、2 mA、上拉；engine SPI 373 先遮罩，全部輪詢。窗口：QUP2 SE0 `0x880000`+`0x4000`、GCC `0x100000`、TLMM `0xf100000`、GICD `0x17100000`。
- **復現**：命令列加 `fuxiamp=2`（或 ADT `fuxi,amp=2`），上機 `-Seconds 120`。預期 console：`FUXI AMP: started mode 2` → `FUXI AMP: survey vote 0x52008=…` → `FUXI AMP: amp B@0x40 … devid=0x35a40 … revid=0xb2 …` 與 `amp T@0x42 …`；失敗行 `FUXI AMP: bring-up stopped at step <n> (6 = both read; …)`。
- **主機測試**：無專用測試（只讀、全還原）。
- **驗證紀錄**：11-16 第二輪鏈 `amp2`（26a4114 前，reset 放不開，讀不到）→`amp3`（26a4114 後）：兩顆 CS35L41 都回應，DEVID `0x35a40`、REVID `0xB2`，IRQ1_STATUS4=`0x3`（OTP 開機完成）、STATUS3 無 OTP 錯誤；reset 腳位這次真的放開（ctl `0x1bc0`、輸入 0→1）；讀完放回 reset，腳位與時鐘票還原。證據：amp3 `boot.log`。
- **參考來源**：UniXNU-sheng `AudioProbe.cpp`（`6880068`）；Linux `sound/soc/codecs/cs35l41*.c`；fuxi live DTB `i2c@880000`。
- **結論／未完成**：功放可存取。出聲還缺：ADSP 音訊圖（K-014、K-015）、功放韌體與調校（`cs35l41-dsp1-spk-prot` 系列）、iOS 音訊裝置。
- **出處**：journal「總結（03:40）」段；記憶 `xiaomi13-adsp-battery`、`xiaomi13-audio-spf`。

### K-014 音訊 SPF 狀態查詢
- **日期**：2026-11-17 11:32（6f28814）～12:01（4b3402d）
- **狀態**：實驗（已通，下一步未做）
- **開關**：`fuxiaudiospf=<1|2>`，或 ADT `fuxi,audio-spf`。1＝APM 格式查詢（40 bytes）；2＝裸 GPR 狀態查詢（24 bytes）。loader：`prepare-wlan-w18-loader.py --audio-spf [--audio-spf-format apm|bare]`。
- **問題／現象**：要在 ADSP 上建音訊圖，第一步要知道 ADSP 的 SPF（Signal Processing Framework，AudioReach）是否就緒。
- **根因**：第一版查詢被拒：GPR 標頭的 client 位元（bits 16–19）不符；首次查詢常回 `AR_EFAILED`，要再問。
- **做法**：`xnu\fuxi-adsp\fuxi_audio_spf.c`：在 GLINK `adsp_apps` 通道（512 bytes × 20 個 intent）註冊只查詢的客戶端，送 APM `GET_SPF_STATE`。fd7ee5e 記錄被拒回覆的標頭；a4e663d 接受 GPR client data 位元並加裸查詢模式 2；4b3402d 每次用新 token 重試，最多 100 次、間隔 100 ms、每次回覆期限 1 s。
- **復現**：`prepare-wlan-w18-loader.py build --like <已驗 loader> --artifact <核心> --name <新名> --with-adsp --audio-spf`，上機 `-Seconds 180`。預期 console：`FUXI AUDIO SPF: registered adsp_apps query-only client` → `FUXI AUDIO SPF: state query queued bytes 40` → `FUXI AUDIO SPF: state 1 after <n> queries (…)`。失敗行：`not ready after … queries`、`rejected reply …`、`channel timeout`。
- **主機測試**：`ksrc\tools\test-fuxi-audio-spf.py`（26106 種 GPR 標頭組合）。
- **驗證紀錄**：11-17 `passivespf` 11:35（被拒，取得標頭）、`spfclient` 11:56（client 位元修正）、`spfretry` 12:04：`state 1 after 2 queries`（第二次查詢就緒）。
- **參考來源**：Linux `sound/soc/qcom/qdsp6/audioreach.c`、`q6apm.c`、`drivers/soc/qcom/apr.c`（GPR）。
- **結論／未完成**：SPF 就緒。之後還缺 PRM（時脈／電源資源）、音訊圖（ACDB，見 K-016）、CS35L41 播放、iOS 音訊裝置。
- **出處**：記憶 `xiaomi13-audio-spf`；ksrc `docs-lanes\audio.md`。

### K-015 GPR 音訊準備（主機模型）
- **日期**：2026-11-16 14:09（51e7ca9）
- **狀態**：準備（主機模型，未上機）
- **開關**：無
- **問題／現象**：K-014 之前需要先確定 GPR 封包格式、port 與 token 規則，避免上機才發現格式錯。
- **根因**：（準備）
- **做法**：`ksrc\xnu\fuxi-audio-prep\fuxi_audio_prep_gpr.c`／`.h`（GPR 標頭編解碼、APM 命令封包、回覆驗證）與 C 主機測試 `test_gpr.c`。
- **復現**：WSL `python3 tools/test-fuxi-audio-prep.py`。
- **主機測試**：`ksrc\tools\test-fuxi-audio-prep.py`。
- **驗證紀錄**：主機測試通過；K-014 的上機格式由這份模型修正而來。
- **參考來源**：Linux `include/linux/soc/qcom/apr.h`、`audioreach.h`。
- **結論／未完成**：已被 K-014 使用。
- **出處**：ksrc `docs-lanes\audio-preparation.md`。

### K-016 原廠音訊設定擷取
- **日期**：2026-11-17 17:44（824e8c2）
- **狀態**：採用（資料）
- **開關**：無
- **問題／現象**：要建音訊圖，需要原廠的 ACDB 檔名、喇叭 TDM 後端格式和功放 mixer 預設值。
- **根因**：（資料蒐集）
- **做法**：`work\statusbar-fix\fetch-android-audio-config.py` 從 Android（adb，唯讀）搜尋 `/vendor/etc`、`/odm/etc`、`/vendor/odm/etc` 的音訊設定，存到 `work\adsp-battery\android-audio-config-1117\`；ksrc 記錄：ACDB `Tutu_acdb_cal.acdb`，喇叭後端 `TDM-LPAIF-RX-SECONDARY` 48 kHz／2 聲道／24 bit，功放 mixer 預設值。
- **復現**：Android 開機、USB 連線後 `python -X utf8 work\statusbar-fix\fetch-android-audio-config.py --output work\adsp-battery\android-audio-config-<日期> --serial <序號>`。
- **主機測試**：無。
- **驗證紀錄**：擷取檔存於上述資料夾（不公開：屬原廠檔案）。
- **參考來源**：Android `audio_platform_info`、`mixer_paths_*.xml`。
- **結論／未完成**：資料已備；ACDB 解析未做。
- **出處**：ksrc `docs-lanes\audio.md`；記憶 `xiaomi13-audio-spf`。

## 顯示、紀錄與注入

### K-017 背光模式 4（AppleARMBacklight＋DCS 0x51）
- **日期**：2026-11-14 22:52（eafc778）；2026-11-16 03:02（7928af8 巡覽）、02:51～03:37 上機
- **狀態**：採用（日常開啟）
- **開關**：`fuxibacklight=<0..4>`（4＝本項；日常命令列含 `fuxibacklight=4`）；`fuxibacklighttrace=1` 記錄每個 IOKit 呼叫。
- **問題／現象**：iOS 的亮度滑桿、自動亮度沒有作用，螢幕固定亮度。
- **根因**：iOS 的 backboardd 找的是 `AppleARMBacklight` 類別服務；ios-fuxi 沒有提供。面板亮度要透過 DSI DCS 命令 0x51（Set Display Brightness）設定，而 DSI 傳輸由顯示擁有者（`fuxi_gpu_scanout.inc`）掌握，不能從別的執行緒直接送。
- **做法**：
  - `xnu\fuxi-backlight\FuxiDsiBacklight.cpp`：發佈 `AppleARMBacklight`（min 0、max 面板最大值），接收 `setProperties` 的亮度值，換算後交給顯示擁有者。
  - `fuxi_dsi_backlight_logic.h`：亮度換算、淡入淡出、合併請求的純函式。
  - `xnu\fuxi-adreno\fuxi_gpu_scanout.inc`：在兩次畫面傳輸之間送 DCS 0x51（不和 scanout 搶 DSI）。
  - 補丁 0098（本機修改）、0109（背光）；`tools\sync-fuxi-backlight.py` 重產。
  - 7928af8：`fuxitour` 巡覽腳本把控制中心亮度滑桿往下、往上各拖一次並截圖（`brightness-low`／`brightness-high`）。
- **復現**：命令列 `fuxibacklight=4`，帶 tour；上機 `-Seconds 240`。預期 console：`FUXI BACKLIGHT DSI: published AppleARMBacklight min=0 max=… value=…` → 拖動時 `FUXI BACKLIGHT DSI: brightness #<n> goal=… sent=… fade_ms=… published=…`。畫面：兩張截圖亮度明顯不同（需肉眼或手機前方拍照，framebuffer 截圖看不到背光）。
- **主機測試**：harness `tests\test-backlight-dsi.py`（workflow `kernel-backlight-dsi.yml`）。
- **驗證紀錄**：11-16 bl4 02:51（路徑通）；bl5t 03:16–03:37：亮度值 1135→65→1329，每個 DCS 46–154 µs。
- **參考來源**：Linux `drivers/gpu/drm/msm/dsi/dsi_host.c`、MIPI DCS 規格 0x51；Kerfand fuxi iOS17 的亮度先例（記憶 `xiaomi13-hardware-reference-projects`）。
- **結論／未完成**：完成；日常「滑兩下就停」由 K-018 修。
- **出處**：journal「總結（03:40）」段；ksrc `docs-lanes\backlight.md`；記憶 `xiaomi13-backlight-mode4`。

### K-018 DSI 錯誤容忍與等滿一幀
- **日期**：2026-11-16 07:02（ba65d38）、07:43（7af418a）
- **狀態**：採用
- **開關**：無（隨 `fuxibacklight=4`）
- **問題／現象**：日常使用時亮度「滑兩下就停」：之後再拖滑桿都沒反應，直到重開機。
- **根因**：第一版只要一個 DCS 命令結果不確定（DSI 錯誤旗標）就永久停用背光；而 CMD DMA 完成等待太短，偶發逾時被當成錯誤。
- **做法**：ba65d38 照 Linux `dsi_error` 的方式讀取並清除 DSI 錯誤狀態，只有連續 6 次錯誤才停用；7af418a 等 `CMD_DMA_DONE` 最長 20 ms（滿一幀）。
- **復現**：同 K-017，但讓 tour 連續拖動滑桿 8 次以上（`fuxitour` 預設）；預期 console 不出現停用訊息，`brightness #` 序號持續增加。
- **主機測試**：harness `tests\test-backlight-dsi.py`。
- **驗證紀錄**：bl6t（11-16 07:19–07:39）約 2900 次 DCS 不停；bl7t 約 3600 次請求，4 次 DMA 完成時間 7.9 ms，核心 `8579ba89…`。
- **參考來源**：Linux `drivers/gpu/drm/msm/dsi/dsi_host.c` 的 `dsi_error` 處理。
- **結論／未完成**：完成。
- **出處**：journal「更正（07:50）」段；記憶 `xiaomi13-backlight-mode4`。

### K-019 獨立開機的 console 紀錄寫入 mtdblk（fx_log）
- **日期**：2026-11-16 07:43（7af418a）～07:46（d96adda）
- **狀態**：採用（日常開啟）
- **開關**：ADT `fuxi,log=1` 或 `fuxilog=1`，且分區已蓋章；沒有章就不寫任何東西。
- **問題／現象**：日常是不接電腦的獨立開機（slot b／常駐選單），沒有 USB 就沒有即時 console，獨立開機才出現的問題（如 K-002 的「100% 充電中」）無從查。
- **根因**：小米 13 沒有 `logdump` 分區（7af418a 原本以為有）。
- **做法**：
  - `xnu\fuxi-unixnu\sweet_ufs.c`（補丁 0106）的 fx_log：寫入 GPT 分區 `mtdblk`（LUN 0，32 MiB；11-16 時全為 0，Android、abl、xbl、uefi 都沒有使用）。
  - 只寫分區開頭 2049 個 4 KiB 區塊：0＝`SWEETLOG` 標頭（版本 2）＋章；1..1024＝環狀緩衝（最後 4 MiB console）；1025..2048＝開頭 4 MiB（環狀繞回後凍結）。其他任何分區、區塊都不寫（`fx_log_write_allowed` 檢查）。
  - 章：Android 端在區塊 0 的 byte 2048 寫 `FUXILOG1 STAMPED`（`work\adsp-battery\hw000\fuxi-log.sh stamp`）。
  - 每 10 秒（`ufslogsecs`）寫回一次；在 ADSP 啟動前開始，保留其啟動過程。
- **復現**：
  1. 主機（Git Bash）跑 `work\adsp-battery\hw000\fuxi-log.sh stamp`（一次即可）：先把整個分區 dd 到手機 `/data/local/tmp/fuxilog-backup.img`、拉回主機並比對 SHA-256，不符就停止，相符才寫章。
  2. loader 的 ADT 寫 `fuxi,log=1`。
  3. 進 iOS 使用後回 Android，`fuxi-log.sh pull` 拉回，`python -X utf8 work\adsp-battery\hw000\fuxi-log-parse.py <拉回的檔>` 解析。
  4. **下次進 iOS 前一定先 pull**，否則被覆蓋；`launch-loader-check.ps1` 每趟開機前會自動拉。
- **主機測試**：無專用測試；寫入範圍由 `fx_log_write_allowed` 限制。
- **驗證紀錄**：bl7t 拉回 799006 bytes；分區原始內容備份在 `D:\xiaomi13\fuxi_Backup\mtdblk-20261116`（sda19）。
- **參考來源**：Linux `drivers/mtd/mtdoops.c` 的環狀紀錄設計（只參考概念）。
- **結論／未完成**：完成。
- **出處**：journal「更正（07:50）」段；記憶 `xiaomi13-standalone-log-mtdblk`。

### K-020 核心在 exec 時注入函式庫（fxinj，補丁 0118）
- **日期**：2026-11-16 09:24（9fa23d5）、09:28（a037bd3）；11-17 13:00（48a46c0，bit 2）、19:23（3d8e39e，wifid）
- **狀態**：採用（日常 `fuxi,inject=2`）
- **開關**：`fxinj=<位元>` 或 ADT `fuxi,inject`（u32，開機時讀一次）。bit 0（1）＝App 主程式（`.../NAME.app/EXECUTABLE`，SpringBoard 除外）注入 `/usr/local/lib/fuxi/libfuxi-app.dylib`；bit 1（2）＝SpringBoard 注入 `/usr/local/lib/fuxi/libfuxi-sb.dylib`；bit 2（4）＝`/usr/sbin/mediaserverd` 注入同一份 `libfuxi-sb.dylib`（震動，K-033）；bit 3（8）＝wifid 依完整路徑注入（Wi-Fi 診斷，K-063）。
- **問題／現象**：SpringBoard 的狀態欄、手電筒按鈕等要改 iOS 行為（U 系列），但在 SpringBoard 的 launchd job 設 `DYLD_INSERT_LIBRARIES` 沒有作用。
- **根因**：launchd（20H392）會丟掉 job `EnvironmentVariables` 裡所有 `DYLD_` 變數（`DYLD_PRINT_*` 除外，log：`Disallowing environment variable: %s`），只有 label 不是 `com.apple.` 開頭的 job 才放行。
- **做法**：補丁 `xnu\patches\0118-fuxi-exec-inject.patch`、`xnu\fuxi-inject\fuxi_exec_inject.h`（純函式，不用 `strrchr`）：exec 時依路徑判斷，把變數加進新行程的環境。dyld 會接受，因為 H1 AMFI 的 dyld policy 回答（補丁 0103，請求 0x5a）全部放行（函式庫不存在也不會失敗）。移植自 GPU 線的 0121（去掉啟動加速 hook）。概念同 HackiOS（hakios-xnu-kernel `xnu/hakios.patch`，`kern.exec_inject`，MIT）。
- **復現**：ADT `fuxi,inject=2`，並把 `libfuxi-sb.dylib` 放進 root（`launch-loader-check.ps1 -Dylib <檔> -DylibSha <SHA256>` 會暫存安裝）。預期：SpringBoard 的 log 有函式庫自己的啟動訊息（U 系列各項）；`launchctl` 不需改。
- **主機測試**：`ksrc\tools\test-fuxi-exec-inject.py`。
- **驗證紀錄**：11-16 狀態欄 shape 各趟（U 系列）；11-17 震動（mediaserverd）、Wi-Fi 稽核（wifid）各趟。
- **參考來源**：HackiOS `kern.exec_inject`（MIT）；GPU 線補丁 0121。
- **結論／未完成**：完成；日常 ADT `fuxi,inject=2`。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段。

## RAM

### K-021 9 GiB RAM 配置（ram9g 變體）
- **日期**：2026-11-16 10:19（fee0512）；12:21 起上機；16:10:51 隨 chain-v6 進日常
- **狀態**：採用（日常）
- **開關**：建置期變體，不是開機參數：harness `xnu\variants\ram9g.patch`、workflow `kernel-adsp-ram9g.yml`（Intel runner 版 `kernel-adsp-ram9g-intel.yml`）；本機 `build-kernel.ps1 -Ram 9g`。loader：`prepare-ram9g-loader.py --ram-layout 9g`（預設）。
- **問題／現象**：原配置 XNU 只用 5 GiB（5088 MiB），12 GB 機型大半記憶體閒置，App 容易被 jetsam 收掉。
- **根因**：ios-fuxi 的記憶體窗口是保守的單一 5 GiB 區段；GPU scratch 放在窗口緊接處，擴大窗口會撞上。
- **做法**：`ram9g.patch` 把 XNU 可用區改成相鄰 3+6 GiB（fresh FDT 已驗證不跨保留區）：XNU usable `0x23e000000`（9184 MiB），GPU scratch 移到 `0xafe000000`；USB 讀取改為有界。`tools\mkadt-fuxi.py`、`tools\ci\kernel-inputs.py`、`tools\ci\prepare-kernel.py` 支援兩種配置。
- **復現**：本機 `build-kernel.ps1 -Ram 9g -Name kernel-local-<名>-9g-artifact`；`python -X utf8 work\adsp-battery\prepare-ram9g-loader.py <名> <來源 loader> <核心產物>`。預期：開機進 SpringBoard，console 的記憶體統計（free＋wired 頁數）大於 5g 配置。loader 產生器會核對韌體、payload、核心、root extents 與 RAM 一致性。
- **主機測試**：`ksrc\tools\test-fuxi-ram9g.py`。
- **驗證紀錄**：CI `43791547599`（harness `36c962d`）成功，40 項 manifest 全通過；新 loader `native-ram9g-tour-user-loader` 檢查全過；12:21:48 第八趟 RAM 樣本（K-023）通過；12:32:01 第九趟整顆 9g（`chain-v5-ram9g`，boot SHA-256 `b7a81bd0…`）見 582815 free＋4961 wired 頁、SpringBoard hook 與 ADSP 電量發佈，12:38:51 回 Android、無 panic（當時未部署）。之後所有 9g 趟次與 chain-v6 起的日常都用此配置。
- **參考來源**：fuxi live FDT `/memory` 與 `reserved-memory`。
- **結論／未完成**：9 GiB 是 12 GB 機型已核對的配置，不是硬體上限；更多 RAM 需要多段 admission（K-024）。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段。

### K-022 RAM SKU 與實際配置分開
- **日期**：2026-11-16 16:28（6166ed6）
- **狀態**：採用
- **開關**：loader `--ram-sku auto|8g|12g`（預設 auto）→ ADT `fuxi,ram-sku`；ios-fuxi 入口的 incoming-FDT guard。
- **問題／現象**：「5g／9g」是 XNU 的配置名，不代表手機是 8 GB 還是 12 GB 機型；拿 12 GB 配置開 8 GB 機會壞。
- **根因**：原本把配置名當成硬體規格。
- **做法**：6166ed6 把實體 SKU（live FDT `/memory/ddr_size`，四個 bytes，`0000000c`＝12 GB）與允許的配置分開；loader 產生器寫 ADT `fuxi,ram-sku` 並在 SKU 不符時拒絕。ios-fuxi 本機提交 `5f04f26` 加 incoming-FDT guard：入口核對 SKU 與配置，相符才印 `RAM_PROFILE_OK12_9G`。
- **復現**：loader 用 `--ram-sku auto`；預期 console：`RAM_PROFILE_OK12_9G`。
- **主機測試**：`ksrc\tools\test-fuxi-ram-sku.py`；`work\boot-chain\test-loader-sku-preflight.py`、`test-runtime-ram-profile.py`；private live FDT 重播與 423 cases／2966 assertions（ASan），入口 smoke 5g／9g 各 6 cases／46 assertions。
- **驗證紀錄**：第 20 趟暫時 loader 通過 `RAM_PROFILE_OK12_9G` 並進 SpringBoard。目前實機是 12 GB SKU。
- **參考來源**：無。
- **結論／未完成**：8 GB 實機的拒絕路徑與 ARM fault／reset 行為未上機驗；日常 chain-v6 當時尚未更新此 guard。
- **出處**：journal「歷史驗收摘要」段（L76、L86）。

### K-023 高位址 RAM 樣式測試（ramtest）
- **日期**：2026-11-16 11:57（d4bc0d0）；12:21、第 13 趟上機
- **狀態**：實驗（已驗，按需開）
- **開關**：ADT `fuxi,ramtest`；loader `prepare-ram9g-loader.py --ramtest [--ramtest-mib 128|512]`。
- **問題／現象**：9 GiB 配置要證明新增的高位址記憶體真的可讀寫，不只是開得了機。
- **根因**：（驗證工具）
- **做法**：`xnu\fuxi-adsp\fuxi_ramtest.c`、`fuxi_ramtest_pattern.h`：開機後配置指定大小，只接受舊 5 GiB 窗口以上的頁；寫四組樣式、清 cache 後讀回比對，結束釋放。實體位址落在配置之外或配置被拒就不寫。
- **復現**：`prepare-ram9g-loader.py <名> <來源> <核心> --ramtest --ramtest-mib 512`；上機 `-Seconds 180`。預期 console：`FUXI RAMTEST: allocated bytes=… pages=… high-pages=… physical=…` → 四次 `FUXI RAMTEST: pass=<n> … cache-evicted verified` → `FUXI RAMTEST: released bytes=… completed=4/4 coverage=allocated-sample`。失敗行：`FUXI RAMTEST: FAIL pass=…`、`no pages above old 5GiB aperture`。
- **主機測試**：`ksrc\tools\test-fuxi-ramtest.py`。
- **驗證紀錄**：第八趟 `native-hw000ram9g-pattern-boot-1`（12:21:48–12:28:58）：128 MiB、8192 頁全在高位址 `0xa1f0bc000..0xa27104000`，4/4 通過（`boot.log` 第 2849–2858 行）。之後 512 MiB：32768 頁 `0xa1b21c000..0xa3b690000`，4/4 通過。
- **參考來源**：無。
- **結論／未完成**：只是配置樣本，不能當全 9 GiB 完整性或長時間壓力驗收。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段。

### K-024 多段 RAM admission、bank shadow 與記憶體盤點
- **日期**：2026-11-16 14:09（51e7ca9）、15:24（a948742）、16:17（27bb0cf）；16:05 Android 擷取
- **狀態**：準備（主機模型與資料，核心未用）
- **開關**：無
- **問題／現象**：想超過 9 GiB 要把 Android 保留區之間的零碎區段也交給 XNU，必須先知道哪些區段真的空著、誰擁有。
- **根因**：DT 的 reserved-memory 只列靜態保留；動態配置（`size` 請求）與 live owner 不在 DT 裡。
- **做法**：
  - `ksrc\tools\fuxi-ram-inventory.py`：從 DT 列出候選區段；`fuxi-ram-admission.py`：依規則決定可交給 XNU 的區段。
  - `ksrc\xnu\fuxi-ram-prep\fuxi_ram_bank.c`：bank shadow admission 的純 C 模型（`test_fuxi_ram_bank.c`）。
  - `work\statusbar-fix\inspect-android-memory.py`：Android 下唯讀擷取 `/proc/iomem`、`/proc/meminfo` 等，存 `work\adsp-battery\android-memory-20261116-1606\memory.json`（參數 `--output <資料夾>`）。
- **復現**：`python -X utf8 work\statusbar-fix\inspect-android-memory.py --output work\adsp-battery\android-memory-<日期>`（Android、USB）；WSL `python3 tools/fuxi-ram-inventory.py <dtb>`、`tools/fuxi-ram-admission.py`。
- **主機測試**：`test-fuxi-ram-inventory.py`（20/20）、`test-fuxi-ram-admission.py`、`test-fuxi-ram-bank.py`。
- **驗證紀錄**：inventory：已知排除以外 15 段共 2228.56 MiB 候選，另有 772.00 MiB 動態 size 請求及未知 placement／live owner，不能直接當可用量。Android 擷取（16:05:37）：14 段 System RAM union 11491.55 MiB、MemTotal 11190.55 MiB，都大於目前 XNU 窗口；兩個 memblock 介面不存在，不能解讀為零保留。
- **參考來源**：Linux `mm/memblock.c`、`/proc/iomem` 格式。
- **結論／未完成**：真正的 XNU 多段 admission 未做。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段；ksrc `docs-lanes\ram-multirange-preparation.md`、`ram-handoff-owner-contract.md`、`ram-android-owner-20261116.md`、`ram-admission-checkpoint.md`。

## PMIC：手電筒與震動

### K-025 PMIC 唯讀盤點（flash／haptics）
- **日期**：2026-11-16 10:49（286ddc5）
- **狀態**：採用（診斷）
- **開關**：`fuxipmic=1` 或 ADT `fuxi,pmic=1`；loader `prepare-ram9g-loader.py --pmic-survey`。值大於 3 時拒絕並記 `unsupported mode`。
- **問題／現象**：手電筒（flash LED，SID 1）和震動（HAP525，SID 7）都在 SPMI 上的 PMIC，先要知道 Android 留下的暫存器狀態和 SPMI 通道擁有權。
- **根因**：（盤點）
- **做法**：`xnu\fuxi-adsp\fuxi_pmic.c`：映射 SPMI PMIC arbiter（core `0x0c400000`、config `0x0c42c000`、observer `0x0c440000`），讀 arbiter 版本與 APID 數，盤點 flash（SID 1 `0xee00`）、haptic config／pattern／boost（SID 7 `0xf000`／`0xf100`／`0xf200`）的暫存器與 APID owner；只讀。
- **復現**：`--pmic-survey`，上機 `-Seconds 120`。預期 console：`FUXI PMIC: arbiter=0x7… APIDs=… mode=1 haptic=0`、`FUXI PMIC: flash sid=1 base=0xee00 APID=… owner=… survey-only`、各 `+xx=yy rc=0` 行。
- **主機測試**：`ksrc\tools\test-fuxi-haptic-survey.py`（同時涵蓋 init 分派）。
- **驗證紀錄**：11-16 盤點趟完成；之後 K-026～K-033 都建立在這份資料上。
- **參考來源**：Linux `drivers/spmi/spmi-pmic-arb.c`、`drivers/leds/flash/leds-qcom-flash.c`、`drivers/input/misc/qcom-hv-haptics.c`（downstream）。
- **結論／未完成**：完成。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段；ksrc `docs-lanes\pmic-torch.md`、`pmic-haptics.md`。

### K-026 手電筒有界脈衝診斷（mode 2）
- **日期**：2026-11-16 11:43（816ab9e）
- **狀態**：實驗（保留作診斷）
- **開關**：`fuxi,pmic=2`；loader `--pmic-torch-pulse`。
- **問題／現象**：要先確認 AP 能安全地點亮 flash LED：電流、硬體計時器、關閉都要可控。
- **根因**：（診斷）
- **做法**：`fuxi_torch_pulse.h`：通道 0、40 mA、80 ms 的單次脈衝，依賴 PMIC 硬體計時器自動截止；寫前檢查 APID owner，寫後讀回。
- **復現**：`--pmic-torch-pulse`，上機 `-Seconds 120`。預期 console：`FUXI PMIC: flash pulse begin channel=0 current=40mA duration=80ms hardware-timer=…` → `FUXI PMIC: flash pulse result=0`；被拒時 `flash pulse refused APID=… owner=…`。
- **主機測試**：`ksrc\tools\test-fuxi-torch-pulse.py`。
- **驗證紀錄**：Torch 5g／9g CI `43799939050`／`43799939063` 成功（9g 40 項 manifest 全過）；第六趟 `flash pulse result=0 registers restored`，ADSP RPMh 啟動與降票同時完成。只證明 40 mA／80 ms 的暫存器序列與還原成功，未確認可見亮光。
- **參考來源**：Linux `leds-qcom-flash.c`。
- **結論／未完成**：mode 2 保留有限脈衝，作為硬體檢查。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段。

### K-027 手電筒租約控制（mode 3）與 SpringBoard 放行
- **日期**：2026-11-16 12:30（e390fe4）、12:38（be26a95）；13:19、13:47 上機
- **狀態**：採用（日常 ADT `fuxi,pmic=3`，chain-v7 起）
- **開關**：`fuxi,pmic=3`；loader `--pmic-torch-runtime`。
- **問題／現象**：控制中心的手電筒按鈕要能開關、調亮度，需要 iOS 可呼叫的介面。
- **根因**：iOS 的手電筒走相機驅動堆疊，fuxi 沒有相機驅動；需要另開一個由 SpringBoard dylib 呼叫的核心入口（dylib 見 U 系列）。
- **做法**：`fuxi_torch_runtime.h`：sysctl `kern.fuxitorch`（0..4；0＝關，1..4＝20／40／60／80 mA），每次寫入給 2 秒租約，逾時自動關；失敗後鎖存（failed latch），讀回 EIO。be26a95：呼叫者為 root，或 platform binary 且行程名是 SpringBoard 才可寫（`fuxi_torch_caller_allowed`）。同提交擴充 haptics 盤點。
- **復現**：`--pmic-torch-runtime`，搭配 U 系列的手電筒 dylib；上機 `-Seconds 240`。預期 console：`torch steady runtime ready`（K-030 之後的字樣）；在控制中心開手電筒後 `sysctl kern.fuxitorch` 讀回 1..4。
- **主機測試**：`ksrc\tools\test-fuxi-torch-runtime.py`。
- **驗證紀錄**：第 10 趟（13:19）控制中心沒有手電筒按鈕；第 11 趟（13:47）按鈕出現，ADT tap 後援指令生效（`using ADT command (22 bytes)`）。之後持續亮光的失敗見 K-028。
- **參考來源**：Linux `leds-qcom-flash.c` 的 torch 模式。
- **結論／未完成**：介面可用；持續亮光直到 K-029／K-030 才解決。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段；ksrc `docs-lanes\pmic-torch.md`。

### K-028 手電筒失敗追查（關閉穩定、計時器、audit、原始拒絕）
- **日期**：2026-11-16 13:53～19:02（b6ce046、5b0f00e、b274554、a066a05、272620c）
- **狀態**：已結案（根因見 K-029）
- **開關**：ADT `fuxi,torchaudit=1`（只在 `fuxi,pmic=3` 時有效）；loader `--torch-audit`。
- **問題／現象**：mode 3 下持續請求 80 mA，脈衝跑一陣就鎖停，每趟停的位置和錯誤碼都不同：第 12 趟 64 次後 `rc=-2`；第 13 趟 12 次後 `rc=-6`；第 14 趟 9 次後 `rc=-6`；第 16 趟 8 次＋restore `+0x42 rc=-1`；第 18 趟第一次就 `rc=-5`（post-disable `+0x09=0x10`）；第 24 趟計時器 `0x89` 下 21 次後 observer read 回 `status=0x9`（DONE＋DROPPED，SID1 `0xee46`、APID 591、owner 0）。
- **根因**：最後確定是 SPMI 交易被同時存取的其他 PMIC 使用者打斷（DROPPED），見 K-029。過程中排除了熱保護、計時器值、關閉順序。
- **做法**：
  - b6ce046：有界記錄 torch 失敗。
  - `fuxi_torch_audit.h`：失敗脈衝最多 64 筆 I/O（R/W、sleep 前後、耗時），控制序列與保護不變。
  - 5b0f00e：關閉後的穩定等待有上限，計時器保留。
  - b274554：回報 PMIC 原始交易拒絕的狀態。
  - a066a05：計時器改用較保守的解碼值；272620c：記錄計時器讀回驗證與鎖存的 SPMI dropped read。
  - 計時器值爭議：Linux v6.12 `leds-qcom-flash.c:set_flash_timeout()` 是 `timeout_ms / 10` 加 bit 7（100 ms→`0x8a`）；比對到的 OEM 來源是 `timeout/10-1`（→`0x89`）。目前核心 `fuxi_torch_pulse.h` 用 `0x89`（保守，OEM 解讀 100 ms、mainline 解讀 90 ms），仍保留 80 ms 等待、限流、2 秒租約與失敗鎖存。實際硬體時間未用儀器量。
- **復現**：`--pmic-torch-runtime --torch-audit`；在控制中心開手電筒 120 秒。失敗時 console：`FUXI PMIC: flash write rejected +xx APID=… status=… failure=…`、`flash write timeout`，以及最多 64 行 audit。
- **主機測試**：`test-fuxi-torch-audit.py`、`test-fuxi-torch-runtime.py`。
- **驗證紀錄**：第 12–24 趟如上（各趟紀錄在 `work\Codex-Xiaomi13-GPU-20261109\native-hw000torch*`）；最高溫 48.5°C 上下，不是熱保護。
- **參考來源**：Linux v6.12 `leds-qcom-flash.c`；OEM kernel 對應檔。
- **結論／未完成**：移交 K-029。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段（第 12–24 趟）；ksrc `docs-lanes\torch-timer-source-checkpoint.md`、`torch-timeout-status-research.md`。

### K-029 PMIC SPMI 交易共用仲裁鎖
- **日期**：2026-11-16 19:37（b48ec0f）；20:00、20:21 上機
- **狀態**：採用
- **開關**：無（PMIC 任一模式）
- **問題／現象**：K-028 的隨機鎖停。
- **根因**：手電筒、震動和核心其他 SPMI 使用者（RTC、按鍵等，`sweet_spmi` 匯流排）各自操作 PMIC arbiter，沒有共用鎖；交易互相插隊時 observer 回 DROPPED。
- **做法**：`fuxi_pmic.c` 的 flash／haptic SPMI 交易改用共用的 `sweet_spmi_bus_lock`（`sweet_spmi_bus.h`）。
- **復現**：`--pmic-torch-runtime --torch-audit`，控制中心請求 80 mA 120 秒。預期：脈衝持續到結束，0 次失敗。
- **主機測試**：`test-fuxi-torch-runtime.py`。
- **驗證紀錄**：第 28 趟 `native-hw000torchlock-120s-boot-1`（20:00:41–20:07:32，最高 52.8°C）：脈衝到第 768 次以上、0 失敗；第 30 趟 `native-hw000torchlock-120s-boot-2`（20:21:22–20:28:11，最高 50.9°C）結果相同。
- **參考來源**：Linux `spmi-pmic-arb.c` 的 `pmic_arb->lock`。
- **結論／未完成**：完成；脈衝式在使用者眼中仍會閃，改成常亮見 K-030。
- **出處**：journal「Claude 接續（19:10 起）」段。

### K-030 手電筒常亮
- **日期**：2026-11-16 22:14（3d41b16）；22:00、22:58 上機
- **狀態**：採用
- **開關**：無（`fuxi,pmic=3` 的行為）
- **問題／現象**：22:00 手動測試（`native-ram9g-torchmanual-sb127-user-loader`，無 tour／tap）使用者看到換檔時閃。
- **根因**：mode 3 原本用一連串有硬體計時器的脈衝模擬常亮，脈衝之間有空檔。
- **做法**：`fuxi_torch_steady.h`：輸出持續保持，直到停止請求或 2 秒租約到期（由 dylib 續約）。
- **復現**：loader `native-ram9g-torchsteady-sb127-user-loader` 的作法：`prepare-ram9g-loader.py … --pmic-torch-runtime --rtc-calibration <json> --rtc-adt`，不帶 tour；上機 540 秒、Reset 10 分鐘，使用者親手開關。
- **主機測試**：`ksrc\tools\test-fuxi-torch-steady.py`。
- **驗證紀錄**：22:58:06 `native-hw000torchsteady-user-boot-1`（CI 9g Intel `43886498954`，核心 SHA256 `0513709d…`，boot SHA256 `a141afa5…`）：常亮 OK，但調亮度時閃。
- **參考來源**：Linux `leds-qcom-flash.c` torch 模式（非 flash 模式）。
- **結論／未完成**：調光閃爍由 K-031 修。
- **出處**：journal「Codex 再接續（11-16 21:31 起）」段。

### K-031 手電筒調光不重開輸出與五檔
- **日期**：2026-11-16 23:13（e9a1f57）；23:44 上機；11-17 00:03:58 五檔驗收
- **狀態**：採用（日常 chain-v7 起）
- **開關**：無
- **問題／現象**：K-030 常亮後調整亮度會閃一下；另外 iOS 的 3、4 檔沒有差別。
- **根因**：調光時先關輸出再以新電流打開。iOS 16 對手電筒送的強度值是 0.85／1.0，dylib 舊算法 `ceil(value*4)` 把兩者都算成第 4 檔。
- **做法**：e9a1f57 在輸出開著時直接更新電流暫存器，不切換輸出。檔位對應由 harness `7034f05`（dylib，U 系列）改為 0／0.25／0.5／0.85／1.0 與核心 0–4 雙向對應（20／40／60／80 mA 不變）。
- **復現**：loader `native-ram9g-torchdim-sb127-user-loader`（581 bytes 命令列，手動）。五檔：本機 9g 核心＋`7034f05` dylib，上機時在控制中心逐檔切換。
- **主機測試**：`test-fuxi-torch-steady.py`；harness `tools\test-flashlight-levels.c`（ASan／UBSan）。
- **驗證紀錄**：23:44 `native-ram9g-torchdim-sb127-user-loader`（CI `43896202141`，核心 `adb03512…`，boot `e570b49c…`）調光不閃。11-17 00:03:58–00:08:50 `native-hw000local-torchlevels-user-boot-1`（本機 9g 核心，第一次上機的本機核心；dylib CI `43902171532`）：113 次切換涵蓋五檔，使用者回報「手電筒可以了 沒問題」。
- **參考來源**：iOS 16 AVFlashlight 強度值（反組譯觀察）。
- **結論／未完成**：完成。mode 3 不宣稱在核心或 SPMI 失效時有硬體自主截止。
- **出處**：journal「歷史驗收摘要」段（L79）。

### K-032 HAP525 震動盤點與有界脈衝
- **日期**：2026-11-16 14:09（51e7ca9）、16:36（acb3fcd）；第 13、20 趟上機
- **狀態**：實驗（只讀；已被 K-033 取代為實際震動）
- **開關**：`fuxihaptic=1` 或 ADT `fuxi,haptic=1`；loader `prepare-ram9g-loader.py --haptic-probe`。
- **問題／現象**：要讓 iOS 震動，先確認 PM8550B HAP525 的狀態、共振週期與能否自主停止。
- **根因**：（盤點）
- **做法**：`fuxi_haptic_pulse.h`：檢查 HAP525 identity／owner／fault／idle／boost follow；PATTERN1 自主停止未驗證前不寫（writes=0）。
- **復現**：`--haptic-probe`，上機 `-Seconds 120`。預期 console：`FUXI PMIC: haptic result=… probed=1 TLRA=5710us start-attempted=0 …`。
- **主機測試**：`test-fuxi-haptic-pulse.py`、`test-fuxi-haptic-survey.py`。
- **驗證紀錄**：第 13 趟 `result=-11 probed=1 TLRA=5710us start-attempted=0 writes=0`；第 20 趟兩輪唯讀 identity／selector／TLRA 有效（5710 µs），FIFO 狀態不可用、cutoff 未驗。研究確認 CFG `0x4a` bit 2 為 FIFO hold（當時 `0x84` 已開）。
- **參考來源**：downstream `qcom-hv-haptics.c`。
- **結論／未完成**：由 K-033 的 DIRECT_PLAY 取代。
- **出處**：journal「Codex 接續（11-16 10:04 起）」段；ksrc `docs-lanes\pmic-haptics.md`、`haptic-finite-research.md`。

### K-033 HAP525 DIRECT_PLAY 震動執行期
- **日期**：2026-11-17 13:00（48a46c0）、13:01（6206698）、22:17（05ed0fa 強度）
- **狀態**：採用（日常 ADT `fuxi,haptic=2`）
- **開關**：ADT `fuxi,haptic=2`（3＝另加開機自測三下）；`fuxi,haptic-amp=<0..255>`（dylib 讀，見 U 系列）；ADT `fuxi,inject` bit 2 讓 mediaserverd 載入 dylib。loader：`prepare-wlan-w18-loader.py --haptic 2 --inject-media [--haptic-amp 128]`。
- **問題／現象**：iOS 的觸覺回饋、來電與充電震動都沒有。
- **根因**：iOS 的震動走 mediaserverd 的 haptic server 與 AppleHapticsSupport 驅動，fuxi 沒有；需要核心介面加 dylib 橋接。
- **做法**：
  - `fuxi_haptic_runtime.h`：映射 haptic CFG／PTN 通道，檢查 Android 留下的狀態（module 開、SPMI_PLAY `0x01` direct play、振幅與 VMAX ≤ 1400 mV、自動共振開、idle、boost 跟隨硬體）；sysctl `kern.fuxivibrate`（0..2000 ms；root 或 platform 的 SpringBoard／mediaserverd 可寫）。播放寫 `0x81`，停止寫 `0x01` 並輪詢 HPWR_INTF 等關閉（照 Linux 先切一次 module 再鎖存關閉）；播放中每 5 ms 檢查 fault。
  - 05ed0fa：sysctl 值的 bits 16..23 帶 HAP525 DIRECT_PLAY 振幅暫存器（`0xf126`）的值；0 表示不改暫存器，舊呼叫者行為不變。開始前與播放中寫入並讀回；VMAX 永不改動；ready 時記錄 Android 留下的振幅與 VMAX。
  - iOS 端（mediaserverd／SpringBoard 的 dylib）把震動模式轉成 sysctl 呼叫，見 U 系列。
- **復現**：`prepare-wlan-w18-loader.py build --like <已驗> --artifact <核心> --name <新> --haptic 3 --inject-media`；上機 `-Seconds 240`。預期 console：開機自測 3 次 `fault=0 stop-rc=0`；觸發震動時 `kern.fuxivibrate` 寫入紀錄。
- **主機測試**：`test-fuxi-haptic-runtime.py`（含 haptic=4 拒絕）；harness `tools\test-vibe-pattern.c`、`test-vibe-worker.py`。
- **驗證紀錄**：vibe6 14:06:34–14:14:15（`native-vibe5-ram9g-sb127-loader`／`kernel-local-vibrate-9g-artifact`）：核心三次脈衝 fault=0／stop-rc=0，iOS 直接震動入口回 `!itl`、無 AVHapticServer 播放，最高 74.6°C。vibe7 14:31:19–14:38:00（dylib `c4dbd88`，CI `44031165852`）：MediaExperience bridge 安裝，一般震動與自訂節奏到核心，9 次播放停止成功，`!itl` 改回 0。vibe8 14:51:38–14:55:26（dylib `101e39d`，CI `44033584532`）：Atoms Minitap 15 ms 實測 15.530 ms，2000 ms 請求提前取消實測 120.850 ms，10 次播放 fault=0。使用者確認充電震動有感。
- **參考來源**：downstream `qcom-hv-haptics.c`；Linux `drivers/input/misc/` HAP 驅動。
- **結論／未完成**：CoreHaptics `-4810` 仍未解（U 系列）。
- **出處**：journal 11-17 段（L93–L95）。

### K-034 震動 FIFO 準備（主機模型）
- **日期**：2026-11-16 15:24（a948742）
- **狀態**：準備（未接上核心）
- **開關**：無
- **問題／現象**：複雜震動波形需要 HAP525 的 FIFO 模式；先在主機上建模。
- **根因**：（準備）
- **做法**：`ksrc\xnu\fuxi-haptic-prep\fuxi_haptic_fifo.c`／`.h` 與 `test_fifo.c`：FIFO 填充、水位、停止條件的純 C 模型。
- **復現**：WSL `python3 tools/test-fuxi-haptic-fifo.py`。
- **主機測試**：`test-fuxi-haptic-fifo.py`。
- **驗證紀錄**：主機測試通過。
- **參考來源**：downstream `qcom-hv-haptics.c` FIFO 路徑。
- **結論／未完成**：DIRECT_PLAY（K-033）已滿足目前需求，FIFO 未接。
- **出處**：ksrc `docs-lanes\haptic-fifo-preparation.md`。

## 測試自動化、RTC、藍牙

### K-035 裝置端 UI 測試指令（taps、tour、tapcmd）
- **日期**：2026-11-14 21:29（6fc377f）、11-16 03:02（7928af8）、13:14（aab893e）
- **狀態**：採用（測試工具）
- **開關**：`fuxitaps=<延遲秒>`、`fuxitour=<…>`（`fuxitoura`、`fuxitourg`、`fuxitourhold`）、`fuxitapcmd=<指令>` 或 ADT `fuxi,tapcmd`（字串）；loader `--tap-script <指令> [--tap-script-adt]`、`--tap-delay`。
- **問題／現象**：上機驗證要在 iOS 裡點開設定、拖滑桿、截圖，但沒有 USB 輸入通道。
- **根因**：（測試工具）
- **做法**：`xnu\fuxi-h1\fuxi_keys.c`（補丁 0103）：開機後依預設腳本或指令字串，透過觸控／HID 注入點擊、拖曳、按鍵與截圖標記。6fc377f：預設 @3 從主畫面第一頁開設定；7928af8：tour 拖控制中心亮度滑桿上下各一次（`brightness-low`／`brightness-high`）；aab893e：命令列滿了改從 ADT `fuxi,tapcmd` 讀有界指令。
- **復現**：`prepare-wlan-w18-loader.py … --tap-script "<指令>" --tap-delay 85`；預期 console：`using ADT command (<n> bytes)`、`FUXI KEYS: inject …`。
- **主機測試**：`ksrc\tools\test-fuxi-tap-command.py`；截圖流程 `work\statusbar-fix\test-launcher-framebuffer.ps1`。
- **驗證紀錄**：第 11 趟（13:47）ADT 後援指令生效（22 bytes）；各 tour 截圖趟。
- **參考來源**：無。
- **結論／未完成**：全高 framebuffer 截圖期間 USB 可能短斷（AGENTS §8）。
- **出處**：ksrc `docs-lanes\tap-command.md`。

### K-036 RTC 校時（ADT fuxi,rtc-offset）
- **日期**：2026-11-16 17:58（cac5f98）、18:39（1836f06）；11-17 02:09（406f096）；02:42 隨 chain-v7 進日常
- **狀態**：採用（日常）
- **開關**：`fuxirtcoffset=<秒>`（優先）或 ADT `/chosen fuxi,rtc-offset`（4 bytes LE）；`fuxirtc` 控制 RTC 讀取。loader：`--rtc-calibration <json> [--rtc-adt]`。
- **問題／現象**：iOS 開機時間不對（PMIC RTC 計數器從某個基準起算，不是 Unix 時間），每次開機都要網路校時，且沒網路時時間錯誤。
- **根因**：PM8550 RTC 只是計數器，Android 把 offset 存在使用者空間；iOS 側沒有。
- **做法**：
  - RTC 讀取本身在 `fuxi_keys.c`（補丁 0103）。cac5f98：rollover 驗證的最後一次 LSB 讀取失敗時拒絕這筆樣本（原本仍回成功）；1836f06 同步到 H1 overlay。
  - 406f096：命令列沒有 `fuxirtcoffset` 時改讀 ADT（日常命令列 607 bytes 已滿）。
  - `work\adsp-battery\rtc-calibration.py capture`：Android 下讀 RTC 計數器與系統時間算 offset，輸出 json（一小時內有效）。
- **復現**：Android 開機後 `python -X utf8 work\adsp-battery\rtc-calibration.py capture <json>`（`verify <json>` 檢查是否仍有效）；也可用 `launch-loader-check.ps1 -CalibrateRtc -Out <名>`；`prepare-ram9g-loader.py … --rtc-calibration <json> --rtc-adt`。預期 console：`counter=<n> offset=<秒> (adt) epoch=<秒>`、`clock set`。
- **主機測試**：`work\adsp-battery\test-rtc-calibration.py`；`ksrc\tools\test-fuxi-rtc-read.py`（production extraction 16 cases／364 assertions）。
- **驗證紀錄**：chain-v7 暫時開機實記 `counter=71238 offset=1794782948 (adt) epoch=1794854186`、`clock set`，與台北時間吻合；日常 payload 帶 `1794782948`（`work\adsp-battery\rtc-calibration-daily-v7-20261117.json`）。iOS 時區另改 Asia/Taipei（U 系列）。
- **參考來源**：Linux `drivers/rtc/rtc-pm8xxx.c`（rollover 讀法）。
- **結論／未完成**：offset 依賴 RTC 計數器不歸零；完全斷電或 RTC 被重設後要重跑 capture 並重包部署。長時間走時未確認。
- **出處**：journal「歷史驗收摘要」段（L87）；ksrc `docs-lanes\rtc-time-handoff.md`。

### K-037 藍牙 GENI FIFO 與 iOS 16 藍牙 ABI 準備
- **日期**：2026-11-16 14:09（51e7ca9）、15:24（a948742）
- **狀態**：準備（唯讀盤點已上機）
- **開關**：`fuxibt=1` 或 ADT `fuxi,bt=1`（唯讀盤點）；loader `prepare-ram9g-loader.py --bluetooth-survey` 或 `prepare-wlan-w18-loader.py --bt 1`。
- **問題／現象**：WCN7850 藍牙走 QUP2 SE6 UART（HCI H4），iOS 端則要 `bluetoothd` 看得懂的傳輸；兩端都還沒有。
- **根因**：（準備）
- **做法**：`xnu\fuxi-bluetooth\fuxi_bt.c`／`fuxi_bt_xnu.c`：唯讀快照 SE6 的 GPIO 76–83、clock branch、engine 狀態；GENI FIFO 的純 C 模型；`ksrc\tools\inspect-fuxi-bluetooth-abi.py` 分析 iOS 16 藍牙驅動的 ABI。
- **復現**：`--bluetooth-survey`；預期 console：`FUXI BT: probe status=ok …`、`FUXI BT: gpio<n> ctl=… io=…`、`FUXI BT: branches core=… se6=…`。
- **主機測試**：`test-fuxi-bluetooth.py`、`test-fuxi-bluetooth-xnu.py`、`test-fuxi-bt-geni-fifo.py`。
- **驗證紀錄**：首趟唯讀 `survey status=ok`，GPIO 76–83 八筆完整、無 read fault；`off_mask=0x12 engine_read=0`（正確拒讀冷時鐘的 SE6；s_ahb 與 SE6 branch CLK_OFF 仍設定）。
- **參考來源**：Linux `drivers/tty/serial/qcom_geni_serial.c`、`drivers/bluetooth/hci_qca.c`。
- **結論／未完成**：板級上電見 K-039。
- **出處**：ksrc `docs-lanes\bluetooth-ios16-abi.md`、`bluetooth-fifo-preparation.md`、`bluetooth-checkpoint-01.md`。

### K-038 藍牙五條時脈租約準備
- **日期**：2026-11-16 16:09（b6be873）
- **狀態**：準備（延後）
- **開關**：無
- **問題／現象**：藍牙用的五條共用投票時脈還有其他使用者，要有引用計數才能安全開關。
- **根因**：XNU 這邊沒有涵蓋這五條時脈的 native clock owner。
- **做法**：`ksrc\xnu\fuxi-bt-clock-prep\fuxi_bt_clock_ledger.c`：純值 C 租約帳本與主機測試，不產生 MMIO callback。
- **復現**：WSL `python3 tools/test-fuxi-bt-clock.py`。
- **主機測試**：`test-fuxi-bt-clock.py`。
- **驗證紀錄**：主機測試通過。
- **參考來源**：Linux common clock framework 的 prepare／enable refcount。
- **結論／未完成**：明確延後；K-039 改用「暫時開、結束全部還原」的作法。
- **出處**：`ksrc\xnu\fuxi-bt-clock-prep\README.md`。

### K-039 藍牙板級上電與 QCA 版本查詢（fuxi,bt=3）
- **日期**：2026-11-17 17:20（141bb99）、17:38（7dfdd70）、17:41（161994f）
- **狀態**：實驗（已通；韌體下載未做）
- **開關**：ADT `fuxi,bt=3`（或 `fuxibt=3`）；loader `prepare-wlan-w18-loader.py --bt 3`（會檢查核心含 `board WLAN_EN steady after` 字串、命令列沒有 `fuxibt=`）。
- **問題／現象**：要讓藍牙晶片回應，得先把 SE6 時脈、腳位、BT_EN 拉起來。
- **根因**：開機階段沒有替 iOS 準備藍牙。第一版（bt1）把回覆的 `event[8]=0x0c` 誤判成 Command Disallowed，其實那是 12 bytes 的長度欄位。
- **做法**：`xnu\fuxi-bluetooth\fuxi_bt_board.c`：SE6 RCG 用 GPLL0_OUT_EVEN 設 7.3728 MHz；gpio76–79 切到 qup2_se6；先等 WLAN_EN 穩定為高 15 秒（上限 300 秒，不穩就不碰 BT_EN）；BT_EN 低 50 ms、拉高等 100 ms；送 QCA 版本查詢（vendor `0xfc00`）；結束後全部還原。7dfdd70 依 Linux btqca 跳過回覆多出的一個 byte，並記錄原始回覆；161994f 同步進 0117。
- **復現**：`prepare-wlan-w18-loader.py build --like <已驗> --artifact <核心> --name <新> --bt 3`，上機 `-Seconds 240`。預期 console：`FUXI BT: board WLAN_EN steady after <ms> ms` → `FUXI BT: QCA version product=0x19 soc=0x40170200 rom=0x200 patch=0x43fb` → `FUXI BT: board restore status=ok`。
- **主機測試**：`ksrc\tools\test-fuxi-bt-board.py`。
- **驗證紀錄**：bt1 `native-hw000bt1-boot-1`（17:25–17:32，141bb99）回應正確但誤判；bt2apps `native-hw000bt2apps-boot-1`（17:44，loader `native-bt2apps-ram9g-sb127-loader`，本機核心 `kernel-local-bt2-9g-artifact`＝ksrc `7dfdd70`＋`161994f`、ath12k `b2876c6`）：原始回覆 `040e120100fc00190c19000000fb43000200021740`，`probe status=ok … valid=1`，fifo 錯誤 0。
- **參考來源**：Linux `drivers/bluetooth/btqca.c`、`hci_qca.c`；UniXNU-sheng 藍牙（記憶 `xiaomi13-hardware-reference-projects`）。
- **結論／未完成**：下一步是下載韌體（依 product／soc 應為 `hmtbtfw20.tlv`／`hmtnv20.bin`）與 iOS 端 HCI 傳輸。
- **出處**：journal「歷史驗收摘要」段（L83）；記憶 `xiaomi13-bluetooth`。

### K-040 WLAN HTC 協定準備（主機模型）
- **日期**：2026-11-16 16:17（27bb0cf）
- **狀態**：準備（未接上核心）
- **開關**：無（`FUXI_HTC_DEFAULT_ACTIVE` 恆為 0）
- **問題／現象**：ath12k 韌體與主機之間的 HTC 封包（READY、CONNECT_RESPONSE、credit trailer）要先能正確解析。
- **根因**：（準備）
- **做法**：`ksrc\xnu\fuxi-htc-prep\fuxi_htc_prep.c`：獨立的 C11 解析器與診斷觀察器，不連進 WLAN、核心、CE、WMI 或 loader；不加開機參數、MMIO、DMA。
- **復現**：WSL `python3 tools/test-fuxi-htc-prep.py`。
- **主機測試**：`test-fuxi-htc-prep.py`。
- **驗證紀錄**：主機測試通過。
- **參考來源**：Linux v6.12 `drivers/net/wireless/ath/ath12k/htc.h`（標頭 8 bytes、READY 8／12 bytes、trailer 記錄）。
- **結論／未完成**：native ath12k（K-049 起）直接用 Linux 模組，這份模型保留作對照。
- **出處**：`ksrc\xnu\fuxi-htc-prep\README.md`。


## WLAN：原廠韌體路線（W18／P17，已擱置）

共同前提：

- 驅動在 `ksrc\xnu\fuxi-wlan\fuxi_wlan.c`，以補丁 `0099-fuxi-wlan.patch` 進核心。改原始碼後在 WSL 跑 `tools/sync-fuxi-wlan.py` 重產補丁。
- loader 產生器 `work\adsp-battery\prepare-wlan-w18-loader.py build`。基本命令列是 `WLAN_ARGS`：`fuxiadsp=0 fuxiwlan=1 fuxiwlanclk=1 fuxiwlanprobe=civac fuxiwlanseq=cycle,parf,dbi,eq,hostirq,msi,por,prefix fuxiwlanqrtr=5 fuxiwlanw18=1`。各實驗開關再附加上去，命令列上限 607 bytes。
- 這一段每趟都是暫時開機，沒改日常 boot_b。收尾都完成 bus master off、PERST、MSI／SMMU undo、buffer 釋放。
- 2026-11-14 以前的 WLAN 階段（M5、M6～M6o、W10～W17、try12～try16）在基底 75148d2 之前，屬 harness 歷史，見 S 系列 `0099`／`0104` 與 E 系列。

### K-041 W18 追蹤與原廠韌體 FW_READY 停損
- **日期**：2026-11-16 14:09（51e7ca9）；上機 15:32（第15趟）、16:24（第19趟）
- **狀態**：結論（原廠韌體路線擱置）
- **開關**：`fuxiwlanw18=1`（W18 有界追蹤）；`fuxiwlanmlo=<值>`（P17 選擇器，見 K-044）。loader 產生器 `--mlo`。
- **問題／現象**：用 Android 原廠 WLAN 韌體（amss20、bd_m3、REGDB、M3）啟動 WCN7850。QMI 前段全部成功，但韌體不送 FW_READY（QMI 0x38）。
- **根因**：未解。第32趟（K-047）證明同一套主機流程換上游韌體就能到 WLAN_MODE，所以差在原廠韌體自己要的額外步驟（QDSS 設定、cnss 專屬能力等）。
- **做法**：
  - 51e7ca9 加 W18 有界追蹤（`docs-lanes\wlan-w18.md`、`wlan-w18-profile.md`）。
  - 原廠資產從 Android 唯讀取出（`work\adsp-battery\android-wlan-assets-20261116-1450`），寫進手機 iOS root。寫入收據 `statusbar-fix\run-wlan-oem-assets-crlf-20261116`。
  - 依 TCSR major2 選 amss20。
- **復現**：
  1. 照「寫入手機分區」規則把原廠 WLAN 資產寫進 root：寫前比對、寫後讀回，保留還原清單。
  2. `prepare-wlan-w18-loader.py build --like <已驗 W18 loader> --artifact <含 W18 的核心> --name <新名>`。
  3. `launch-loader-check.ps1 -Seconds 300`。
  4. 預期 console：REGDB、BDF 15 段、M3_INFO 的 QMI result／error 都是 0，之後 `FW_READY 0x38` 等 10000 ms 逾時，停在 step 28（code `0x1c01`）。
- **主機測試**：`ksrc\tools\test-fuxi-wlan-w18.py`、`test-fuxi-wlan-m6.py`。
- **驗證紀錄**：
  - 第15趟 `native-hw000w18-oem-assets-boot-1`，15:32:22–15:38:12：結果如上，主機最高 61.9°C。mtd 存 `adsp-battery\fuxilog\20261116-153920`（boot#17，307228 bytes）。
  - 第19趟 `native-hw000w18-oem-nomlo-boot-1`（loader `native-wlan-w18-oem-nomlo-ram9g-loader`），16:24:13–16:31:04：關掉 MLO 後結果相同，所以 no-MLO 不是解法。最高 51.7°C。
  - 對照 Android 開機紀錄 `work\adsp-battery\android-wlan-init-20261116-1823`：Android 的 M3（`phy_ucode20.elf`，299660 bytes，和 fuxi 的 m3.bin 同大小）送出後 2 ms 下載 `qdss_trace_config_v2.cfg`（4911 bytes），再 11 ms 就收到 FW init done。
  - 288cd1a（18:25）把這份 Android 證據寫進 `docs-lanes\wlan-hostcap-secondary-checkpoint.md`，用來框定下一批假設（K-042～K-046）。
- **參考來源**：Android cnss2 開機紀錄；Linux ath12k `qmi.c`；UniXNU-sheng（同 WCN7850，已通）。
- **結論／未完成**：K-042～K-046 依序排除了五個假設。K-047 換上游韌體才到 MODE，原廠路線擱置。
- **出處**：journal 2026-11-16 第15、19趟；`ksrc\docs-lanes\wlan-w18.md`。

### K-042 SECONDARY HOST_CAP
- **日期**：2026-11-16 17:04（a066a05）、17:19（06c7b64）、17:41（3115b92）；上機 18:04（第22趟）
- **狀態**：結論（排除）
- **開關**：`fuxiwlancap=1`；loader 產生器 `--host-cap-secondary`。
- **問題／現象**：Android 的 HOST_CAP 帶 SECONDARY 能力，fuxi 沒帶。懷疑韌體因此不送 FW_READY。
- **根因**：不是這個。
- **做法**：
  - a066a05 加有界的 HOST_CAP TLV `0x20 SECONDARY=2`，只在 `fuxiwlancap=1` 時送。
  - 06c7b64 讓 M6i 主機模型、3115b92 讓 Rails 主機抽取，都跟正式的 admission guard 對齊。
  - 同一個 commit 也把手電筒的 deadline 降低（K-028）。
- **復現**：在 K-041 的 loader 上加 `--host-cap-secondary`，其他不變。
- **主機測試**：`test-fuxi-wlan-w18.py`、`test-fuxi-wlan-m6i.py`、`test-fuxi-wlan-rails.py`。產生器 self-test 會核對 `fuxiwlancap=1` 只出現一次，而且是唯一差異。
- **驗證紀錄**：第22趟 `native-hw000w18-oem-secondary-boot-1`（loader `native-wlan-w18-oem-secondary-ram9g-sb127-loader`），18:04:50–18:09:41。
  - TLV 確實送出，回覆 `msg0x34 result0/error0`。
  - REGDB、BDF、M3_INFO 都成功，但仍等 FW_READY 10000 ms 後停在 step 28。主機最高 50.5°C。
  - USB log SHA-256 `72c168f66ce8f43da9656c6b9f1b2a6a6416d0f84569885bc96b9b9a4eb8d4fb`。
- **參考來源**：Android cnss2 HOST_CAP 內容；Linux ath12k `qmi.c` 的 host_cap。
- **結論／未完成**：單一 TLV 變更不是解法。
- **出處**：journal 第22趟；`ksrc\docs-lanes\wlan-hostcap-secondary-checkpoint.md`。

### K-043 省略 nm_modem 能力
- **日期**：2026-11-16 18:37（723e740）、19:02（4efd714 紀錄）；上機 18:55（第25趟）
- **狀態**：結論（排除）
- **開關**：`fuxiwlancap=2`；loader 產生器 `--omit-nm-modem`。payload 和 `fuxiwlancap=1` 只差一個字元。
- **問題／現象**：接 K-042，比對 Android 的能力宣告，試試不宣告 nm_modem。
- **根因**：不是這個。
- **做法**：723e740 加一個隔離的「省略 SECONDARY host 能力」選項，用來對照 firmware-ready。
- **復現**：在 K-041 的 loader 上加 `--omit-nm-modem`。核心用 9g CI `43850892720`（kernel SHA-256 `1311058383a2680914b77292e4d7883e72de8bdea5ceda6e16c893c592191da3`）；同批 5g CI 是 `43850892769`。
- **主機測試**：`test-fuxi-wlan-m6i.py`、`test-fuxi-wlan-rails.py`、`test-fuxi-wlan-w18.py`。
- **驗證紀錄**：第25趟 `native-hw000w18-oem-no-nm-modem-boot-1`，18:55:06–18:59:58。
  - 省略標記和 SECONDARY 都出現，回覆 result0。
  - 仍是 step 28 FW_READY 逾時，code `0x1c01`。
  - SMMU CB6 的 FSR `0x400`、FAR、FSYNR、SID `0x139f` 從 step 20 到 step 28 都一樣，所以不算新增 fault，也不改 stream mapping。
  - USB `boot.log` 4114 行，SHA-256 `beb4fb316b641167a6ace5ca5d1eabdb313c880d9d3e22cb465e5c3cfb8e528c`。
  - 持久紀錄 `adsp-battery\fuxilog\20261116-190038\console.txt`（boot#27）。
- **參考來源**：同 K-042。
- **結論／未完成**：排除。
- **出處**：journal「18:54–19:01：第25趟」。

### K-044 PMK8550 睡眠時脈與大塊記憶體（P17）
- **日期**：2026-11-16 19:37（e82f103）；上機 19:20（第26趟，用既有開關）、19:53（第27趟）
- **狀態**：結論（睡眠時脈是必要條件，見 K-047；大塊記憶體排除）
- **開關**：
  - `fuxiwlanmlo` 位元：`0x40` 讀睡眠時脈；`0x80` 開睡眠時脈；`0x200` BIGMEM；`0x100` ERRDEC（K-045）。
  - loader 產生器 `--sleep-clock check|on` 會產生 `fuxiwlanmlo=64` 或 `192`；`--big-mem` 產生 `704`。
- **問題／現象**：
  - 對照 UniXNU-sheng（同晶片、已通）後發現 fuxi 從沒開過 PMK8550 gpio3 的 32 kHz 睡眠時脈。
  - 另外，W13 起 fuxi 一律回零段記憶體，逼韌體改要 31 塊不超過 512 KiB 的小塊。Android cnss2 和 mainline ath12k 都直接給兩大塊（7077888＋8454144 bytes）。
- **根因**：
  - 睡眠時脈：實證 XNU 下是關的。
  - 大塊：try12 時期給過大塊，但 IOVA 只對齊 16 KiB；W13 把「切小塊」和「二的次方對齊」一起改掉，所以「大塊＋正確對齊」從沒測過。
- **做法**：
  - 睡眠時脈的 P17 開關早已存在，只是沒上機過。
  - e82f103 新增 `0x200` BIGMEM：直接給兩大塊，IOVA 對齊，不做零段協商。
  - 為了湊 607 bytes 命令列，拿掉重複的 `fuxiadsp=0`；ADT `fuxi,adsp=0` 仍然關著 ADSP。
- **復現**：
  - 第26趟：`--sleep-clock on`。預期 console 先印 `mode 0 func 0 en 0x80 state 0`（原本關），開啟後讀回 `mode 0x1 func 0x2 en 0x80 state 0xff`。
  - 第27趟：`--big-mem`。預期 `P17 bigmem grants n=2 total=15532032 without zero-segment negotiation; aligned IOVAs`。
- **主機測試**：`test-fuxi-wlan-w13.py`（加 trial 14）、`test-fuxi-wlan-w17.py`（選擇器範圍）。
- **驗證紀錄**：
  - 第26趟 `native-hw000w18-oem-slpclk-boot-1`（loader `native-wlan-w18-oem-slpclk-ram9g-sb127-loader`，boot SHA-256 `04b7f151bd1bb9b8a394a7f65dc54f3bf561b2c394de60efe807ecd3ab835b90`），19:20:14–19:25:02。時脈確實開了，但原廠韌體仍停在 step 28。EE 是 AMSS，ERRCODE／ERRDBG 全是 `0xcafecace`：韌體沒當掉，只是沒往下走。USB SHA-256 `222d0de1ae1477b701971938f82459b667383d172de5166cd74dc36072108241`。
  - 第27趟 `native-hw000w18-oem-bigmem-boot-1`，19:53，`fuxiwlanmlo=704`：走了新路徑，FW_READY 仍逾時，所以小塊協商不是卡點。
  - 核心 `kernel-adsp-bigmem-ram9g-artifact`（kernel SHA-256 `cb527adf…f0d5`，含手電筒共用鎖 b48ec0f）；harness `4c6cc13`；CI `43859436119`／`43859436103`／`43859436037`。
- **參考來源**：UniXNU-sheng 的 WCN7850 開機流程；Android cnss2、Linux ath12k 的 `qmi.c` 記憶體請求處理。
- **結論／未完成**：睡眠時脈對原廠韌體不夠，但對上游韌體是關鍵（K-047）。大塊記憶體排除。
- **出處**：journal「19:10–19:25：第26趟」「19:53–20:16」；`ksrc\docs-lanes\wlan-p17.md`。

### K-045 ERRDEC：WLFW 逾時後統計韌體寫過的主機記憶體
- **日期**：2026-11-16 20:27（86cfb9d）；上機 20:42（第31趟）
- **狀態**：結論（診斷）
- **開關**：`fuxiwlanmlo` 位元 `0x100`；loader 產生器 `--errdec` 產生 `fuxiwlanmlo=960`（相對第27趟只多診斷輸出）。
- **問題／現象**：需要分辨兩種情況：韌體根本沒碰主機記憶體，還是跑了一段才停。
- **根因**：（診斷項）
- **做法**：
  - 分配時清零。
  - WLFW 逾時後逐段統計：非零位元組數和頁數、開頭幾個字、最多 12 段可讀文字。
  - 唯讀，不改流程。
- **復現**：`--errdec`。核心 `kernel-adsp-errdec-ram9g-artifact`：harness `fb74d96`，CI `43866828542`／`43866828266`／`43866828527`。
- **主機測試**：無專用測試，跟著 0099 編譯。
- **驗證紀錄**：第31趟 `native-hw000w18-oem-errdec-boot-1`（loader boot SHA-256 `21ff3a9e…c7fb`），20:42:59–20:50:11，最高 50.1°C。
  - type 1（7077888 bytes）只有開頭 493 個非零位元組（+0～+0x317，一頁），開頭是 `0159aec0 0000012c 00100505 01278c08`，沒有可讀文字。
  - type 4（校正用，8454144 bytes）完全沒被碰過。
  - USB SHA-256 `f82cede2…7371`。
- **參考來源**：無。
- **結論／未完成**：韌體對主機記憶體的 DMA 是通的，SMMU 對應沒問題。它只寫了一小段表頭就停。Android 在同一步，M3 之後 13 ms 就 init done。
- **出處**：journal 第31趟；`docs-lanes\wlan-p17.md`。

### K-046 AOP PDC 設定
- **日期**：2026-11-16 20:10（第29趟）
- **狀態**：結論（排除）
- **開關**：`fuxiwlancnss=pdc`（M6n 階段已有，預設關）；loader 產生器 `--cnss-pdc`。
- **問題／現象**：Android cnss2 在 WLAN 供電前會送 13 筆 `wlan_pdc` 設定給 AOP，fuxi 預設不送。
- **根因**：不是這個。
- **做法**：開既有開關。為了湊 607 bytes 命令列，拿掉 `fuxiperfidle=1000`。
- **復現**：在 K-044 第27趟的 loader 上加 `--cnss-pdc`，即 `fuxiwlanmlo=704 fuxiwlancnss=pdc`。預期 console `M6n PDC consumed 13/13 before WLAN rails`。
- **主機測試**：`test-fuxi-wlan-m6n.py`。
- **驗證紀錄**：
  - 第29趟 `native-hw000w18-oem-pdc-boot-1`，20:10:48 開機：13 筆全部送出，FW_READY 仍逾時。USB SHA-256 `41ae905f…b0d8`；持久紀錄 `fuxilog\20261116-201600`（boot#31）。
  - 這趟啟動器在 20:13 中途結束（主機程序消失）。手機靠核心的 6 分鐘倒數自己回 Android；20:16 確認回程後才移除留下的鎖檔。
- **參考來源**：Android cnss2 開機紀錄。
- **結論／未完成**：
  - 預設表第 11 筆 `bb s2g.v dwnval` 是 800，Android 實際是 512，來源未查。
  - Android 在 CAP 回覆後還依 `ol_cpr_cfg` 再送 7 筆 AOP 電壓（s4e 914、s5g 946/414、s2g 966/790、s4g 1314、s6g 1866），fuxi 只印不送。
  - 兩者都未再追（原廠路線擱置）。
- **出處**：journal「19:53–20:16」。

### K-047 上游韌體＋睡眠時脈：WLAN_MODE 通過
- **日期**：2026-11-16 21:02（第32趟）
- **狀態**：已驗證（QMI 啟動流程全部完成；資料通路改走 K-049 起的 native ath12k）
- **開關**：`fuxiwlanbdf=bd_up.elf fuxiwlanmlo=192`（不開 SECONDARY、大塊、PDC）；loader 產生器 `--bdf bd_up.elf --sleep-clock on`。
- **問題／現象**：11-14 的 try15／16 用上游韌體已到 FW_READY／INI／CFG，只卡 WLAN_MODE 10 秒。
- **根因**：缺 PMK8550 gpio3 的 32 kHz 睡眠時脈（K-044 實證 XNU 下原本是關的）。
- **做法**：
  1. 從 linux-firmware `ath12k/WCN7850/hw2.0` 下載 `amss.bin`／`m3.bin`／`board-2.bin`。SHA-256 依序 `43aadfd3…`／`0e72f44d…`／`6a98237c…`，三個都和 sheng 清單相同。版本 `WLAN.HMT.1.1.c7-00108…UPSTREAM-3`。存 `work\adsp-battery\upstream-wlan-fw-20261116`。
  2. 從 board-2.bin 取 `…subsystem-vendor=17cb,subsystem-device=1107,qmi-chip-id=2,qmi-board-id=255` 項（88760 bytes，`d4f92e9f…`）存成 `bd_up.elf`；regdb 取同檔的 `bus=pci` 項（24310 bytes）。
  3. 清單 `wlan-stage-input-upstream-20261116-2110.json`。20:58–21:02 寫進手機 root：改 8 個 4 MiB 區塊，三次 fsck OK。還原清單與原區塊在 `statusbar-fix\run-wlan-upstream-20261116`。
- **復現**：照上面三步準備、寫入韌體後，`prepare-wlan-w18-loader.py build --like native-wlan-w18-oem-slpclk-ram9g-sb127-loader --bdf bd_up.elf --sleep-clock on --name <新名>`。預期 console：
  - M3_INFO 回覆時收到 FW_READY（0x38）。
  - INI 約 11 ms、CFG 約 35 ms，`W15 wlan mode normal ok; stop before CE/HTC`（約 89 ms，result 0／error 0）。
  - 再觀察 2 秒 ERRCODE 不變，`step 28 ok code 0x101c`，28 steps done。
- **主機測試**：`test-fuxi-wlan-w15.py`、`test-fuxi-wlan-w18.py`。
- **驗證紀錄**：第32趟 `native-hw000w18-up-slpclk-boot-1`（loader `native-wlan-w18-up-slpclk-ram9g-sb127-loader`，boot SHA-256 `8a32fedb…9940`，核心同第31趟），21:02:23–21:09:33，最高 60.7°C。
  - 結果如上預期。
  - USB SHA-256 `f30b9ff1…624a`；持久紀錄 `fuxilog\20261116-210953`。
- **參考來源**：linux-firmware ath12k WCN7850 hw2.0；UniXNU-sheng 韌體清單；Linux ath12k `qmi.c`。
- **結論／未完成**：
  - 當時驅動到 MODE 就主動停機，沒有 CE／HTC／WMI。
  - 原廠韌體（c2-00058.3）停在 M3 之後，擱置不追。
  - 下一段資料通路改用 Linux ath12k 模組（K-049）。
- **出處**：journal「第32趟」。

### K-048 WLAN BDF 來源盤點
- **日期**：2026-11-16 16:17（27bb0cf）
- **狀態**：準備（工具）
- **開關**：無
- **問題／現象**：BDF（board data）有好幾個來源：Android vendor、board-2.bin、sheng 清單。要能核對哪個檔對應哪組 chip／board id。
- **根因**：（準備）
- **做法**：`ksrc\tools\fuxi-wlan-bdf-inventory.py` 解析 board-2.bin／ELF BDF 並列出項目和雜湊。同一個 commit 也加了 RAM bank shadow admission 檢查（K-024）。
- **復現**：WSL `python3 tools/fuxi-wlan-bdf-inventory.py <board-2.bin 或 BDF>`（參數見檔頭 argparse）。
- **主機測試**：`test-fuxi-wlan-bdf-inventory.py`。
- **驗證紀錄**：主機測試通過；K-047 的 `bd_up.elf` 就是依這套規則取出的。
- **參考來源**：Linux ath12k `core.c` 的 board-2.bin 解析（BDF 名稱字串格式）。
- **結論／未完成**：無。
- **出處**：`ksrc\docs-lanes\wlan-bdf-provenance.md`。

## WLAN：native ath12k 與 iOS 介面

共同前提：

- 直接連結 pinned 的 Linux ath12k 模組物件，模組在 macOS CI 編：harness workflow `fuxi-ath12k-objects`。來源鎖是 ath12k `5f7f5a8`、UniXNU-sheng `6880068`、UniXNU `4a654d1`。
- 核心這邊：
  - `xnu\fuxi-wlan\fuxi_wlan_ath12k.{h,inc}`、`fuxi_wlan_arena.h`、`fuxi_wlan_control.h`、`fuxi_wlan_ios.inc`，在補丁 0099。
  - `xnu\fuxi-wifi-ios\`（apple80211、station、net），在補丁 0104。
- 本機建置：`build-kernel.ps1 -Ram 9g -Ath12k <已下載的 fuxi-ath12k-objects 資料夾> -Name <名>`。
- loader：`prepare-wlan-w18-loader.py build --like <已驗 native loader> --artifact <核心> --name <新> --native-ath12k --wifi-ios …`。產生器會檢查核心裡有沒有對應的字串標記，沒有就拒絕。
- 每個 loader 資料夾都有產生器寫的 profile：native 是 `wlan-ath12k-profile.json`，W18 是 `wlan-w18-profile.json`。裡面記錄當次選項（quiet_boot、haptic_amp、wifi_rssi_bounds、inject…）和完整命令列，`--like <loader 名>` 就是讀 native 的這份當範本。要重現某趟，先看這個檔。
- 命令列固定帶 `fuxiwlan=1 fuxiwlanath=1 fuxiwlanmlo=192`，`--wifi-ios` 再加 `fuxiwifiios=2`。11-18 起，可用 `--wifi-args-adt` 把驅動啟動後才讀的開關移到 ADT `fuxi,args`（K-067）。

### K-049 ath12k 板級轉接層
- **日期**：2026-11-16 22:37（42df429）
- **狀態**：已驗證（K-052 起實機掃描）
- **開關**：`fuxiwlanath=1`（預設關）
- **問題／現象**：K-047 之後要 CE／HTC／WMI／掃描。自己移植 ath12k 是大工程，改成直接連 Linux 模組，fuxi 只提供板級介面。
- **根因**：（新功能）
- **做法**：
  - PBL 階段只有單一 MHI owner。
  - 對應完整 2 MiB BAR。
  - 128 MiB Normal-NC 自有 DMA arena（`fuxi_wlan_arena.h`）。
  - 窄範圍的 PCI config W1C 保護。
  - 韌體讀取走白名單。
- **復現**：只做主機驗證；上機見 K-052。
- **主機測試**：`test-fuxi-wlan-ath12k.py`、`test-fuxi-wlan-m6.py`／`m6i`／`m6o`。
  - MSVC ASan 跑 236471 項檢查、30000 次 allocator transition，含 containment 之後 metadata／韌體的釋放。
  - 和 pinned `nw_abi.h` 比對四個 struct 的大小、alignment、所有欄位 offset 和 callback 指派。
  - M6／M6i／M6o／Rails／W18 用 wasm32 ASan／UBSan 重跑。
- **驗證紀錄**：主機全過；當時 board-2.bin 尚未放進 root。
- **參考來源**：pinned 模組 ABI（`nw_abi.h`，在模組來源鎖內）；Linux ath12k `pci.c`／`mhi.c`。
- **結論／未完成**：接 K-050 連結。
- **出處**：journal「Fuxi板級介面新增…」；`ksrc\docs-lanes\wlan-ath12k.md`。

### K-050 ath12k 模組連結與 CI
- **日期**：2026-11-16 22:43（f6a7588）
- **狀態**：已驗證
- **開關**：只在要求時連結（核心 CI 的 opt-in 9g，或本機 `-Ath12k`）。
- **問題／現象**：模組物件在 macOS 上編，核心在 Linux／macOS 交叉編，連結前要先驗證物件。
- **根因**：首次模組 CI 失敗：pinned fetcher 把帶前置斜線的路徑直接交給 cone sparse-checkout。
- **做法**：
  - `ksrc\tools\ci\ath12k-link.py` 核對物件 manifest、imports、entries 後才連結。
  - `variants\ath12k-link.patch`；`tools\ci\build.sh`、`prepare-kernel.py` 接線。
  - harness `41a932d` 只做受控的字串轉換，改用既有去斜線的 `paths` 和 `--skip-checks`。
- **復現**：
  - 推 harness 觸發 `fuxi-ath12k-objects`。
  - 下載 artifact 後 `build-kernel.ps1 -Ram 9g -Ath12k <資料夾>`。腳本從模組 gate 讀 15.5 建置 target，用 Linux `llvm-nm` 檢查 Mach-O。
- **主機測試**：`test-fuxi-ath12k-link.py`（15e6d0a 加）。
- **驗證紀錄**：
  - 模組 CI `43879548709`（harness `41a932d`）成功：約 1.2 MiB，13 項 undefined import 全是 C 字串／記憶體／格式化函式。
  - harness `cb63de2` 重建，CI `43894744787`：125 objects，Mach-O 為 MACOS15.5，13 imports，9 entries。
  - opt-in 9g 核心 CI `43896202460`（harness `c0d0d2d`）：41 項 manifest 全過，kernel SHA-256 `3528e078d9c2c2770f638c361b49d54bf6f…`。
  - 11-17 本機建置通過 47 項 manifest。
- **參考來源**：UniXNU Ath12kWifi 建置方式。
- **結論／未完成**：無。
- **出處**：journal「ath12k objects 首次 CI…」「harness cb63de2…」「ath12k 9g CI…」。

### K-051 隔離 native imports 與控制通道
- **日期**：2026-11-16 23:25（15e6d0a）、2026-11-17 00:19（62dd9b0）
- **狀態**：已驗證
- **開關**：同 K-049
- **問題／現象**：
  - 第一趟 native 實機停在 `start -16`，BSS 0。
  - 第二趟到 AMSS／M0，但 DMA error 1、BSS 0。
- **根因**：
  - 第一趟：控制通道沒接上，start 回 -EBUSY。
  - 另外 imports 要和核心連結平台一致。
- **做法**：
  - 15e6d0a 隔離 native WLAN 的 imports，讓連結平台和核心一致。
  - 62dd9b0 接上 control transport（`fuxi_wlan_control.h`），掃描 peer 核對 session、generation 和 reply。
- **復現**：本機 9g 加 `-Ath12k`，loader 加 `--native-ath12k`。
- **主機測試**：`test-fuxi-wlan-control.c`（C、ASan）、`test-fuxi-wlan-ath12k.py`、`test-fuxi-ath12k-link.py`。
- **驗證紀錄**：
  - `native-hw000ath12k-scan-boot-1`，11-16 23:51:24–23:58:16：start -16，BSS 0，DMA error 0，faults 0。mtd `fuxilog\20261117-000135`。
  - `native-hw000ath12k-control-boot-1`（ksrc 62dd9b0），00:26:28–00:30:18：到 AMSS／M0，DMA error 1 後收尾，BSS 0，最高 49.3°C。mtd `fuxilog\20261117-003351`。
- **參考來源**：pinned 模組的 `nw_*` 控制介面。
- **結論／未完成**：DMA error 由 K-052 修。
- **出處**：journal 對應兩行。

### K-052 遵守模組 DMA kfree 擁有權
- **日期**：2026-11-17 00:31（d24fc49）
- **狀態**：已驗證（第一次掃到 BSS）
- **開關**：同 K-049
- **問題／現象**：K-051 第二趟 DMA error 1。
- **根因**：模組對 DMA buffer 的 kfree 擁有權契約沒照做：該由模組釋放的被 fuxi 處理，或反過來。
- **做法**：arena 依模組契約記錄擁有者，釋放走對應路徑（`fuxi_wlan_arena.h`、`fuxi_wlan_ath12k.inc`）。
- **復現**：loader `native-wlan-dma-ram9g-sb127-loader`，核心本機 9g（ksrc d24fc49）。
- **主機測試**：`test-fuxi-wlan-ath12k.py`。
- **驗證紀錄**：`native-hw000ath12k-dma-boot-1`，00:34:12–00:37:02。
  - 掃到 34 個 BSS；start error 0、DMA error 0、faults 0；最高 61.1°C。
  - 收尾 bus master off、PERST asserted；MHI reset 未確認。
- **參考來源**：pinned ath12k 模組的 DMA API 契約。
- **結論／未完成**：MHI reset 的收尾未確認。
- **出處**：journal `native-hw000ath12k-dma-boot-1`。

### K-053 iOS station 後端（電源與掃描）
- **日期**：2026-11-17 00:56（e575a32）
- **狀態**：已驗證
- **開關**：`fuxiwifiios=2`；loader 產生器 `--wifi-ios`。
- **問題／現象**：要讓 iOS 的 wifid 看到網路介面，能開關電源和掃描。
- **根因**：（新功能）
- **做法**：
  - `fuxi-wifi-ios\`：`fuxi_wifi_apple80211.c` 回答 Apple80211 ioctl；`fuxi_wifi_sta.c` 是 station 狀態；`fuxi_wifi_ios.c` 接 IOKit。
  - `fuxi_wlan_ios.inc` 把 native WCN7850 的電源和掃描接到 station 後端。
  - 啟動時自測兩輪 power off／on 和掃描。
- **復現**：loader `native-wlan-ios-ram9g-sb127-loader`，本機 9g（ksrc 4b52021、harness 1d53fc3）。
- **主機測試**：`test-fuxi-wifi-ios.py`、`test-fuxi-wlan-ios.py`；`ksrc\tools\check-fuxi-wifi-ios.py`。
- **驗證紀錄**：
  - `native-hw000wlan-ios-boot-1`，01:03:11：兩輪 power off／on result 0，station 掃描 BSS 30。
  - `native-hw000wlan-ios-ui-boot-1`（同核心、帶設定頁巡覽）：wifid 取 POWER 有回應。RSSI_BOUNDS、INT_MIT、POWERSAVE 和 ioctl 383 被拒，畫面顯示「association unavailable」，無法加入。
- **參考來源**：`fuxi-wifi-ios` 移植自 HackiOS kernel checkout `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`（APSL-2.0）：`redwood_net.c`→`fuxi_wifi_net.c`、`redwood_sta.c`→`fuxi_wifi_sta.c`、`redwood_apple80211.c`→`fuxi_wifi_apple80211.c`、`RedwoodWLAN.cpp`→`FuxiWLAN.cpp`、`MiniIONetworkStack.cpp`→`FuxiNetworkStack.cpp`、`wifi/lx/src/lx_wpa.c`→`fuxi_wifi_wpa.c`；授權 `LICENSE.HackiOS` 隨 0104 附上。HackiOS userland `906425b7…`（MIT）只讀過 wifid 筆記和 `net_test.m`，沒有複製。沒有用到 UniXNU 程式碼。
- **結論／未完成**：加入流程見 K-055。
- **出處**：journal 兩行；`ksrc\docs-lanes\wifi-ios.md`。

### K-054 native WLAN 身分對齊 iOS 裝置樹
- **日期**：2026-11-17 01:00（4b52021）
- **狀態**：已驗證（併入 K-053 那趟）
- **開關**：同 K-053
- **問題／現象**：wifid 依裝置樹 wlan 節點找介面，native 驅動的身分要和它一致。
- **根因**：native 驅動沒對應 iOS DT 的 wlan 節點。
- **做法**：`fuxi_wlan_ath12k.h`／`.inc` 加身分欄位，讓它與 iOS 裝置樹的 wlan 節點一致。
- **復現**：同 K-053。
- **主機測試**：`test-fuxi-wlan-ios.py`。
- **驗證紀錄**：K-053 那趟 wifid 有找到介面並送 ioctl。
- **參考來源**：iOS 16 原廠 DT 的 wlan 節點。
- **結論／未完成**：無。
- **出處**：ksrc 4b52021；`docs-lanes\wlan-ath12k.md`。

### K-055 加入開放與 WPA2-PSK 網路
- **日期**：2026-11-17 02:00（d020ece）
- **狀態**：已驗證（11-17 使用者手動加入 WPA2 成功、DHCP 成功）
- **開關**：加入流程本身沒有開關（跟著 `fuxiwifiios=2`）。自測用 `fuxiwifitest=2 fuxiwifitestssid=<SSID>`（loader 產生器 `--wifi-join-test <SSID>`）。
- **問題／現象**：wifid 從來沒有匹配到 WPA2 網路。
- **根因**：GET_BSS 只回 384 bytes 的元素，把 RSN 截掉了，wifid 以為網路沒加密。
- **做法**：
  - GET_BSS 回完整元素。
  - worker 透過模組的 rx event 和 `nw_wifi_tx` 跑四向握手。
  - WPA3／SAE 和必要 MFP 的網路回 EOPNOTSUPP（不支援）。
  - `fuxiwifitest=2` 用假密碼試加入一次。
- **復現**：loader `native-wlan-join-ram9g-sb127-loader`（`--like` 產生，`--wifi-join-test <SSID>`），本機 `kernel-local-wifijoin-9g-artifact`。預期 console：associated → step5 handshake error 80（AP 拒絕金鑰＝流程正確）。
- **主機測試**：`test-fuxi-wlan-ios.py`（大幅擴充）、`test-fuxi-wlan-ath12k.py`。當時 33 項 workflow 主機命令通過。
- **驗證紀錄**：`native-hw000wlan-join-boot-1`，02:02:52–02:05:22，最高約 42°C。
  - 掃描 BSS 36；家用網路 2.4 GHz −37 dBm、5.2 GHz −55 dBm。
  - 假密碼結果如預期。
  - mtd `fuxilog\20261117-020754`。
- **參考來源**：四向握手的 WPA 邏輯是 `fuxi_wifi_wpa.c`（移植自 HackiOS `lx_wpa.c`，見 K-053）；Linux mac80211 加入流程。
- **結論／未完成**：
  - 真密碼加入在 K-056（06:50）手動驗過。
  - 純 SAE 和必要 MFP 仍不支援。
- **出處**：journal `native-hw000wlan-join-boot-1`。

### K-056 UI 測試只列指定網路（fuxiwifitest=3）
- **日期**：2026-11-17 02:56（70470b9）
- **狀態**：已驗證（開關生效；腳本點擊仍不可靠）
- **開關**：`fuxiwifitest=3 fuxiwifitestssid=<SSID>`；loader 產生器 `--wifi-ui-only <SSID>`。只用在測試 loader，日常不帶。
- **問題／現象**：點擊腳本要在「其他網路」或清單裡點到目標網路，但清單順序不固定。
- **根因**：（測試輔助）
- **做法**：開關打開時，wifid 只看得到指定名稱的網路，清單第一列就是它。密碼仍由畫面輸入。
- **復現**：`--wifi-ui-only <SSID> --tap-script <腳本>`。
- **主機測試**：`test-fuxi-wlan-ios.py`。
- **驗證紀錄**：
  - `native-hw000wlan-uijoin-boot-1`（02:45，本機 `kernel-local-wifirtc-9g-artifact`，這個開關之前）：設定 App 停在「一般」頁，點擊全部落空。21 個標記只存到 2 張圖（讀取時 USB 斷 16 次）。
    - 同趟確認狀態列 2:45 是台北時間（K-036）。
    - 同趟發現 coreduetd 不停呼叫 AKS sel 17（kAKSGetDeviceState），約 57% CPU（U 系列）。
  - `native-hw000wlan-uijoin2-boot-1`（06:50，本機 `kernel-local-wifiui-9g-artifact`＋`fuxiwifitest=3`）：腳本仍落空，還誤改了「收到新留言」提示聲。
    - 使用者手動加入 `<SSID>` 成功：WPA2-PSK、2412 MHz、−47 dBm，DHCP 拿到 `<區網IP>`。
    - 但狀態列 Wi-Fi 格是空的、Safari 黑屏，點網路後輸入密碼前卡幾秒。
- **參考來源**：無。
- **結論／未完成**：訊號格空白見 K-057。
- **出處**：journal 兩行。

### K-057 定期送 RSSI_CHANGED（狀態列訊號格）
- **日期**：2026-11-17 07:18（54beb9b）
- **狀態**：已驗證（wifid 的 RSSI／NOISE 查詢有回答）
- **開關**：無（跟著 `fuxiwifiios=2`）
- **問題／現象**：連上之後狀態列 Wi-Fi 格是空的。
- **根因**：驅動從不送 RSSI_CHANGED（事件 39），wifid 算不出 ScaledRSSI。
- **做法**：已連線時每 5 秒送一次 RSSI_CHANGED；噪聲底回 −95 dBm（`fuxi_wifi_apple80211.c`／`.h`）。
- **復現**：本機 `kernel-local-wifirssi-9g-artifact`；同趟狀態欄設定 300103（U 系列狀態欄項）。
- **主機測試**：`test-fuxi-wifi-ios.py`。
- **驗證紀錄**：`native-hw000wlan-rssi-sb103-boot-1`，07:20。
  - 使用者再加入 `<SSID>` 成功（2412 MHz），wifid 的 RSSI／NOISE 查詢有回答。
  - 訊號格要等使用者確認：tap `p` 不發 monitor 認得的標記，沒有截圖。
  - 同趟 Safari 開 apple.com：backboardd 的 Metal 後端拒收 WebKit 的 `b3a8`（3001×1500，HostMemory 不支援）和 `w30r`（OutOfMemory(Device)）。gate runtime-failure，20 秒後 backboardd 以 CPU 重生。這個問題交給 K-070／G 系列。
- **參考來源**：iOS 16 wifid 對 RSSI 事件的處理（本機反組譯）。
- **結論／未完成**：自動加入仍不行，根因在 K-064。
- **出處**：journal `native-hw000wlan-rssi-sb103-boot-1`。

### K-058 舊掃描結果加入前只重掃上次頻道
- **日期**：2026-11-17 07:27（d3f7631）
- **狀態**：已合入（沒有單獨上機）
- **開關**：無
- **問題／現象**：wifid 用較舊的掃描結果要求加入時，BSS 可能已不在 mac80211 的快取裡，需要重掃；全頻重掃很慢。
- **根因**：（效能）
- **做法**：先只重掃這個網路上次所在的頻道；不在那裡才全頻掃。
- **復現**：包含在 K-059 之後的所有 Wi-Fi 核心。
- **主機測試**：`test-fuxi-wlan-ios.py`。
- **驗證紀錄**：沒有單獨一趟；之後各趟加入都有經過。
- **參考來源**：Linux mac80211 加入前 probe 的行為。
- **結論／未完成**：無。
- **出處**：ksrc d3f7631。

### K-059 AKS 金鑰 wrap／unwrap（鑰匙圈可存 Wi-Fi 密碼）
- **日期**：2026-11-17 07:56（31241b2）、07:58（7294068）
- **狀態**：已驗證
- **開關**：無（AKS 替身固定提供）
- **問題／現象**：
  - 11-17 07:38 的 ADSP＋WLAN 聯合那趟（K-012）：使用者手動加入成功，但連上的那一刻 securityd 包裝金鑰（AKS sel 10）被拒 `0xe00002c7`。
  - 之後 wifid 不再發任何 apple80211 查詢，訊號格空白，密碼也沒存進鑰匙圈。
  - 原生日誌（15:22 的 `native-hw000wlan-log-boot-1`）也顯示，修正之前一般和 NonSyncable 的密碼查詢各 22 次 `-25300`。
- **根因**：AKS 替身（補丁 0038 `sweet-applekeystore`）沒實作 sel 10（wrap）和 sel 11（unwrap）。
- **做法**：
  - 在 0038 加 wrap／unwrap。用固定種子的 HMAC-SHA256 產生 pad 和 tag，blob 格式是 `tag(8) ∥ key ⊕ pad(32)`。
  - 鑰匙圈因此沒有靜態保護（文件註明）。
  - 31241b2 同時加記錄：RSSI_CHANGED 事件有沒有到 wifid。
  - 7294068 把 wrap 定義移開 0043 依賴的 context。
- **復現**：本機 `kernel-local-akswrap-9g-artifact`；要取樣時加 `--sample Preferences,locationd,wifid`（boot arg `sweetsample=`）。
- **主機測試**：沒有單獨主機測試，以實機 unwrap 計數為準。
- **驗證紀錄**：
  - `native-hw000wlan-akswrap-dt-boot-1`，08:01：securityd 的 sel 10 和 sel 11 全部回 0x0（22 次 unwrap，0 次錯誤），鑰匙圈可寫。
  - 同趟電量計：remaining 4234–4248、full 4249 mAh，4.36–4.44 V，100% 是實值。
  - 同趟用 locationd 取樣找到「日期與時間」卡死的根因：fairplayd MIG，修法在 U／B 系列。
- **參考來源**：AppleKeyStore user client 的 selector 編號（依 securityd 實際呼叫觀察）；0038 原本的 AKS 替身。
- **結論／未完成**：鑰匙圈沒有靜態保護，這是已知取捨。
- **出處**：journal `native-hw000wlan-joint1-boot-1`、`native-hw000wlan-akswrap-dt-boot-1`；`work\localbuild\wifi-autojoin-credential-decision-20261117.zh-TW.md`。

### K-060 協商掃描停留時間與 FAST 掃描快取
- **日期**：2026-11-17 10:31（21e2a91）
- **狀態**：已驗證（110 ms 單頻道掃描成功；快取命中）
- **開關**：
  - `fuxiwlandwell=1`（loader 產生器 `--scan-dwell`）：需要和模組協商。
  - `fuxiwlancache=1`（`--scan-cache`）：只重用 5 秒內、成功完成、覆蓋請求範圍、非空的結果。
- **問題／現象**：wifid 帶非零停留時間的掃描被拒（EOPNOTSUPP 102）。
- **根因**：pinned 模組原本不接受指定 dwell。
- **做法**：
  - 和模組協商 dwell extension，模組端由 harness `9b5cfcd`／`4d87ed9` 修改。
  - 加 FAST 掃描快取。
- **復現**：
  - 模組 CI `44002779624`，正式核心 CI `44003964196`。
  - 本機 `kernel-local-scandwell-9g-artifact`：33 項 workflow 主機命令、81 項 manifest、1012 個 production dwell 案例。
  - loader `native-wlan-scandwell-ram9g-loader`（只開 dwell），以及 `native-wlan-scancache-ram9g-loader`（再開 cache）。
- **主機測試**：`test-fuxi-wlan-ios.py`、`test-fuxi-wlan-control.c`、`test-fuxi-ath12k-link.py`。
- **驗證紀錄**：
  - `native-hw000wlan-scandwell-boot-1`，10:34:45–10:39:35：110 ms 單頻道掃描完成（0），BSS 49，原本的 EOPNOTSUPP 102 消失。持久紀錄 `fuxilog\20261117-103948`（boot#58）。
  - `native-hw000wlan-scancache-boot-1`，10:40:10–10:44:59：FAST 命中一次。持久紀錄 `fuxilog\20261117-104546`（boot#59）。
  - 兩趟都還沒有自動加入，後段各有 4 次 scan EINVAL 22，由 K-062 處理。
  - 10:46 唯讀檢查 `statusbar-fix\inspect-wifi-after-scandwell-20261117-1046`：讀 20 個區塊，overlay 寫入 0。
- **參考來源**：Linux cfg80211 `cfg80211_scan_request` 的 `duration` 欄位。
- **結論／未完成**：無。
- **出處**：journal 兩行與「已修非零停留時間掃描遭拒」段。

### K-061 wifid 呼叫追蹤與被拒掃描參數
- **日期**：2026-11-17 10:56（8741795）
- **狀態**：已驗證（診斷）
- **開關**：`fuxiwifitrace=1`（loader 產生器 `--wifi-trace`）
- **問題／現象**：要知道 wifid 從哪裡呼叫 ioctl 383（掃描），以及哪些掃描參數被拒。
- **根因**：（診斷）
- **做法**：最多記兩次 wifid ioctl 383 的呼叫堆疊，並印出被拒掃描的參數。
- **復現**：loader `native-wlan-wifitrace-ram9g-loader`。
- **主機測試**：`test-fuxi-wifi-ios.py`。
- **驗證紀錄**：`native-hw000wlan-wifitrace-boot-1`，10:59:02–11:03:50：定位到 40 頻道、每頻道 110 ms 的預算被拒；FAST 命中一次；仍沒有加入。最高 66.7°C。呼叫點整理在 `work\localbuild\ioctl383-wifid-calls-20261117.json`。
- **參考來源**：本機同版 wifid 反組譯。
- **結論／未完成**：被拒原因交給 K-062。
- **出處**：journal `native-hw000wlan-wifitrace-boot-1`。

### K-062 dwell 掃描分批
- **日期**：2026-11-17 11:09（69ea46c）
- **狀態**：已驗證（模組 NULL 合約修正後）
- **開關**：`fuxiwlanbatch=1`（loader 產生器 `--scan-batch`）
- **問題／現象**：40 頻道×110 ms 超過模組和 bridge 的逾時預算。
- **根因**：
  - 預算問題。
  - 另外，首測在 pinned Linux 的 `rdev-ops.h:463` 被拒 EINVAL 22：被動掃描時 `n_ssids=0`，`ssids` 卻不是 NULL。
- **做法**：
  - 在現有逾時內把掃描分成 31＋9 兩批。
  - 模組端 harness `b2876c6` 修 NULL 合約，模組 CI `44010197996`。
- **復現**：loader `native-wlan-scanbatch-ram9g-loader`；核心要搭配 `44010197996` 之後的模組。
- **主機測試**：`test-fuxi-wlan-ios.py`。
- **驗證紀錄**：
  - `native-hw000wlan-scanbatch-boot-1`，11:13:29–11:18:18：模組修正前，第一段 31 頻道仍回 EINVAL 22，沒進第二段。
  - `native-hw000wlan-passivespf-boot-1`，11:35:14–11:40:05（本機核心 `6f28814`＋模組 `44010197996`）：31＋9 被動掃描多次成功，BSS 52–54；仍沒有加入。持久紀錄 `fuxilog\20261117-114041`（boot#62）。
- **參考來源**：Linux `net/wireless/rdev-ops.h`。
- **結論／未完成**：無。
- **出處**：journal 兩行。

### K-063 wifid 精確路徑注入
- **日期**：2026-11-17 19:23（3d8e39e）
- **狀態**：已驗證（診斷用）
- **開關**：fxinj bit 8（ADT `fuxi,inject` 的 8），只比對 wifid 的精確路徑。
- **問題／現象**：自動加入的決策在 wifid 內部，需要把診斷 dylib 注入 wifid。
- **根因**：（診斷）
- **做法**：0118 exec 注入加一個位元，只在 exec 路徑完全等於 wifid 時注入。
- **復現**：loader 產生器 `--wifi-audit`：要求 `--wifi-ios`、核心含 `wifid gets` 字串、命令列沒有 `fxinj=`，原 `fuxi,inject` 必須是 2 或 6，再 OR 上 8。診斷 dylib 見 U 系列。
- **主機測試**：`test-fuxi-exec-inject.py`。
- **驗證紀錄**：
  - `native-hw000wifi-filter-feedback-audit-boot-1`，19:28:53–19:34:43（本機 `kernel-local-wifiaudit-9g-artifact`）。
  - `native-hw000wifi-candidate-sound-audit-boot-1`，19:47:37–19:52:26。
  - `native-hw000wifi-decisions-corehaptics-boot-1`，20:06:13–20:11:02。
  - 三趟都成功注入並記到原生決策。
- **參考來源**：K-020 fxinj 0118。
- **結論／未完成**：決策結論見 K-064。
- **出處**：journal 三行與「Wi-Fi 已縮到最後的原生加入資格檢查」段。

### K-064 回答 RSSI_BOUNDS（自動加入修好）
- **日期**：2026-11-17 22:17（05ed0fa）
- **狀態**：已驗證（使用者確認「wifi 終於會自己連線了」）
- **開關**：ADT `fuxi,wifi-rssi=1`；loader 產生器 `--wifi-rssi-bounds`。
- **問題／現象**：
  - 已知網路通過 profile 匹配和排序，但 `__allowJoinCandidate:trigger:defer:error:` 一直回 allowed=0，NSError code=1。
  - 原生 NSError 擷取把原因縮到「Below minimum RSSI threshold」。
- **根因**：wifid 讀 RSSI_BOUNDS（Apple80211 get 106）被拒，拿不到門檻，就把每個候選判成太弱。
- **做法**：
  - `fuxi_wifi_apple80211.c`：開關打開時，get 106 回 version 1、上下限 −128／127、門檻 −128 dBm；關閉時照舊拒絕。
  - UniXNU zizhan 用同樣的值。
  - 同一個 commit 也加了 DIRECT_PLAY 振幅（K-033）和 quiet boot（K-065）。
- **復現**：loader `native-rssiamp-quiet-1117-2225-ram9g-srgb-loader`（`--wifi-rssi-bounds --quiet-boot --haptic-amp 128`），本機 `kernel-local-rssiamp-quiet-9g-artifact`，dylib `sb-local-hapticamp-sbwifi-artifact`。
- **主機測試**：`test-fuxi-wifi-ios.py`。
- **驗證紀錄**：
  - `native-hw000wifi-hapticfb-boot-1`，21:34：定位根因，仍沒有 join finished。console SHA-256 `df846f2f…c3`，mtd `fuxilog\20261117-212954`。
  - `native-hw000wifi-rssiamp-boot-1`，22:25：join finished 10 次、DHCP 5 次，使用者確認自動加入。console 27075 行，SHA-256 `3e5a033b09196d09140abd276b2675c84af60d7f2f7181b115cbb13cd0161249`，mtd `fuxilog\20261117-222609`。
- **參考來源**：UniXNU zizhan 的 RSSI_BOUNDS 回答；本機同版 CoreWiFi 反組譯。
- **結論／未完成**：使用者接著回報四個體驗問題，見 K-066。
- **出處**：journal「最新對齊（2026-11-17 23:30）」段。

### K-065 安靜開機（不畫 console 跑馬燈）
- **日期**：2026-11-17 22:17（05ed0fa，補丁 0119）
- **狀態**：已驗證
- **開關**：`sweetfb_noconsole=2`；loader 產生器 `--quiet-boot`。
- **問題／現象**：開機時螢幕會畫 XNU console 文字。
- **根因**：SweetFramebuffer 預設把 console 畫到螢幕上。
- **做法**：`fuxi-unixnu\SweetFramebuffer.cpp`（補丁 0106）加上 `0119-sweet-quiet-boot.patch`，值 2 時不畫 console 文字。USB console 和 mtdblk 紀錄照常。
- **復現**：`--quiet-boot`。
- **主機測試**：無專用測試。
- **驗證紀錄**：22:25 那趟（K-064）不再出現跑馬燈，USB console 照常完整。
- **參考來源**：0106 的 SweetFramebuffer（v7 以前用 `sweetfb_noconsole=1`）。
- **結論／未完成**：日常 chain-v8 已帶 `sweetfb_noconsole=2`（`work\dualboot\daily-merge-20261118\comparison.json`：v7 為 1、v8 為 2）。
- **出處**：journal 22:25 段。

### K-066 fuxi,wifi-ux：電源回報、依速率選 AP、同台不斷線（bit 0～2）
- **日期**：2026-11-17 23:16（aa89a3e）
- **狀態**：已驗證
- **開關**：ADT `fuxi,wifi-ux`（位元遮罩，預設 0）；loader 產生器 `--wifi-ux <值>`（會檢查核心有沒有 `FUXI WIFI IOS: ux options` 標記和各位元的字串）。
  - bit 0（1，`FUXI_WIFI_UX_POWER_ASKED`）：開關剛按下、電源還沒切完時，GET POWER 回報要求的狀態；關閉進行中拒絕掃描和加入。
  - bit 1（2，`PICK_RATE`）：wifid 沒指定 BSSID 時，照 wpa_supplicant 的比較法用估計速率選 AP。
  - bit 2（4，`KEEP_LINK`）：已連線時又要求加入同一台，就不先斷線。
- **問題／現象**：使用者回報四個問題：
  1. 關 Wi-Fi 時開關閃約 2 秒才關。
  2. 打開後掃描慢。
  3. 速率最多約 100 Mbps（另一支手機 300 Mbps）。
  4. 偶爾斷線又恢復。
- **根因**：
  - 關閉排隊或執行中時，GET POWER 仍回報「開」，開關就彈回去。
  - 選 AP 只比 RSSI，常選到 2.4 GHz。
  - wifid 對已連線的同一台再要求加入時，驅動先斷線再重連。
- **做法**：`fuxi_wifi_sta.c`／`.h`、`fuxi_wlan_ios.inc`、`fuxi_wifi_apple80211.c`；harness `0392fff`；產生器 `--wifi-ux`（主倉庫 `45b700d`）。
- **復現**：本機 `kernel-local-wifiux-9g-artifact`（38 項 PASS），loader `native-wifiux-1117-2320-ram9g-srgb-loader`（同 K-064 再加 `--wifi-ux 7`）。
- **主機測試**：`test-fuxi-wifi-ios.py`、`test-fuxi-wlan-ios.py`。
- **驗證紀錄**：`native-hw000wifi-wifiux-boot-1`，23:20–23:42:46（900 秒），console 36080 行，SHA-256 `2580304451062ab6d2305dd92ae7f3ea05a597d88c7ecddd0dbf114ee9e21652`，最高 75.7°C。
  - ux 0x7 生效：每次都選 5200 MHz（估計 648–720 Mbps），不選較強的 2.4 GHz。join finished 0 四次、16 一次。
  - 「轉圈」那次的成因：
    1. 掃描中切換開關，關閉要求被後到的開啟覆蓋，radio 從沒關過。
    2. iOS 端收到「開」仍清掉連線狀態，但 mac80211 還連著同一台。
    3. 再認證回 -EALREADY（狀態 2 → EBUSY），中止流程送 deauth，下一輪才連上。
  - 這個成因由 K-067 的 bit 4 修。
- **參考來源**：wpa_supplicant `wpa_scan_result_compar`（估計速率比較）。
- **結論／未完成**：使用者回報速率有升，但沒到 300 Mbps；重開後搜尋仍慢。
- **出處**：journal「最新對齊」段與 `native-hw000wifi-wifiux-boot-1`。

### K-067 國家碼、相同電源狀態不重做、計時、ADT fuxi,args（bit 3～4，補丁 0121）
- **日期**：2026-11-18 00:02（497a117）
- **狀態**：已驗證（日常 chain-v8 用 ux=31）
- **開關**：
  - `fuxi,wifi-ux` bit 3（8，`COUNTRY`）：SET 51 收下並記住國家碼。只記住，不改 Linux 法規域，也不發事件。
  - bit 4（16，`POWER_SAME`）：要求的電源狀態和現在一樣（例如關被開覆蓋）時，不呼叫底層、不清連線。
  - ADT `fuxi,args`（補丁 `0121-fuxi-adt-wifi-args.patch`）：驅動啟動後才讀的開關可以放這裡，不佔 607 bytes 命令列。loader 產生器 `--wifi-args-adt`。`fuxiwlan=1` 和測試用的 `fuxiwifitest*` 仍留在命令列。
- **問題／現象**：K-066 的轉圈；命令列已滿，放不下 chain-v7 的調校項目。
- **根因**：同 K-066 的分析。
- **做法**：
  - `fuxi_wifi_apple80211.c`／`fuxi_wifi_sta.c` 實作 bit 3／4，並加開關切換和掃描的耗時紀錄。
  - 0121 讓核心從 ADT `/chosen fuxi,args` 讀參數。
  - 產生器 `--daily-tuning` 把 chain-v7 的 7 項調校放回命令列。
- **復現**：loader `native-v7wifi-1118-0030-ram9g-srgb-loader`（`--daily-tuning --wifi-args-adt --wifi-ux 31`），本機 `kernel-local-wifiux2-9g-artifact`。
- **主機測試**：`test-fuxi-wifi-ios.py`、`ksrc\tools\test-fuxi-adt-args.py`；產生器 self-test 有 `fuxi,args` 的負測試（重複 token、空字串、過長、NUL）。
- **驗證紀錄**：`native-hw000wifi-v7wifi-boot-1`，00:31–00:49:30（900 秒），console 25431 行，SHA-256 `822c283c24fb1a66e4b4e57c0bb515cf179b04840c92f563b9f8018f3c71f83c`，USB 斷 2 次都重連，最高 62.3°C。
  - ux 0x1f 生效，ADT 參數有讀到；開機自動加入 438 ms。
  - 第一次量到掃描耗時：2.4 GHz 13 頻道約 0.94 秒，5 GHz 27 頻道約 7 秒，全頻 16 秒（每個 5 GHz 頻道約 260 ms）。
  - 同趟先用 `phone-readthrough.py --install-app` 裝酷安（T／U 系列）。
- **參考來源**：iOS 16 wifid SET 51（本機反組譯）。
- **結論／未完成**：日常 chain-v8 合入這版（ADT `fuxi,wifi-ux=31`、`fuxi,wifi-rssi=1`，B 系列）；掃描慢留給 K-068／K-069。
- **出處**：journal `native-hw000wifi-v7wifi-boot-1`、「日常 v8 合併」。

### K-068 限制隱含掃描範圍＋分組停留（失敗、已回退）
- **日期**：2026-11-18 01:03（a23e701），01:09 由 490764d 回退
- **狀態**：放棄
- **開關**：當時 `fuxi,wifi-ux` bit 6（ux=127）
- **問題／現象**：想把全頻 16 秒的掃描縮短。
- **根因**：分組 dwell 在真實韌體上分批耗時過長；主機測試沒涵蓋。
- **做法**：（已回退）未指定頻道時改用 iOS 公布的頻道清單，再用模組的 dwell extension 依主動、被動、雷達頻道分組。
- **復現**：不建議重現。回退方式：
  - `git diff 497a117 HEAD` 為空。
  - harness `patches/kernel-adsp-battery.patch` 回到 `05880e1`。
  - loader 產生器回到主倉庫 `dbbb912`。
- **主機測試**：當時兩份 Wi-Fi ASan／UBSan、loader self-test 和 38 項 workflow 命令全過，但都沒涵蓋真實韌體的分批逾時。
- **驗證紀錄**：
  - `native-hw000wifi-scanscope-boot-1`（loader `native-scanscope-1118-0105-ram9g-srgb-loader`），01:05:32：第一輪 15 頻道分五批，30,001 ms 逾時（error 60），native worker 隨後退出。使用者回報掃描沒結果、關不了 Wi-Fi。USB SHA-256 `447410a777ec6d3598d5fa67dc6c38f4915802e9ed7e00c1266020613728eb18`，最高 61.1°C。
  - 回退後 `native-hw000wifi-rollback-boot-1`，01:12:56：重開 `native-v7wifi-1118-0030-ram9g-srgb-loader`（boot SHA-256 `7a66e622c513473d2426827b95b837943c79dbd229f49676a3c49e0f0d84da27`）。POWER off 2 ms／on 18 ms，掃描 7,427 ms、39 BSS；第一次加入在四向握手失敗（error 80），留給使用者檢查。
- **參考來源**：無。
- **結論／未完成**：
  - 這組設定拒用。
  - 國家碼只在 iOS 層保存；底層是不是 world 法規域、舊全頻掃描有沒有包含 6 GHz，都未證實。
- **出處**：`work\localbuild\wifi-scan-validation-20261118.zh-TW.md`「失敗與限制」「回退方式」。

### K-069 掃描中止／逾時恢復與公布頻道掃描（bit 5～6）
- **日期**：2026-11-18 11:11（a41069f）
- **狀態**：已驗證（實機兩趟；日常還沒合入）
- **開關**：
  - `fuxi,wifi-ux` bit 5（32，`SCAN_RECOVER`）：已受理的掃描被中止或逾時後，保留電源控制。掃描沒回完成事件前，先擋下一筆掃描和加入，等原事件到，或切換電源更新 generation。
  - bit 6（64，`SCAN_CHANNELS`）：未帶頻道的掃描改用 iOS 公布的 2.4／5 GHz 清單。指定的頻道和停留時間照傳，預設停留時間的掃描維持一批。
  - 兩個都預設關。
- **問題／現象**：K-068 失敗後，需要先讓「掃描卡住就關不了」不再發生，再安全地縮小範圍。
- **根因**：掃描沒回完成事件時，電源控制被卡住。
- **做法**：沿用既有 ath12k 模組的 SCAN_DONE 和電源確認契約；harness `522e94b`。
- **復現**：
  - 本機 `kernel-local-wifi-recover-1118-9g-artifact`：建置 101 秒，38 項 workflow 主機命令、86 項產物雜湊。
  - loader `native-scan-ux63-1118-ram9g-loader`、`native-scan-ux127-1118-ram9g-loader`：同核心、同 RTC 校時、同命令列，payload 只差 ADT 掃描範圍位元。
- **主機測試**：`test-fuxi-wlan-ios.py`。ASan／UBSan 涵蓋 reply／SCAN_DONE 先後到達、批次逾時、切電源時中止、晚到的完成事件和之後的重掃。
- **驗證紀錄**：
  - `native-hw000wifi-scan-ux63-1118`，11:16:16：兩輪關／開自測通過，各一次 join finished 0。兩次全頻掃描 15,784 和 15,769 ms（各一批）。USB SHA-256 `4b68768dcd506ba2adb71c398ac54716b785d97e6bcbe806b8c00aea3592b673`，最高 65.5°C。11:26:27 等不到 Android ADB（常駐選單要按鍵確認），啟動器自動釋鎖。
  - `native-hw000wifi-scan-ux127-1118`，11:39:51：
    - 40 頻道一批掃描 11,295 ms、27 BSS，比全頻平均 15,776.5 ms 少 28.4%（關開後只量到一次）。
    - 第二輪關閉 104 ms 內完成，但 wifid 在自測讀電源前又打開了，自測回 EIO 5 提前結束。
    - 兩次在 5200 MHz 加入成功。
    - USB SHA-256 `d480190d19ba8be0a39a8280a7e59ea9cb072147b4141ebca4cb9e4d47cb981e`，最高 79.3°C。11:45:10 回 Android。
- **參考來源**：UniXNU Ath12kWifi `src/nw_sta.c`（公布頻道清單）。
- **結論／未完成**：下載吞吐和長時間連線還沒測；日常 chain-v8 仍是 ux=31。
- **出處**：`work\localbuild\wifi-scan-validation-20261118.zh-TW.md`「11:16 起續修」「11:39 的 40 頻道對照」。

### K-073 優先處理 Wi-Fi 關閉、批次接收與連線統計（bit 7～9）
- **日期**：2026-11-18 12:05（af3c264）；上機 12:26（ux1023）
- **狀態**：實驗（ux1023 上機一趟；ux767 對照未跑）
- **開關**：
  - `fuxi,wifi-ux` bit 7（128，`POWER_OFF_FIRST`）：先做完排隊中的關閉，再受理後到的開啟；關閉可中止掃描和進行中的加入。
  - bit 8（256，`RX_BATCH`）：用既有 ath12k 封包讀取回呼，直接填進 mbuf，批次交給 XNU。
  - bit 9（512，`LINK_STATS`）：有流量時每 5 秒印一次 PHY TX 速率和 en0 位元組計數。
  - `FUXI_WIFI_UX_ALL` 是 1023。
- **問題／現象**：使用者回報「設定 → Wi-Fi」關閉不穩，下載最高約 210 Mbps。
- **根因**：
  - 關閉和開啟的要求次序沒有保證。
  - 接收路徑逐封包複製再交給 XNU。
- **做法**：`fuxi_wifi_sta.c`／`.h`、`fuxi_wifi_net.h`、`fuxi_wlan_ios.inc`、`fuxi_wlan_ath12k.h`；harness `7900eac`。
- **復現**：
  - 本機 `kernel-local-wifi-power-rxbatch-1118-9g-artifact`：建置 64 秒，38 項 workflow 主機命令通過。
  - loader `native-wifi-power-ux767-1118-ram9g-loader`（關閉批次接收）和 `native-wifi-power-ux1023-1118-ram9g-loader`（開啟）：逐位元比對只差接收批次開關，兩者都保留實際 Settings 操作。
  - 上機要有 USB 連線和有效的 RTC 校時（一小時內）。
- **主機測試**：`test-fuxi-wlan-ios.py`、`test-fuxi-wifi-ios.py`。
- **驗證紀錄**：
  - 對照組：上一趟日常 ux=31 的持久紀錄 boot#96（`fuxilog61118-122545`），其中一筆關閉排隊 4,786 ms，另一筆在掃描期間被隨後的開啟蓋過。
  - `native-hw000wifi-power-ux1023-1118-1225`（loader `native-wifi-power-ux1023-1118-1225-loader`），12:26:14 RAM 開機：
    - 兩次在設定頁關閉，都在 67–71 ms 完成；第一次中止了未完成的掃描。
    - 第一次重新加入成功後約 50 秒沒有接收，第二次關開後恢復流量。
    - 使用者回報約 220 Mbps；en0 最高的 5 秒接收平均 196.88 Mbps，同區間 TX PHY 採樣 576.4 Mbps。
- **參考來源**：UniXNU-sheng `package/WifiNet.cpp`（commit `68800685763d755c368775b848dd703fb3f8a3ce`）的接收批次作法。
- **結論／未完成**：
  - 關閉優先已見效（4,786 ms → 67–71 ms）。
  - 「加入後約 50 秒無接收」未解。
  - 待同核心不分批（ux767）對照吞吐。
- **出處**：journal「2026-11-18 12:06 Wi-Fi 關閉與下載續修」。

### K-074 ath12k 接受韌體配置的 peer ID 0

- **日期**：2026-11-18 12:25–13:00（台北時間）
- **狀態**：修正版完成一趟暫時開機驗證，重連後即有資料流量
- **開關**：使用含 peer ID 0 修補的 ath12k 物件。對照組與修正版都開啟接收批次（ADT fuxi,wifi-ux=1023），沿用相同命令列與 root extents。
- **問題／現象**：對照趟第一輪重新加入成功後，en0 一段時間收不到資料。TX completion 顯示 peer ID 0 查找錯誤。
- **根因**：釘選的 Linux 7.0.14 ath12k 把韌體可合法配置的 ID 0 當無效值。上游修補保留 ID 上限，移除 ID 0 的特例拒絕。
- **做法**：harness 9ca823f 回移植修補，ksrc 1431ae5 與 harness 91698cf 讓連結檢查接受該份經驗證的物件。工作區 cca035e 登記已驗證的 loader 輸入。CI 使用固定來源的 ASan／UBSan 對照驗證舊版會拒絕 ID 0，修正版可接受。
- **復現**：取 macOS run 44239539371 的 fuxi-ath12k-objects 與 manifest。執行 build-kernel.ps1 -Ram 9g -Name kernel-local-wifi-peer-zero-1118-9g-artifact -Tests -Ath12k <物件目錄>。以接收批次對照趟為 --like 基底，依總索引步驟 5–6 換入該核心。使用歷史 loader native-wifi-peer-zero-1118-1252-loader 時，先依目前裝置核對 root extents、RAM 與 RTC。進設定關開 Wi-Fi 並測速，核對首次連上後第一個五秒 en0 讀值和 TX completion。
- **主機測試**：本機 9g 建置 68 秒、38 項 workflow 主機命令通過。CI 30 項物件檢查通過。連結條件見 tools/test-fuxi-ath12k-link.py。
- **驗證紀錄**：native-hw000wifi-peer-zero-1118-1252 於 12:53:51 開機，第一次重連 5200 MHz 的首個五秒取樣收到 38,461 bytes。峰值五秒平均接收 228.45 Mbps，該區間 TX PHY 864.6 Mbps、RSSI −59 dBm。查找錯誤與 panic 均為零，12:59:45 回 Android。原始 boot.log SHA-256 為 91d073877da8462f8e67af85cfd19e8403b8f9c5b0c8fa8a5b1f8d184a54c40b。
- **參考來源**：[上游 ath12k 修補](https://lkml.iu.edu/2605.1/06622.html) · [macOS CI 44239539371](https://github.com/scyx2611/fuxi-metal-frontend-check-20261108/actions/runs/44239539371)
- **結論／未完成**：此趟驗證首次重連就恢復資料與測速流量。持續使用與跨重開機留待各版本的獨立紀錄。
- **出處**：work/hw000-adaptation-status.zh-TW.md 的 12:06 段落、work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-peer-zero-1118-1252/boot.log、work/adsp-battery/prepare-wlan-w18-loader.py。

### K-075 ath12k WMI 掃描優先級與首輪掃描時間

- **日期**：2026-11-18 13:13–13:33（台北時間）
- **狀態**：修正版暫時開機三輪設定頁關開通過
- **開關**：核心按需 Wi-Fi 追蹤 fuxiwifitrace。A/B 使用相同 ADT、命令列與 root extents，變更 ath12k 物件的 WMI priority 欄位。
- **問題／現象**：開啟 Wi-Fi 後首輪僅三個頻道，仍等了 7,395 ms。事件顯示 802.11d 啟動後 7,021 ms 才有頻道切換，BSS 回報後 wifid 立即讀取。
- **根因**：ath12k 送 WMI 掃描命令時須輸出已選擇的掃描優先級。補上該欄位後，手機的首輪切頻和 BSS 結果顯著提前。數字用以界定這次變更的實機效果。
- **做法**：ksrc 43b2e2b 補 fuxi_wlan_ath12k.inc、fuxi_wlan_ios.inc 與 fuxi_wifi_sta.h 的時間／韌體事件欄位。harness 7387e88 補 WMI 封包序列化，ksrc 5b0e0b3 與 harness be60a9f 更新物件輸入檢查。韌體仍執行 802.11d 掃描。
- **復現**：以 macOS run 44243587936 的 fuxi-ath12k-objects 和 manifest 編本機 9g 核心。對照 loader native-wifi-scan-trace-1118-loader，修正版 native-wifi-scan-priority-1118-loader。依總索引步驟 5–6 檢查兩份輸入同條件並開機，在設定頁關閉再開啟 Wi-Fi，量首輪 5200／2412／5745 MHz 和「首輪送出到 wifid 掃描完成」兩段時間。每輪再檢查加入後 en0 接收計數。
- **主機測試**：9g 核心 59 秒，38 項 workflow 主機命令、31 項 ath12k 物件檢查通過。
- **驗證紀錄**：對照 native-hw000wifi-scan-trace-1118 的設定頁掃描完成為 9,380 ms。修正版 native-hw000wifi-scan-priority-1118 的三輪為 1,646／1,629／1,723 ms，三頻首輪為 414／408／414 ms。三輪首次自動加入 5200 MHz 均收到資料。13:33:28 回 Android 並釋鎖，使用者確認明顯提速。
- **參考來源**：[ath12k 802.11d offload 變更](https://lists.infradead.org/pipermail/ath12k/2025-March/006346.html) · [macOS CI 44243587936](https://github.com/scyx2611/fuxi-metal-frontend-check-20261108/actions/runs/44243587936)
- **結論／未完成**：確認這組 AP 與設定頁操作的掃描延遲下降。下載 220 Mbps 是 K-073／K-074 所列對照的驗收結果。掃描速度分別以首輪完成時間和設定頁整段時間記錄。
- **出處**：work/hw000-adaptation-status.zh-TW.md 的 13:13 段落、work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-scan-trace-1118/boot.log 第 6627–6719 行、native-hw000wifi-scan-priority-1118/boot.log 第 5439–8126 行。

## 其他核心項目

### K-070 NativeAdreno host-import 配額失敗回報 Vulkan OOM
- **日期**：2026-11-17 08:58（566aaa9）
- **狀態**：已驗證
- **開關**：無（Turnip／mesa 補丁）
- **問題／現象**：K-057 那趟，Safari 的 WebKit 大貼圖（`b3a8` 3001×1500、`w30r`）被 backboardd 的 Metal 後端拒收，gate 判成 runtime-failure，backboardd 以 CPU 重生。
- **根因**：host-import 配額不足時，回的錯誤碼不是 Vulkan 的 OOM，上層就當成致命失敗，不會走降級路徑。
- **做法**：`ksrc\tools\patches\mesa-fuxi-hostimport.patch`：BoImport 因配額失敗時回 `VK_ERROR_OUT_OF_DEVICE_MEMORY`，其他失敗仍回 `VK_ERROR_INVALID_EXTERNAL_HANDLE`。
- **復現**：依 G 系列的 Turnip 建置流程套這個補丁；上機用 `launch-loader-check.ps1 -TurnipHybrid <檔> -TurnipSha <SHA256>`。
- **主機測試**：`test-fuxi-turnip-hostimport.py`（核心端 HostImport user client 另有 `test-fuxi-hostimport.py`，屬 G 系列）。
- **驗證紀錄**：`native-hw000wlan-hybimport-safari-boot-1`，09:32–09:43:42：寫 11 個區塊（PRE_OK／WRITE_OK）安裝獨立 hybrid，09:35:24 開機，沿用本機 akswrap 核心。
  - 1200 列裁切圖 5184000 bytes、9.2 秒、0 次重連，親眼看是 Safari 分頁畫面。
  - USB SHA-256 `84e6cac532241cd8c135802644e474c42b40263aa86131dbe9088a5a9cf7139a`；CPU 短峰 83.6°C。
  - boot#56 持久紀錄 `fuxilog\20261117-094627`。
- **參考來源**：Vulkan 規格 `vkAllocateMemory` 的錯誤碼；mesa Turnip。
- **結論／未完成**：G 系列有對應項目（GPU 線）。
- **出處**：journal `native-hw000wlan-hybimport-safari-boot-1`。

### K-071 指定行程的有界取樣（sweetprofname）
- **日期**：2026-11-17 09:53（d10a41d）
- **狀態**：已驗證（診斷工具）
- **開關**：
  - boot arg `sweetprofname=<行程名>`；loader 產生器 `--profile <名> --profile-delay <秒>`。
  - 既有的 `sweetsample=<名,名…>`（`--sample`）做多行程堆疊取樣。
- **問題／現象**：要分析特定 userland 行程的 CPU 熱點，例如 coreduetd 57% CPU、locationd 卡死。
- **根因**：（工具）
- **做法**：`ksrc\xnu\fuxi-prof\sweet_prof.c`（補丁 `0111-fuxi-user-profiler.patch`）只對指定名稱的行程做有界取樣。
- **復現**：在 loader 加 `--profile <行程名>`，上機後在 console 找取樣輸出。
- **主機測試**：`test-fuxi-prof.py`；同步工具 `sync-fuxi-prof.py`。
- **驗證紀錄**：K-059 那趟用 `sweetsample=Preferences,locationd,wifid` 找到 locationd 卡在 FairPlay MIG。
- **參考來源**：0111 原有的 `sweetsample` 取樣器。
- **結論／未完成**：無。
- **出處**：ksrc d10a41d。

### K-072 ksrc 基底與維護
- **日期**：2026-11-14 19:45（75148d2）、2026-11-15 00:06（f1a0846）
- **狀態**：維護
- **開關**：無
- **問題／現象**：ksrc 是讓補丁可以用 git 管理的展開樹。
- **根因**：（維護）
- **做法**：
  - 75148d2：基底 zgl97/ios-fuxi `979e2f08` 加上當時 harness 的全部補丁（harness HEAD `2aae087`）。
  - f1a0846：0106 讀取的韌體分區變多之後，重產 0111（只有 hunk 位移）。
  - 3277d2c 屬 GPU 線，見 G 系列。
  - WLAN M5～W17、ADSP 早期與 UniXNU 移植的上游脈絡見 S／E 系列。
  - 從 ksrc 根目錄執行下表的 `python3 tools/<腳本>`。補丁編號對應 `xnu/patches/` 的檔名前綴。

  | 同步腳本 | 重產或校驗的補丁 | 主要輸入 |
  | --- | --- | --- |
  | `sync-abi-backend.py` | 0098 的 NativeAdreno ABI 後端區塊 | NativeAdreno probe／後端 |
  | `sync-fuxi-adreno-shared.py` | 0096、0098，並核對 0100 的連帶變更 | Adreno 共用 header 與 Metal 同步腳本 |
  | `sync-fuxi-adsp.py` | 0117 | ADSP、SweetBattery、電池 TTL、音訊準備與共用電源原始碼 |
  | `sync-fuxi-audio.py` | 0113 | 音訊 GPR 與 RSC 仲裁器 |
  | `sync-fuxi-backlight.py` | 0109 | 背光服務與 DSI 控制 |
  | `sync-fuxi-h1.py` | 0103 | H1 相容層、按鍵與 RTC |
  | `sync-fuxi-idle.py` | 0105 | Idle／IPI 診斷 |
  | `sync-fuxi-metal.py` | 0096、0098 | GPU probe、NativeAdreno ABI 與 XNU 接線 |
  | `sync-fuxi-metal2.py` | 0100，讀取 0098 以核對相依關係 | execswap、handle index 與 user client |
  | `sync-fuxi-pac.py` | 0114 | PAC 自我測試 |
  | `sync-fuxi-perf.py` | 0097 | 觸控／編譯調頻與排程 |
  | `sync-fuxi-prof.py` | 0111 | 使用者空間剖析器 |
  | `sync-fuxi-regtrace.py` | 0112 | IORegistry 與 Work-Interval 追蹤 |
  | `sync-fuxi-scanout.py` | 0108 | SweetSurface、顯示觸發和 Scanout |
  | `sync-fuxi-sys.py` | 0107 | P-SYS 服務與路徑政策 |
  | `sync-fuxi-unixnu.py` | 0106 | UniXNU 移植、mtdblk 紀錄與顯示 |
  | `sync-fuxi-wifi-ios.py` | 0104 | Apple80211／IONetworkStack 與 station 模型 |
  | `sync-fuxi-wlan.py` | 0099 | WLAN 核心 C／include，含 RPMh 與 ath12k 接線 |

- **復現**：在 WSL 的 ksrc 樹改原始碼，跑對應腳本重產補丁，再加 `--check` 重跑並檢視該份補丁差異。將原始碼與補丁一併提交到 ksrc，再依總索引共用步驟 2，以 `eafc778..HEAD` 重產 harness 的外層 `kernel-adsp-battery.patch`。使用 WSL 可讓未指定 newline 的產生器輸出 LF。
- **主機測試**：同步腳本用 `--check` 核對內容。各硬體主機模型依對應 S／K 項目，workflow 套補丁順序見 T-059。
- **驗證紀錄**：無。
- **參考來源**：無。
- **結論／未完成**：無。
- **出處**：ksrc `git log` 與 `tools/sync-*.py`，以各腳本的 patch 路徑與執行分支核對。
