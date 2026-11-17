# Fuxi battmgr freshness 首輪 checkpoint

2026-11-16，唯讀審查 `work/adsp-battery/ksrc/xnu/fuxi-adsp/` 的既有 producer、codec 與 SweetBattery consumer。本輪新增純 host freshness helper/test，結論根據下列來源版本。原先使用者拔線那趟的因果仍需該趟 boot mode、channel、成功 USB-online/status 回覆與發布記錄核對。

## 1. 已確認的 source 缺口

### 發布值缺少 channel 與年齡判斷

`fuxi_adsp_battery.c` 第 130–133 行在 `fb_pub_lock` 下遞增 sequence 並替換 `fb_pub`。第 146–153 行的 reading accessor 只檢查 `fb_publish` 與 `fb_pub.sequence != 0`，隨後交出整個舊 snapshot。這個路徑沒有成功取樣時間、每欄位年齡、channel-up 或 generation 檢查。

第 55–61 行的 `fbState(..., up=0)` 設定 `fb_lost`、`fb_up=0` 並排入 worker。第 234–240 行的 loss branch 清除 request deadline、初始化 `fb_bm`、重設 `fb_was_up`，發布快取 `fb_pub` 仍保留。若之前已有 sequence，consumer 可以一直得到前次 100%/external=1 的 snapshot。

`SweetBattery.cpp` 第 355–362 行只要 accessor 成功就呼叫 `publishAdsp()` 並 return。第 309–315 行把該讀值標為 hardware-valid、current-valid、fallback=false。第 411 行在首筆 ADSP 顯示後維持 30 秒 poll，每次都可重複發布同一個過期 snapshot。

### 新 sequence 也可能攜帶過期 charger 欄位

`ShengBattmgr.h` 第 44–45 行保存 `valid` 與 sticky `charge_known` mask。`ShengBattmgr.c` 第 98–106 行開始 refresh 時保留既有欄位值與 mask。第 173–182 行 timeout 清除該欄位的 `valid`，第 221–227 行錯誤回覆也清 `valid`，成功回覆則把 status/USB-online bit 累積到 `charge_known`。

第 247–255 行 snapshot 的 `HAS(f)` 使用 `valid | charge_known`。成功的 status/USB-online 因此在後續 timeout/error 後仍會是 known，沒有 TTL。第 261 行的 `s->charge_known` 是 SOC 可計算性的判準，與 struct 中 sticky charger mask 的用途各自獨立。

具體可達的序列為 status=charging、USB-online=1 成功 → 後續 status/USB-online 一直 timeout → capacity 持續成功 → snapshot 仍為 external-known/status-known → `fbPublish()` 因 SOC 合理而遞增 sequence。僅在 `fb_pub` 加一個整包發布時間無法衡量這些欄位各自的成功取樣年齡。

### Implausible cycle 保留舊發布值

`fuxi_adsp_battery.c` 第 99–108 行遇到 charge unknown、百分比不合理或已讀電壓不合理會直接 return，舊 `fb_pub` 繼續有效。第 216 行的 publication 又只在 `fbLog()` 執行，而第 263–271 行通常等到整個 cycle 完成或最後一個 timeout。

因此真實 USB-online=0 即使已被 codec 接受，若該 cycle 的 SOC/電壓使整包發布被拒絕，charger 更新仍可能被擋住。全慢速 cycle 有 32 個欄位、每 request deadline 2 秒，timeout 串連的週期耗時可接近 64 秒，還需計入排程與其他 request。

### Fallback 的精確值

`SweetBattery.cpp` 第 366–379 行在 `fReal` 沒開啟或 SPMI sample 無效時執行以下呼叫。

```cpp
publish(100, 4200, 0, true, true, false, true, false, false);
```

依第 144–145 行參數順序，這是 percent=100、external=true、capable=true、charging=false、full=true、measured=false、currentValid=false。第 152–163 行確實寫入 ExternalConnected、IsCharging、FullyCharged 與 AppleRawExternalConnected。回落會覆蓋先前真實 SOC/charger 值，而 charging 的具體值是 false。

目前 stale accessor 持續成功時會走 ADSP 分支。若只把 accessor 改成 stale 時返回 0，consumer 下一步就會進入這個 fallback，所以 producer 與 consumer 必須一起修正。

### Legacy flags 需要相同 known 判斷

`SweetBattery.cpp` 第 261–268 行的主要 setters 有 `external_known` / `status_known` gate，但第 322–323 行 legacy dictionary 的 charger/charge flags 直接取 `b.external` / `b.charging`。Codec 在 unknown 時把 external 算成 0，legacy 路徑可能寫出與主要屬性不同的 charger flags。過期/失效修正需要涵蓋所有這些別名。

## 2. 成功真拔線的既有路徑

`ShengBattmgr.c` 第 217–227 行接受符合當前 in-flight opcode/property 的成功回覆，USB property 0 的 value=0 會寫入 `value[BmUsbOnline]`。第 253–264 行 snapshot 會得到 external-known=true、external=false、charging=false、fully-charged=false。

Fuxi 的 `fbBoard()` 第 177–183 行依 firmware capacity 作 SOC 修正，full 仍取決於 external。若整包通過 `fbPublish()`，SweetBattery 的主要 setters 會收到已知拔線狀態。這條路徑在 source 中可達。原趟是否收到並接受這個回覆、是否完成 cycle 與通過發布條件，需要原趟記錄確認。

## 3. 最小修正提案

### Producer 與 codec 接點

1. 在現有 `fb_pub_lock` 保護的 state 增加 channel generation/up、每欄位最後一次成功取樣時間與 fresh mask。Down callback 立即令發布來源失效，worker 處理 coalesced down/up 時先做 down invalidation，再開始新的 generation。Reader 在同一 lock 中取得 snapshot、validity 與 timestamps。
2. 使用 codec 已驗證的單筆 GET 回覆作 timestamp 更新點。先保存 `fb_bm.cursor` / in-flight 與 request generation，呼叫 `sheng_battmgr_receive()`，確認回覆真的被接受且該 field 結果成功、value 語義合理後，才更新該欄位時間。Notification、cycle 完成、錯誤與 timeout 均不更新成功時間。
3. 初輪可在 fuxi wrapper 保存 freshness metadata，重用既有 codec。Reader 以每欄位成功時間 gate sticky charger bit，並按 fresh mask 判斷 SOC/status/online 的更新資格。
4. 成功 USB-online 回覆獨立於整包 SOC plausible gate 更新 charger state，讓有效拔線能在壞 SOC 或長 cycle 中繼續發布。成功 online=0 足以設定 external=false、charging=false、full=false。成功 online=1 時 charging/full 依各自規則所需的新鮮 status/SOC 資料推導。
5. RX ring message 與 request 帶 local generation，worker 濾掉舊 generation。Loss 時清理/隔離 ring 與 pending request。現有 wire 回覆依 opcode/property 匹配，缺少 request token，重開與 timeout 重試仍需明確約束晚到回覆的處理。

### SweetBattery 接點

ADSP 已接管後，在 `poll()` 的 ADSP 分支分別處理 fresh、partial 與 unavailable，處理後 return。失效時保留最後已知 capacity/charger 屬性，發布 source-valid=false、external-known/status-known=false、age 與失效原因，time-remaining 設為 unknown，current-valid 等測量標誌按 fresh mask 更新。這個分支使舊資料以其實際有效性呈現。

初次尚未收到 ADSP 值時，現有 bootstrap 表示仍需明確標為 fallback/estimated。恢復後逐欄位發佈新鮮值。30 秒 consumer poll 要持續評估 TTL，producer 失去 callback 或停止排程時也能過期。Source validity 改變時呼叫 `updateStatus()`。

主要 setters、AppleRawExternalConnected、AdapterDetails、FullyCharged 與 legacy flags 必須使用同一份已知且已發布的值。資料失效不提供拔線證據，external=false 的更新由成功 online=0 或另外已驗證的物理資料來源支持。

TTL 首輪測試採可配置的 90,000 ms，這是提案選值。實際值應以成功回覆節奏、最長 timeout cycle、consumer poll 與容許資料年齡校準。UI 對新增 validity 屬性的消費行為仍需 powerd/SpringBoard 驗收，最後已知 charger icon 的呈現可能持續到新實測值抵達。

### 與 ADSP fatal 的關係

`fuxi_adsp.c` 第 522–529 行對 SMP2P fatal 讀 crash reason，這段未把 battery channel 標成 down。Freshness 的定時失效能涵蓋無 down callback 的停流情況。Fatal→client invalidation 是後續整合的明確接點。

## 4. 新增純 host helper

新增 `xnu/fuxi-battery-prep/fuxi_battery_freshness.{h,c}`。重用既有 `ShengBattmgr.h` 的 field enum，保存 successful-at-ms 與 generation，僅回傳 `fresh_fields`、update-capacity、update-external、update-charging 資格。helper 的資料結構沒有 percent、external 或 charging 的值。

- Channel down 清除當代 observed mask，down/up generation 使舊事件無法重新有效。
- 成功且匹配 generation 的欄位才更新時間，error/timeout 的 observe 不延長 TTL。
- 年齡到 TTL 邊界即過期，對 clock 回退/future timestamps 回傳不新鮮，避免 unsigned 下溢。
- Capacity、online、status 的年齡獨立，新的 SOC 不替舊 online/status 延期。
- 成功 online=0 的 consumer 模型在 capacity unknown 時仍更新拔線，失效模式保留最後已知值。
- Caller 保證鎖定、value 驗證、accepted-reply 與 generation 標記的正確性。helper 本身沒有 kernel callbacks 或測量內容。

## 5. 驗證與交付範圍

```powershell
python work/adsp-battery/ksrc/tools/test-fuxi-battery-prep.py
python work/adsp-battery/ksrc/tools/test-fuxi-battery-prep.py --sanitize
```

兩輪都通過 `PASS fuxi-battery-prep freshness: 1805 checks`。MSVC 14.50、C11 `/W4 /WX`，sanitize 輪使用 AddressSanitizer。Compiler discovery 重用既有 audio-prep 測試工具。UBSan、kernel integration 與 powerd/UI 行為尚待驗證。

覆蓋初始無值、channel loss、coalesced down/up、舊 generation、持續 SOC 更新但 charger timeout、精確 TTL、全部 32 欄位、partial 真拔線、保留最後已知值、clock rollback、64-bit 邊界與參數錯誤。既有 producer/codec/consumer 的判斷來自唯讀 source 審查，host executable 驗證新增 helper 與 consumer 策略模型。

新增五個檔案為此文件、`fuxi_battery_freshness.h`、`fuxi_battery_freshness.c`、`test_freshness.c` 與 `tools/test-fuxi-battery-prep.py`。

## 6. 審查版本

| 既有來源 | 審查時 SHA256 |
| --- | --- |
| `xnu/fuxi-adsp/fuxi_adsp_battery.c` | `aebe2ca03fd93f0535bae4c709a2a43f1b83e532c391a278e5c263d955254e20` |
| `xnu/fuxi-adsp/SweetBattery.cpp` | `8af583bea96e769e815aca42d849a0a741ebbbcfb4ec6824ad6456ea04f160d7` |
| `xnu/fuxi-adsp/ShengBattmgr.c` | `12f25e0ca84164fe060c63161c6e9a3908742451cfb09ccd114cfe047130727e` |
| `xnu/fuxi-adsp/ShengBattmgr.h` | `bb652fc1d23ccebcc08b86228fc895c73cec38238bdbc55b6f08ff7975ab6d3d` |

此 checkpoint 支持立即規劃 producer/consumer 的一組小修正。Host helper 的資格判斷已驗證，下一階段由主線整合既有 production 接點並驗收真拔線、停流、失效、重連與 UI。
