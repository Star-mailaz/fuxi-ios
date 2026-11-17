# Battery publication：首個可測 production checkpoint

2026-11-16。承接使用者確認已收的 ksrc `51e7ca9` / harness `3c09708` freshness 研究 checkpoint。本輪修改 producer / consumer 的 stale 快取路徑與自己的 helper/test；不修改 vendor、`fuxi_adsp.c`、sync、build、聚合 patch，也未 commit / push / branch 或操作手機。

這是 source 根因修正與 host 驗證，不是對使用者某趟拔線事件的實機根因認定。前輪精確 source 缺口與當時來源 SHA256 記於 `docs-lanes/battery-freshness.md`；其中舊 production 行號只適用於前輪版本。

## 修改檔案

| 檔案 | 本輪內容 |
| --- | --- |
| `xnu/fuxi-adsp/fuxi_adsp_battery.c` | accepted GET 逐欄位成功時間、語義 gate、channel generation、RX 世代隔離、每次 read 重算 TTL、逐欄位立即發布 |
| `xnu/fuxi-adsp/fuxi_adsp_battery.h` | appended freshness ABI 與初輪 TTL 預設 |
| `xnu/fuxi-adsp/SweetBattery.cpp` | retained published values、ADSP 接管後不回 fake fallback、所有別名共用 retained snapshot、測量資格與 stale metadata |
| `xnu/fuxi-battery-prep/fuxi_battery_freshness.h` | flattened header 接線與共享 merge 宣告 |
| `xnu/fuxi-battery-prep/fuxi_battery_freshness.c` | production 共用 merge；初始化不依赖 host `string.h` |
| `xnu/fuxi-battery-prep/test_freshness.c` | 直接執行 production merge 的 bootstrap / partial / stale / recovery assertions |
| `tools/test-fuxi-battery-prep.py` | helper 的 ADSP header 搜尋路徑 |
| `tools/test-fuxi-battery-publication.py` | 直接 include production producer C，搭配原 codec 與 host callback / clock / lock model |
| `docs-lanes/battery-publication-checkpoint.md` | 本文件 |

## 已實作的資格與保留策略

### Producer

- `fbState` 在 publication lock 中更新 channel up / generation；down 立即清除 observed mask，reader 不需等 worker 才看到失效。RX ring 同時清理，coalesced down/up 仍觸發 codec / request reset。
- `fbReceive` 保存本地 channel generation 與 callback 收到資料時的毫秒時間。worker 拒絕不屬於當前 channel / worker generation 的 ring entry。
- `fbRun` 先保存 in-flight field 與 request generation，再執行 `sheng_battmgr_receive`。只有 codec 的 responses 計數前進、該 field 的 valid bit 成功、語義 gate 接受且 generation 匹配，才 observe。send refused 不取得有效 request generation。
- notification、錯誤、timeout、cycle done 與新 SOC 本身都不替其他 field 延長 TTL。codec 原有 sticky `charge_known` 不直接用於 publication；臨時 snapshot 的 valid mask 改為當代 fresh fields，raw 值來自獨立的最後成功資料陣列。
- 每個 accepted GET 都可觸發 `fbPublish`，不再等完整 cycle 或整包 SOC plausible gate。成功 USB-online=0 即使 SOC 已過期或新 SOC 被拒絕，仍更新 external=false / charging=false / full=false，清 adapter details；channel loss 或 TTL 不會推導拔線。
- `fuxi_adsp_battery_reading` 在每次讀取時重算資格。publish mode 已啟用時返回 metadata，包括 sequence=0 的 bootstrap 和 stale；返回值不再代表「整包測量有效」，consumer 必須看欄位資格。
- SOC 採既有 firmware hundredths-percent 與至少 1% 的發布政策。GET 語義 gate 接受 capacity 0–10000、battery voltage 2500000–4800000 µV、temperature −4000–9000、status 1–4、present / online 0–1；current 排除會造成 codec 取負溢位的 INT32_MIN。其他非負值仍由既有 codec 換算。本輪沒有加入 opcode、property 或充電設定。
- 初輪 `FUXI_BATTERY_DEFAULT_MAX_AGE_MS=90000`，可用 boot arg `fuxibatttl`（毫秒，接受 2000–3600000）覆蓋。90 秒不是已完成實機校準的需求值。年齡等於 TTL 就過期；無當代樣本的 age 是 uint32 最大值。

### Consumer

- `fAdspLast` 保存最後已發布的值，producer 與 consumer 共用 `fuxi_battery_prep_merge`。只有符合 incoming 資格的欄位覆蓋；其他值保留，資格則每次更新。SOC、電壓、電流、溫度、raw / full / design、cycles、時間與 adapter components 分別 gate。
- 首次尚無 ADSP 成功值時保留原先 100% / 4200 mV / external / full / 25°C 的 bootstrap 相容值，明確為 fallback / estimated、未知且 stale；不宣稱這些是測量。非零 publication sequence 使接管狀態 sticky；實測 SOC / temperature 曾經顯示後，過期不會把其 provenance 改標為 estimated。
- `poll` 在 ADSP wanted 或已接管時始終處理 ADSP 分支並 return，失效不會進入 fake100 / external / full 的 SPMI fallback。timer 建立失敗也保留 ADSP routing，直接发布 retained values + unknown validity，不留下當下 fresh 標誌假裝能繼續定時維護。
- primary setters、AppleRawExternalConnected、FullyCharged、AdapterDetails、legacy charger / charge flags 均取同一 retained `b`。資料失效時可保留最後 charger-connected / charging 值，但 external-known / status-known=false；不把未知偷換成 unplugged。cycles=0 也同步 primary 與 legacy，避免一邊仍保留舊正值。
- `SweetBatteryHardwareSampleValid` 要求 SOC 與 voltage fresh；current validity 獨立，temperature estimated 與曾經測量的 provenance 分開。新增 `FuxiBatterySourceStale`、SOC / voltage / present / raw-capacity / adapter validity、external / status known、channel up、fresh mask、核心欄位 age 與 max-age。
- `TimeRemaining` 只在所需時間 field 與 charger status 有資格時有效，否則 −1。成功 online=0 本身足以知道不充電，所以不要求另一次 status 成功才呈現真拔線。
- consumer 常態 30 秒 poll，TTL metadata / UI 通知更新因此可能落後 TTL 邊界最多一個正常 poll 間隔再加排程延遲；producer accessor 的 fresh mask 仍在每次 read 精確重算。down 的 producer invalidation 是立即的，IORegistry 發布不是同步 callback 即時刷新。

## 實際驗證

在 `D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc` 執行：

```powershell
python tools/test-fuxi-battery-prep.py
python tools/test-fuxi-battery-prep.py --sanitize
python tools/test-fuxi-battery-publication.py
python tools/test-fuxi-battery-publication.py --sanitize
```

- helper normal / ASan：`PASS fuxi-battery-prep freshness: 1848 checks`。
- production publication normal / ASan：`PASS fuxi-battery production publication: 1882 checks`。
- consumer source wiring：24 structural checks；是文字結構回歸檢查，不是 IOKit 執行或 native compile。
- MSVC 14.50.35717，C11 `/W4 /WX`，assertions 保持啟用；sanitize 使用 AddressSanitizer。沒有 UBSan / TSan 結果。checks 數含 mock lock / send ownership assertions，不等於獨立 scenario 數。
- harness 編譯實際 production producer C、實際 production freshness / merge helper 及 vendor codec。MSVC 不支援 vendor table 的 C array designators，工具先驗證全部 32 個 designators 和 enum 順序完全一致，再只在 temporary copy 去除 designators；vendor canonical 檔沒有修改。
- 覆蓋 capacity 持續成功但 online / status timeout、停流精確 TTL、partial 真拔線、bad SOC / voltage、錯誤 reply、notification、property mismatch、send refused、立即 loss、coalesced down/up、late 舊 ring generation、generation recovery、首次無 ADSP 資料、consumer 保留值、adapter partial update、可配置 TTL、失敗 refresh 不延長前次成功時間、延後 worker 使用 ingress 時間而非 decode 時间。
- 直接 merge 測試涵蓋無資格的 fake100 / full 等 incoming 值不能覆蓋接管後真值；consumer alias / return-before-fallback / timer-unavailable 接線另以結構檢查確認。

Vendor 保護：本輪重算 SHA256，`ShengBattmgr.h` 仍為 `bb652fc1d23ccebcc08b86228fc895c73cec38238bdbc55b6f08ff7975ab6d3d`；codec C 仍為前輪的 `12f25e0ca84164fe060c63161c6e9a3908742451cfb09ccd114cfe047130727e`。

## 主線精確 sync 接線（本 worker 未執行）

`tools/sync-fuxi-adsp.py` 的 `SOURCES` / `HEADERS` 已包含 producer / ABI；`MODIFIED` 已把 `xnu/fuxi-adsp/SweetBattery.cpp` 接到 `iokit/Kernel/arm/SweetBattery.cpp`。缺少新的 shared helper。

主線在現有 `SOURCE_PATHS` 定義之後、`FILES = SOURCES + HEADERS` 計算之前，加入等價接線，保留其他 lane 的映射：

```python
SOURCES += ('fuxi_battery_freshness.c',)
HEADERS += ('fuxi_battery_freshness.h',)
SOURCE_PATHS.update({
    'fuxi_battery_freshness.c': ROOT / 'xnu/fuxi-battery-prep/fuxi_battery_freshness.c',
    'fuxi_battery_freshness.h': ROOT / 'xnu/fuxi-battery-prep/fuxi_battery_freshness.h',
})
```

結果应為 `bsd/dev/fuxi_battery_freshness.c` / `.h`，並由現有 `build_list_hunk` 自動增加 `bsd/conf/files` standard source entry。helper header 使用同目錄的 `ShengBattmgr.h` / `fuxi_adsp_battery.h`；SweetBattery 使用 `../../../bsd/dev/fuxi_battery_freshness.h`。務必同一批帶上 appended ABI、producer、consumer 及 helper，避免未定義符號或 struct layout 不一致。

主線再生成 / check `0117-fuxi-adsp.patch`，下一個 CI snapshot 做 native XNU / IOKit build。新兩支 host tools 可加入該批 host validation；本 worker 未改 harness CI、sync 或 build，workspace 聚合 patch 尚未包含這次修正。

## 未驗界限與下一階段條件

1. 沒有 native XNU / IOKit compile、真多執行緒 lock / callback 驗證、powerd / SpringBoard / legacy API 執行、手機真拔線 / 再插線或充電硬體驗證。host kernel headers、clock、thread-call、transport、locks 是模型；ASan 不證明 kernel concurrency。
2. generation 保證本地舊 ring / pending request 不會跨代 observe。現有 wire GET reply 只有 opcode / property / value / result，沒有 request token；若重連或 timeout 重試後物理晚到的 reply 和新請求 opcode / property 完全一樣、且到達時已在新代，wrapper 無法可靠識別。本輪不宣稱解決這個 wire 層歧義；需要 transport 保證舊資料已排空或另有可驗證的 session 關聯。
3. producer `fbLog` 仍是 vendor cycle 的診斷 view，可能顯示 sticky charger mask。實際發布資格以 accessor metadata、SweetBattery unknown / stale 記錄和 IORegistry 為準，不能單用舊 cycle log 證明 freshness。
4. producer 無 down callback 的停流會在 read 時 TTL 過期。`fuxi_adsp.c` 的 fatal → battery channel invalidation 不在本 write set；sleep 期間 monotonic clock 的行為與 consumer 恢復 poll 尚待驗。timer 已建立但後來不再回呼時，IORegistry metadata 不會自行刷新，需主線驗證 timer / resume 正常運作。
5. UI 是否會採用新增 unknown / validity properties 尚未驗；沒有新實測 online=0 時，charger icon 保留最後已知 connected 是允許結果，不是偽造拔線。若 producer 新歷史值在 consumer 第一次讀到前已過期，本輪 merge 保留 consumer 先前顯示值，不補發從未顯示過的過期歷史值。
6. 下一階段由主線先完成 native build，再以正常非 staged boot 驗收：成功 online=0 + 壞 SOC / status timeout 的拔線、online / status 單獨停流、全停流、channel down/up、真值 recovery，以及 primary / AppleRaw / AdapterDetails / legacy flags 一致。應同時收 accepted GET、generation、fresh mask / ages、SweetBattery 發布與 userland 讀取證據。

本輪不調快充限流或功放、不操作硬體，不把 ADSP / 功放 ID 已通視為音訊完成。
