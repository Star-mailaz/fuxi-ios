# 快充／拔線：只讀證據與下一輪驗收判準

2026-11-16，首個 bounded checkpoint，後續接 iter3 / 第14趟已保存 log 更新。新增／更新範圍僅 `tools/fuxi-charge-evidence.py`、`tools/test-fuxi-charge-evidence.py` 與本文件；沒有修改先前 producer / consumer / helper 的九檔，也沒有新增 runtime、操作手機、取得手機鎖、commit / push / branch、改 sync / build / patch 或調整限流、電壓、溫保。只讀既存本機 log；以下物理實驗由主線日後安排，不打斷使用者。

## 一、必須分開的結論

| 項目 | 可以支持的結論 | 不能替代的證據 |
| --- | --- | --- |
| raw USB voltage / current | 該 diagnostic snapshot 的 USB 輸入 telemetry，`V × I` | 外接電表、同時取樣保證、穩態功率或 67W 峰值 |
| battery voltage / current | 電池端淨吸收／釋放功率，含系統負載影響 | USB 端輸入功率；不能把兩端 W 直接相等 |
| USB input limit / max | 已回報的限流／能力上限欄位 | 當下實際電流，或為何 firmware 限流的完整原因 |
| BmUsbAdapter=6 / PD family | 本機 codec 對 enum / family 的 PD label | PDO 合約、供電器／線材能力、QC 模式或 67W 實測 |
| QC / PD / 67W 文字、包裝／額定 | 宣稱與實驗設定 | 實測功率與可接受快充 |
| charging flag | firmware / consumer 回報充電狀態；有資格時才是 fresh charging flag | 正淨電池功率、快充或滿功率 |
| 可接受快充 | 指定 SOC / 溫度 / 負載、相同充電器線材下的電表穩態量測與預先約定的 baseline 比較 | 單筆高 W、PD label，或在 100% 未到峰值就判 broken |

工具刻意把 `usb_input_telemetry_signed_w`、`battery_net_charge_positive_w`、`usb_input_meter_w` 分開。最後一項在本 checkpoint 始終是 null；`physical_unplug` / `fast_charge_acceptance` / `acceptable_fast_charge` 始終為 not_established，不會從配置宣稱或 log 圖示自動簽核硬體。

## 二、來源、單位與不改策略的證據

本輪直接核對 `xnu/fuxi-adsp/ShengBattmgr.h`、同目錄 vendor codec C、`fuxi_adsp_battery.c` 與 `SweetBattery.cpp`。沒有下載或假定另一份 Android downstream property 表，也沒有把另一平台的 QC enum 套到 fuxi。解析表重用此 owning enum，host test 驗證所有採用的 field index 與現有 header 一致。

| raw index | owning enum | codec GET | 單位／用途 |
| --- | --- | --- | --- |
| f0 / f2 | BmStatus / BmCapacity | BATTERY_GET properties 0 / 4 | status；SOC hundredths-percent |
| f3 / f4 / f5 | BmVoltage / BmCurrent / BmTemperature | BATTERY_GET 7 / 9 / 13 | µV / µA / 0.01°C |
| f7 / f8 | BmUsbOnline / BmUsbType | USB_GET 0 / 6 | online / type |
| f9 / f10 | BmUsbVoltage / BmUsbCurrent | USB_GET 1 / 3 | µV / µA |
| f11 / f12 | BmTimeToEmpty / BmTimeToFull | BATTERY_GET 21 / 20 | seconds；無可用估計不發布零分鐘 |
| f20 / f21 / f22 | BmUsbAdapter / BmUsbLimit / BmUsbMax | USB_GET 7 / 5 / 4 | adapter enum / µA / µA |
| f24 / f25 | BmThermalLevel / BmChargeCurrent | BATTERY_GET 10 / 12 | thermal level / µA；不是 USB 實測電流 |
| f27 / f28 / f31 | BmPowerMax / BmPdVerified / BmInputSuspend | BOARD_GET 0x33 / 0x18 / 0x2a | 回報 watts / verified / suspended，非電表讀值 |

vendor codec 的 `kFields` 第 12–44 行、header 的 enum 第 31–40 行支持以上映射。`USB_GET=0x32` 來自 header，不新增 opcode。`BmUsbAdapter` 是 field index 20，但其 wire USB property 是 7，不是 property 20。

vendor snapshot 第 266 行把 battery raw current 取負後轉 mA；這條 iOS 路徑是 charge-positive：

- raw 電池端淨充電 W = `−BmVoltage(µV) × BmCurrent(µA) / 10^12`。
- summary 電池端淨充電 W = `mV × mA / 10^6`。正值為淨吸收，負值為淨放電，零不等於拔線。
- raw USB signed telemetry W = `BmUsbVoltage(µV) × BmUsbCurrent(µA) / 10^12`。保留負號；沒有足夠來源把負 USB 電流一律視為 charging，所以不取絕對值。
- vendor 第 279–283 行的 summary adapter current 已取絕對值，watts 是整數四捨五入。工具另列其來源限制，原始 signed USB 優先解讀，但不把不同 records 的數值互相補齊。

**不能宣稱整個既有 ADSP client 都是 only-GET。** 原 codec 第 62 行已有 SDP 900000 µA 設定；第 121–130 行可發 USB_SET/property 5；第 142–155 行 `wanted_limit` / `check_limit` 對 SDP / CDP 有既有策略，其他類型由 firmware 決定。這些是先前 vendor 行為，不是本 lane 新增。本工具只解析 GET 回報、既有 summary 與 metadata，不會發任何 GET / SET，沒有 transport、手機命令或充電設定介面；host tests 僅啟動同一 host Python CLI。

本輪重算 vendor SHA256，codec C=`12f25e0ca84164fe060c63161c6e9a3908742451cfb09ccd114cfe047130727e`，header=`bb652fc1d23ccebcc08b86228fc895c73cec38238bdbc55b6f08ff7975ab6d3d`，與前輪相同。這支持「本 lane 沒改既有 firmware／限流策略」，不證明 firmware 當下已協商特定功率。

## 三、解析工具與使用

在 `D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc`：

```powershell
python tools/fuxi-charge-evidence.py D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109\native-adsp2b-user-loader-boot-1\boot.log
python tools/fuxi-charge-evidence.py C:\existing-logs\boot.log C:\existing-logs\ci.log --manifest C:\existing-logs\experiments.json --since 60 --until 180
python tools/test-fuxi-charge-evidence.py
```

工具僅讀指定 log / manifest、輸出 JSON 到 stdout，不產生 runtime 或寫入輸入檔。第二個例子是假設日後主線已將 log 存在 host；本 worker 不取得新手機讀數。

可選 manifest 的形狀如下。相對 log path 以 manifest 所在目錄解析；同一 log 不得重複宣告。整份配置以 `experiment_declared_unverified` 保存，不能替代輸入的物理證據：

```json
{
  "experiments": [
    {
      "log": "boot.log",
      "experiment_id": "ios-normal-low-soc-pd",
      "kind": "device_boot",
      "config": {
        "charger_model": "user-recorded model",
        "cable_model": "user-recorded cable",
        "rated_watts": 67,
        "protocol_label": "PD",
        "soc_start": 40,
        "ambient_c": 25,
        "load_description": "screen off, no torch or stress test",
        "staged": false
      },
      "boot_hashes": {
        "kernel_sha256": "user-recorded artifact SHA256"
      }
    },
    {
      "log": "ci.log",
      "experiment_id": "battery-native-ci",
      "kind": "ci",
      "config": {"purpose": "native build and host tests, not device charging"}
    }
  ]
}
```

### 隔離與保守邊界

- 每個檔案一個 report；檔內以 Darwin kernel banner 分 boot segments，不合併兩 boot 的 raw / charger / metadata。每 boot 的來源 hashes、source commits、boot args、unverified labels 分開保存；hash 衝突不覆蓋成最後一筆。
- `log_sha256` 是工具確實完整讀取且 stat 未變時的整份 log hash，不是 kernel / loader artifact hash。達 bytes / boot 上限或讀取時檔案變動，整檔 hash 為 null，另列 prefix hash 與掃描 bytes。log 自述的 artifact hashes 與 manifest 宣告也分開，沒有自動驗證 artifact 本體。
- `[10.5]`、`[10500ms]`、開頭 `t=10.5s` / `time=10.5s` 支持相對秒窗。wall-clock 文本保留但不轉成相對秒；沒有 timestamp 的記錄為 unknown。禁止借用鄰行／同一物理行後面串接的前一筆 timestamp。帶時間窗時 unknown 記錄仍列出，但不進該窗功率 min/max。
- 支持真實 FUXI summary / raw、SweetBattery publication、same-line `FuxiBattery*` / `SweetBattery*` 數值或 Yes/No / true/false properties。支援單位 µ/μ/u、m、base V/A 及符號；native int32 範圍外／單位錯誤值無法計功率。
- 不跨行拼湊 IORegistry properties 成一次快照。只有同 record 的 known / channel / mask / ages / TTL 一致，才標 fresh；fresh online=0 可不要求 status 成功時間尚 fresh。部分 metadata、default / unknown / stale / invalid、loss、TTL 邊界均保守處理。raw `valid` bit 不是 field TTL，也不證明 accepted GET generation。
- `fuxi,adsp=4` / `fuxiadsp=4`、staged marker 或 manifest staged 設定使整個 boot 保守排除物理驗收。單純 57% 不推定 staged；沒有 marker 也不證明 boot 真的是非 staged。staged57% / external=0 永遠不成為物理拔線證據。
- 不認識的 adapter enum 保留 unmapped，不自行映射 QC。PD/QC/67W 文字只列 unverified text claims。所有 power summaries 是 retained diagnostic records 的觀測範圍，不是峰值／平均／能量積分；工具沒有跨時間插值或電表匯入功能。
- 預設每檔 64 MiB、每行 65536 bytes、全檔最多保留 2000 records、32 boot segments；超長行整行略過並標 incomplete，超過保留額度標 omitted。截斷或緊接其他 message 的尾端數字不推測剩餘位數。輸出上限可由四個 `--max-*` 明確設定。
- iter3 接續新增 `--tail-bytes N`：掃描尾端 `min(N, max-bytes)` 範圍，以一個額外 byte 檢查起點是否落在半行，半行整段丟棄。`scanned_byte_range` 採半開 byte range，另給 `scanned_range_sha256`；起點非零時整檔／prefix hash 均為 null，行號只相對 scan start，不能當原始檔絕對行號。未掃到的 boot／staged prefix context 明確列 missing，所有尾段 records 排除物理驗收。小檔若整份落在 tail 範圍，仍可計完整檔 hash。

## 四、實際 host checkpoint 證據

Python 3.12 stdlib `unittest`：**33 tests 通過**，包括真實 parser fixtures、partial / 截斷 / 串接、符號與單位、unknown / stale / bootstrap、同 record fresh qualification、兩檔與兩 boot 隔離、PD 低功率满 SOC、staged 隔離、時間窗／無時間／wall-clock、零／負 current、hash 配置隔離與衝突、長 log bounds、CLI manifest 及 enum 對照。這是 Python parser 測試，不是 MSVC / native C / ASan 或手機驗證；本輪未重跑或改動上一批 1848 / 1882 / 24 的九檔測試。

直接對既存本機 log 跑 CLI 得到下列分開的觀測，沒有採集新手機資料：

| log | bytes / 整檔 SHA256 | retained records | raw USB telemetry 最大 W / summary 最大 W |
| --- | --- | --- | --- |
| `work/Codex-Xiaomi13-GPU-20261109/native-adsp2b-user-loader-boot-1/boot.log` | 270513 / `7fa0297e7e392fa4b679003d1a4f09826f6341cfea7848b4bf86f1e10c366060` | 49 | 3.840882 / 4.20444 |
| `work/Codex-Xiaomi13-GPU-20261109/native-adsp3t-user-loader-boot-1/boot.log` | 494879 / `566fd90d41aada89b5ab11be4b2be10d11088546b947a4d9f97a8e95e6c5f631` | 327 | 3.647168 / 4.025630 |

這些 log 都出現 PD enum / 满 SOC 背景，但缺完整 battery timestamps、逐欄位 accepted GET / generation、新 freshness metadata、物理拔線確認、外接電表及 boot artifact hash。原文有串接／截斷；整檔 hash 完整不代表內容完整。工具不把以上最大觀測當峰值，亦不判 67W broken。兩份 log 的時段／配置不可互相充當 baseline。

真實 fixture 的 source 位置：adsp2b `boot.log:1055` 的 4393 mV / −579 mA summary，與 `boot.log:2921` 的 raw f20=6、f21=1200000、f22 被串接截斷。後者 raw USB 為 4.622 V × 0.831 A = 3.840882 W；電池端為 4.436 V × 0.343 A = +1.521548 W。這支持單位與兩端功率要分開，沒有提供同時性或時間長度。

## 五、後續物理實驗的預先判準

### A. 正常拔線／recovery 的資料路徑

1. 先以新 CI snapshot 的正常非 staged boot 身分及 kernel / loader hashes 確認版本。CI build / host PASS 與真實 device-run 分開歸檔。保留實際 MaxAgeMs；本輪不調 TTL。
2. 主線與使用者另約可操作時段，記錄充電器／線材／插孔、SOC、溫度、負載，以及**使用者真拔線／再插线的物理時間與觀測**。不要以 staged tour、channel loss、zero current、UI 圖示替代這一列。
3. 同一 boot / 同一時間基準核對物理事件 → codec 接受成功 USB-online=0 的 GET → fresh external-known=true / external=false → consumer primary / AppleRaw / AdapterDetails / legacy 一致。SOC 壞值或 status timeout 不得阻擋已接受 online=0；charging/full 應 false，adapter cleared。新版本 worker 處理後可發布，UI 最多一個實際 consumer poll 間隔再加量測到的排程延遲，不能預設物理拔線後立刻零延遲。
4. 若在線 GET 一直 timeout，判準是該 field age 到實際 TTL 後 known=false / stale；保留最後 external 值可以接受，不能偽造 false。capacity 持續成功不得重置 online / status age。source 全停流與 channel down/up 分別歸檔，loss 的 producer 資格立即失效，consumer 於下一次正常 poll 更新 metadata。
5. 再插線後逐欄位恢復真值；不回 fake100 / external / full。任何不完整 log、無 accepted GET 時間、無 generation／一致 snapshot 或時間基準不能對齊者，都標 inconclusive，而不是宣称完成真拔線驗收。

### B. 充電可用，而非快充

- fresh online=1 + fresh status=charging 支持「回報正在充電」，正 battery net W 支持當時電池淨吸收，外接表正 USB W 支持插口輸入。三者分欄，不以其中一者推出其他兩者。
- charging flag 與負 battery W 可以在系統負載大時同時存在；须記錄螢幕／GPU／torch／壓力測試／溫度，不能單筆判 firmware 故障。相反，滿 SOC 的低電流／不充電可以是正常 taper／停止；需要對照同條件 Android baseline 或 OEM 策略資料。

### C. 可接受快充與 67W 峰值，分開驗收

- 先補充電器型號、支援的模式／額定 profiles、原廠／合格線材、外接電表型號與精度，確認電表／轉接線不阻擋 proprietary negotiation。不能為了測试下發限流、電壓或繞過溫保。
- 第一輪可規劃自然出現的中低 SOC（例如 20–60%）、相近 ambient / battery temperature、無額外 torch 或 RAM/GPU stress；這是實驗配置提案，不是宣稱 OEM 快充的溫度／SOC 門檻。不得強迫放電或解除保護來追峰。
- 用相同充電器／線材／電表／負載做 Android 與新 iOS 的獨立 matched runs，分別紀錄 SOC / temperature / profiles / time window，預先約定穩態窗與容許差。可先用 60–180 秒穩定期及至少 60 秒量測窗作規劃，但不能把未有 timestamps 的現存 log 套入該窗。
- 工程「可接受快充」至少要求：有效新鮮資料、電表量測穩定高於相同條件低功率 reference 且差值超過量測誤差、matched Android baseline 比較落在**事前約定**容許差、沒有異常熱／掉線／供電問題。容許差未定、充電器不兼容、SOC / 溫度不同或電表影響協商，都先記 inconclusive，不填假定的通過門檻。
- 「曾達 67W」另外要求兼容充電器／線材／模式、電表校正與同時時序證據，說清楚是短峰／持續值、量測位置、精度与持续时间。額定 67W 不是全 SOC 持續 67W 的保證；100% 時未達峰值不能判 broken。這個 parser checkpoint 沒有相關實測資料，不能簽核這項。

## 六、尚未驗證／刻意留給主線的接點

首輪沒有新 CI / device 資料；iter3 接續已有主線保存的 build 與第14趟 boot log，離線核對結果見下一節。本 lane 沒有採集新手機讀數，沒有完成 coherent runtime freshness、完整 IORegistry aliases／UI、充電器／電表或物理插拔驗收。CI PASS 本身不能替代真實供電實驗。未標記的 replay／staged／錯誤配置不能只靠文字 parser 認證。

現有 SweetBattery 把 freshness properties 放進 IORegistry，不會自動逐欄位印出完整 coherent metadata；現有 FUXI raw buffer 也可能只印出部分 fields。若新的 log 仍沒有同 snapshot 的 property／age／mask 与 accepted GET / generation 證據，工具會維持 missing。主線需在自己授權的後續觀測安排提供這些證據；本 worker 不加 runtime、不改 producer 或 consumer，也不宣稱已補上該觀測缺口。

## 七、iter3／第14趟接續 checkpoint

### 來源與版本邊界

主線回報 iter3 5g / 9g CI 成功、第14趟正常 ADSP 接管；仍未進行真拔線／快充驗收。本 lane 僅核對本機既有檔案，沒有重新操作或讀取手機，也没有變動 producer / consumer / helper、runtime 或提交 source。

| 保存的來源 | bytes／SHA256 | 本輪可核對的結果 |
| --- | --- | --- |
| `work/Codex-Xiaomi13-GPU-20261109/native-hw000iter3-battery-torch-audit-boot-1/boot.log` | 270845／`b84e0c89d1fd5b06c9a4c7a30cadd64ae953d620abd0e04c256332786521cf9b` | 91 retained records、16 partial records；正常 publication #2 / #3 的 known flags 與 #2 對應 readback 已見 |
| `work/Codex-Xiaomi13-GPU-20261109/kernel-adsp-iter3-5g-artifact/logs/build.log` | 140784043／`42148146e2d593320ff1d073205df5bebcbf10a9b7c60a34dd1cf21ace09d457` | 尾端 `XNU Build Done!` 已見，與 artifact SHA256SUMS 的 build log hash 相同 |
| `work/Codex-Xiaomi13-GPU-20261109/kernel-adsp-iter3-ram9g-artifact/logs/build.log` | 140786632／`d1546fbbf75cbc00b44c66b9ed9103ffb055b286c5e975f17d2e7b0e09f2c4c4` | 尾端 `XNU Build Done!` 已見，與 artifact SHA256SUMS 的 build log hash 相同 |

boot log hash 由 parser 完整讀取取得；build log 整檔 hash 另以 host `Get-FileHash` 重算，並與保存的 SHA256SUMS 對照。SHA256SUMS 所列 stripped kernel hash 分別為 5g `74940ae61f0686cc1fc9143113051819214ed0c2413146f8913361d0f08b22dc`、9g `aa54c3a5c5fc5cc5e8dcbdd932d7725164181f17a95f4cf6d68f1e63a92a638d`；本輪沒有重算 kernel binary，也沒有從裝置證實第14趟載入 artifact 的 cryptographic identity，因此仍保留 boot artifact hash 缺口。workflow success 是主線交接資訊；本輪没有再次查詢 CI API。

這兩份約 141 MB 的 build log 超出預設 64 MiB 前段掃描上限，前段未見完成標記只表示 not seen，不表示 CI 失敗。可用以下 bounded tail 命令，在不同 reports 保留 5g / 9g 證據：

```powershell
python tools/fuxi-charge-evidence.py D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109\kernel-adsp-iter3-5g-artifact\logs\build.log D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109\kernel-adsp-iter3-ram9g-artifact\logs\build.log --tail-bytes 1048576 --max-bytes 1048576
```

5g 掃描 range `[139735467, 140784043)` 的 SHA256=`4566b99ff1c95b78dfa35976648fca654c2fd076096efc57f9a3b912473c11c7`；9g range `[139738056, 140786632)` 的 SHA256=`a8e337640b615a85ba8b2960d92b7659c23873591cd5cd7d55923a4b00f2655b`。這兩筆是範圍 hash，不能冒充前述整檔 hash。兩份 report 均見 completion marker、0 battery measurement records，維持 incomplete / unscanned-prefix 與物理拔線／快充 not_established；不從 CI 推導供電功能已驗收。

### 第14趟到底支持甚麼

- `boot.log:70` 是 static fallback；第 71 行「ADSP battery manager, 100% 4200mV 0mA」只是 routing 選定，尚未證明實測資料。第 72 行 publication #1 的 external / charging 明確 unknown，full=1 是保留 bootstrap，不能當滿電／充電測量證据。
- 第 1840 行 publication #2 顯示 `100% external=1 charging=1 full=1 -778mA`；第 1841–1843 行見同一 publication #2 的 UserEventAgent / symptomsd readback。第 3104 行 publication #3 是 `external=1 charging=0 full=1 -9mA`。工具新增 `adsp_routing`、`sweet_publication`、`sweet_readback` 的角色區分及 publication-number／flag 比對，不再把 readback 或 routing log 計成一筆新的電池功率量測。
- 這支持「主線保存的正常接管與 consumer 發布／讀回路徑已出現」，但不含完整 coherent freshness / per-field ages / accepted GET generation，也沒有一次涵蓋 primary、AppleRaw、AdapterDetails、legacy 的同 snapshot 驗收。不能僅因沒有 `(unknown)` suffix 就簽核 TTL 或真拔線。
- 第 1399–1400 行雖出現 firmware summary / raw USB-online=0，主線仍未執行真拔線驗收；缺使用者物理事件與可對齊時間，不能拿這筆自行宣稱物理拔線成功，也不猜測其原因。
- 本趟 raw USB telemetry 最大觀測 2.197800 W，summary 最大 4.051092 W；raw 印出節奏有限，二者不作同時性、峰值或窗平均宣稱。滿 SOC、負 battery current / charging flag 共存要保留系統負載與 freshness context，不能冒充 fault 或 67W 故障。

### f0=0／f12=-1 唯讀語義結論

1. [Linux v6.12 primary `include/linux/power_supply.h`](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v6.12/include/linux/power_supply.h) 第 34–40 行明確定義 `POWER_SUPPLY_STATUS_UNKNOWN=0`、CHARGING=1、DISCHARGING=2、NOT_CHARGING=3、FULL=4。此次以固定 tag 直接讀取、未寫入 workspace，解碼後原文 SHA256=`3211d1508fe2aa68bbc545c5bda8443ae092a8a7257286939bd6c217ee54394b`。本機 vendor snapshot 第 250 行使用相同 1–4 status 語义，因此 f0=0 應解為 unknown，不是 charging fault enum。
2. f12 是 `BmTimeToFull`，秒數。現有 vendor codec 第 273–276 行明示負值／巨大值代表無估計；只有 `0 < seconds < 100*3600` 才轉分鐘，否則 snapshot time=-1。這支持把實際 f12=-1 視為「本 codec 沒有可用 time-to-full 估計」，**沒有證明每版 Qualcomm firmware 的 wire ABI 都必須使用 -1 作唯一 sentinel**，也不提供 error code／hardware fault 證據。工具新增 time fields 與 codec-qualified minutes，unknown 仍是 null，不改成 0 分鐘。
3. 未改動的 producer `fbValueValid` 第 198 行只接受 status 1–4；第 201 行 default gate 要求非負值。故第 1199 行 f0=0、第 1200 行 f12=-1 被 semantic gate 拒絕，不能 observe 或延長該 field TTL。拒絕「成為 fresh measurement」不等於 transport 失敗／firmware 充電故障，也不能據此要求改功率設定。
4. 本趟保留 log 中可見 f0=0 一次、f12=-1 七次；producer 的 rejection logging 共用有界計數器，只印前八次，工具的數目僅是 retained messages，不是未知值發生率或完整 GET 次數。第一個 cycle 的 raw mask `0xffffeffe` / f0=- / f12=-，後續 status 可回到 2；這些都與 unknown 資料不取得 fresh 資格相容。
5. vendor 的 full 推導本就可以因 SOC=100 且 external=true 而 full=true，consumer 失效／bootstrap 又會保留最後 full 值。因此 full=1、status unknown、time unavailable、甚至 charging flag 與 net discharge 並存，都必須分別判讀。**本輪沒有把 unknown/full 冒充 fault，沒有修改 production gate、sentinel 處理、快充策略或充電硬體。**

### 本輪實際驗證

`python tools/test-fuxi-charge-evidence.py` 與 `python -X dev tools/test-fuxi-charge-evidence.py` 各 **47 tests**。新增第14趟實際 log grammar fixtures、括號結尾 readback flags、bootstrap/routing/publication 區分、unknown/sentinel rejection、time bounds、full/charging/net-discharge 分欄、5g/9g completion、tail byte/hash/半行/staged-prefix 邊界。另以 CLI 實際解析第14趟完整 log 及 iter3 5g / 9g bounded tail。

尚未完成的物理拔線、快充／電表、coherent runtime freshness 與跨 alias／UI 验收維持前述判準。沒有重新跑 producer/consumer host tests、沒有新 native build，也沒有手機操作或 source commit。
