# Battery poll pause：native 接線 source checkpoint

2026-11-16。承接主線已提交 `b6be873` 的獨立 helper 與 3538-assertion host checkpoint。本輪只修改 `xnu/fuxi-adsp/fuxi_adsp_battery.c`、`tools/sync-fuxi-adsp.py`、生成的 `xnu/patches/0117-fuxi-adsp.patch`、`tools/test-fuxi-battery-publication.py` 與本文件。不修改 charge parser、SweetBattery、freshness／pause helper、vendor codec、其他 lane canonical source。沒有手機／adb／fastboot／鎖操作、commit／push／branch。

這是 native source 接線與 host callback 驗證，不是 native XNU build 或實機拔線／TTL／快充驗收，也不宣稱某趟使用者事件的根因。

## Boot args 與 bounded 排程

- `fuxibatpause` 單位毫秒，default 0/off。主線要求的明示 opt-in 配置為 `fuxibatpause=130000`；可選 `fuxibatpausedelay`，預設 0、上限 60000。
- 兩個 arg 都讀進 uint64，再交已提交的 helper 驗證，避免先轉 uint32 而把巨大／負值截成合法小值。duration 上限 300000，非零 duration 下限 1000；實際 step 還要求 duration 至少 production TTL+1000。duration 不足、delay／duration 超界、clock／generation／channel／TTL 等 guard 失敗會取消診斷，正常 GET polling 繼續。
- production TTL 仍由 `fuxibatttl` 的原有 2000–3600000 毫秒 gate 或 90000 default 決定，沒有縮 TTL。若實際 TTL 不能被 300000 上限覆蓋，診斷拒絕，不調低 TTL。
- default 0 不 bind generation、不更新 helper clock、不 withholding、不打印新診斷。明示 duration 0 時，單獨的 delay 不會打開功能。
- bootstrap／partial baseline 時正常 polling；真 capacity、USB-online、status 都在當代且 fresh，並且無 request deadline、GET／SET 在途，才 arm。delay 期間仍正常 GET；到達安全 quiescent point 才開始單次 withholding，結束時間以真正 start 的 monotonic ms 計算。

## Native 接點

1. `fuxi_adsp_battery_start` 在原 TTL 配置之後初始化 `fb_pause`。不改 raw、最後成功值、codec mask、逐欄位成功時間、publisher sequence 或 charge firmware 配置。
2. `fbRun` 維持 channel／coalesced loss、RX ring 世代隔離、matched accepted GET observe、timeout／refresh 的原有次序；排空 RX 並處理 timers 後呼叫 `fbPauseStep(fbNowMs())`，再呼叫 `fbPump()`。
3. `fbPauseStep` 在 publication lock 下讀 freshness／worker generation，執行已提交的純排程 helper。channel loss／代際轉換取消已 arm／holding 的診斷，不能跨新代再次開始。bootstrap 尚未 bind 的 Waiting 不是 withholding。
4. `fbPump` 在原 channel／generation guard 後、`sheng_battmgr_next` 前攔所有下一筆 GET。既有 pending `limit_due` 或尚需送出的 keyboard SET 仍走原優先路徑；不在 codec next 已改 in-flight 後才丟封包。不取消既有请求、不改充電限流／設定、不攔 notification enable、不停 RX／timeout／refresh。
5. `wake_at_ms` 減本次 monotonic ms，做有界 uint32 remaining，再用原 `fbDeadline`／`clock_interval_to_deadline(ms, NSEC_PER_MSEC, ...)` 轉 absolute ticks，與 request／refresh ticks 取最早 deadline。已到期以 1ms wake；不能把毫秒直接和 mach ticks 比。remaining clamp 防轉窄溢位，真正 phase／clock guard 仍由下次 step 判定。
6. sync 新增 `fuxi_battery_poll_pause.h` 映射，生成路徑為 `bsd/dev/fuxi_battery_poll_pause.h`。header-only helper 不需要新 `.c` build-list entry；現有 freshness `.c` 的接線保留。

## 有界診斷與實驗資格

新 log 僅 `FUXI BATTERY: poll-pause start/end/cancel`。每 boot 的單次排程最多 start+end 或 start+cancel；開始前失敗只有 cancel。重複 callback 不重印。欄位包含 bound generation、當前 channel generation／up、`now_ms`、production TTL、duration、SOC／online／status ages 與 helper reason；這些只是讀取，不改成功時間。無當代樣本的 age 維持 UINT32_MAX。

任何真正匹配且 codec／語義 gate 接受的晚回覆仍正常 observe。測試驗證在名義 pause 時間之後、worker 排空 RX 時接受的 GET，沿用 ingress timestamp，再開始 withholding。開始時必須無在途 GET，因此 holding 期間沒有可接受的既有 GET；未匹配的重複回覆由原 codec 拒絕，不額外當作成功。現有 wire 無 token 的重試／跨重連歧義沒有新增解法。

130 秒配合 TTL90 秒提供約40秒過期觀察窗口；consumer 已接管後原本每30秒 polling，仍須計入 scheduler delay。只見 start/end 不代表所有欄位或 IORegistry 真已過期；需同代最後 accepted GET、逐欄位 age、unknown metadata 與 userland readback。新增 `now_ms` 可對齊診斷事件，不替代使用者物理插拔時間或充電器電表。

TTL withholding 實驗應保持物理 USB 連接，以正常非 staged 模式進行；過期後 external／charging 可以保留最後值，但 external-known／status-known、SOC／voltage／current／adapter-valid 必須失效。不要要求 unknown 偽造 external=0，也不要拿此實驗、staged57%、或 retained full 當物理拔線／fault／快充證據。真拔線另輪由使用者物理操作，再驗 accepted USB-online=0。

## Host 驗證

```powershell
python tools/test-fuxi-battery-publication.py
python tools/test-fuxi-battery-publication.py --sanitize
python tools/test-fuxi-battery-pause.py --sanitize
python tools/sync-fuxi-adsp.py --check
```

- production publication normal／MSVC ASan：各 **8820 checks**。原五個 production scenarios 與原24個 consumer structural checks保留；新增四個 callback scenarios，checks 含 host lock／send／property assertions，不是8820個獨立情境。
- 真 production producer C 直接 include；freshness `.c` 與 vendor codec 都是 production source。原 MSVC vendor array-designator temporary translation 與 enum 順序檢查保留，不改 canonical vendor。
- host clock 使用每 tick 250ns，milliseconds、nanoseconds 與 mach ticks 不相等；assert resume／delay deadline 經 interval conversion，最早 request／refresh deadline 不被新 timer 蓋掉。
- withholding callback 期間 GET count 不再增加；連續比較 producer 最後成功 values、codec raw values／valid mask、freshness mask／逐欄位 timestamps、cached publication，確認只是停止 GET。SET／notification／原 RX／timeout 仍執行。
- TTL90秒前、等號90000、過期120000、130000 resume／fresh recovery；保留最後97%／external／charging，不偽造拔線。另驗 bootstrap、default0、合法上下界、uint64超界、TTL不縮短、late accepted ingress、SET bypass、generation loss／coalesced up、clock rollback與TTL改變取消、event不重印。
- 測試從未修改的 SweetBattery source 精確抽出整個 `publishAdsp` 方法，編譯成 C++17，將真 producer accessor snapshot 餵入。實際執行方法中的 primary setters、AppleRaw、AdapterDetails、legacy、freshness properties 與 shared merge，核對它們的值／資格一致。IOKit allocator／dictionary／symbols／setters 是 host mocks，key constants與flag bits是mock符號；不是完整 SweetBattery class／IOKit ABI／registry／powerd／UI 執行。
- 已提交獨立 pause helper MSVC ASan仍通過 **3538 assertions**。MSVC C11／C++17均 `/W4 /WX`，assertions啟用；沒有本輪 UBSan／TSan 結果。
- `sync --check` 與 scoped `git diff --check` 通過；沒有 native XNU compile。

## 聚合 0117 邊界與主線交付

0117 generator 依當下所有 canonical source 再生。此次再生時另有並行 `fuxi_pmic.c` 的 haptic survey 改動，因此生成的0117也包含其內容；本 worker没有修改那份canonical或其他agent source，不會自行撤回／裁切它。主線應核對並行lane歸屬，使用同批commit snapshot整合；不能把整份0117 diff稱為純battery變更。若主線移動並行canonical或重生0117，需重新check／hash；下方hash只適用當時workspace snapshot。

本輪新增／改動檔案應同批帶上 producer、sync、生成0117、增補publication test與本文件；依賴已提交 `b6be873` header。下一批CI需native XNU／IOKit compile與整套host tests。手機的TTL unknown／aliases／UI、真拔線、快充／電表、sleep／resume、真並行callback race均未驗。本worker不啟動該物理階段。

## 最後驗證 snapshot SHA256

| 檔案 | SHA256 |
| --- | --- |
| `xnu/fuxi-adsp/fuxi_adsp_battery.c` | `6008710a2d2a9c3c64175dcf92dc2b9fe0a3264a8adb7cc88199c27e85e199e6` |
| `tools/sync-fuxi-adsp.py` | `f3cd63fc030289e6419091443737a7d208441115999ddefbae1616f88d504a87` |
| `xnu/patches/0117-fuxi-adsp.patch` | `017cf796ef7b47a064ffa50c9b52c12ca3e49035682b3d5c46729cae8767ff08` |
| `tools/test-fuxi-battery-publication.py` | `4c1b28d1c37c8d8f9506f92c7fb5e4a867a50dfbada35b33357eaef185f85946` |

依賴 pause header未變，SHA256=`393a0f7b7db7bd1f1ab1b955a37ecc62b30e49a616e9a18110480c4da6dcc368`。以上 hashes 由完成 normal／ASan與sync check之後的本機檔案重算；0117另含前述並行PMIC內容。
