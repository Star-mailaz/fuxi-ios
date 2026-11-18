# Wi-Fi 自動加入：原生密碼查詢阻擋點

2026-11-17 16:21。這是現有實機紀錄的離線分析；沒有新增手機操作，Wi-Fi 自動加入尚未修好。

## 新證據

來源為 `work/statusbar-fix/inspect-wifi-autojoin-native-20261117-1536` 的 18 個已捕獲區塊。原摘要 SHA256 為 `39ae1c5cb95c4775bbde262f6e3af5d84055f6c9728f866d5e9782fb98a50c62`；原生日誌為 `/private/var/logs/wifimanager.log`，131646 bytes。

`inspect-wifi-autojoin-credential-final-cached-20261117-1627/powerlog-state.json` 的固定模板計數：

| 原生決策 | 次數 |
|---|---:|
| 一般密碼查詢返回 `-25300` | 22 |
| NonSyncable 密碼查詢返回 `-25300` | 22 |
| suitability 找不到密碼，返回 unsuitable | 22 |
| 因 missing-password 停用旗標而拒絕 | 0 |

NonSyncable 在此指鑰匙圈項目的可同步屬性；兩條實作本身都使用背景 queue 及有界等待。一般查詢設 `kSecAttrSynchronizableAny`，不能稱為只查可同步項目。

本次精準選取命中 124 行，敏感詞過濾隱藏 66 行，保留 58 行、沒有省略中段。密碼、帳戶值及鑰匙圈內容均未輸出；錯誤碼僅由兩個已核對的固定日誌模板擷取。

較早摘要會整行隱藏包含 password 的訊息，因此漏掉了這批拒絕原因。`redacted_sources` 現在只計數函式名稱，`credential_decisions` 只輸出固定分類與整數錯誤碼，不放寬敏感內容過濾。

## 同版程式核對

分析主機 `work/localbuild/wifi-daemon-20H392/wifid`，SHA256 `0ec6ad6ee120fb107510393c485a19ceaf54ef8dc7da479899a8cf7b93cdf871`，UUID `F0919F06-43C6-3723-AFF2-411233365292`。

- `__WiFiDeviceManagerKnownNetworkSuitabilityCheck` 的函式範圍為 `0x100109f78..0x10010aac4`；`0x10010aa14` 引用「No password found ... return as unsuitable」，經 `0x10010a148` 返回 false。「Priority Network with no RT traffic - ok to autojoin」沒有直接完成整個 suitability 函式。
- `0x1000bdb20..0x1000bdc60` 的一般查詢 block，在 `0x1000bdb68` 呼叫 `SecItemCopyMatching`，錯誤分支使用 `%s:[%@] Error result %d`。
- `0x1000bf180..0x1000bf34c` 的 NonSyncable 查詢 block，在 `0x1000bf25c` 呼叫同一 API，錯誤分支使用相同模板。
- 兩條查詢均使用 generic-password class、帳戶名、service `AirPort`、`kSecUseSystemKeychain=true` 與 return-data；一般查詢另外設 `kSecAttrSynchronizableAny`。此為同版 binary 的查詢結構，不輸出實機帳戶或密碼內容。
- `0x10012a62c..0x10012a910` 的掃描完成路徑會先轉換 scan records，再呼叫 `CWFFilteredScanResults`，最後執行完成 block。只能據此辨識流程，沒有 runtime 參數證據時不能宣稱這層丟掉全部結果。
- deferred manager 的「no scan results」在 `0x100153520` 檢查陣列 count 為零後輸出；NULL 陣列走另一個「scanResults NULL」訊息。這個訊息不證明底層沒有掃到 BSS。

目前實證支持先追密碼保存／查詢／移除；不再以同樣條件重跑掃描，也不清除使用者 Wi-Fi 設定。查詢沒有取得項目，不等於密碼錯誤、不等於從未成功保存，也不能排除查詢條件或後續移除的問題。

## 驗證

- `inspect-powerlog-state.py --self-test`：42 項檢查，包括敏感值不外洩、固定錯誤模板、32-bit 狀態界限、精準篩選與首尾保留。
- 主機重播核對來源摘要雜湊、禁止缺塊補讀、phone_operations=0、root overlay writes=0。
- `inspect-wifi-daemon.py` 新增辨識這份 Mach-O 的 Objective-C selector stubs；保留 xref 候選及 function-extent 的原有不確定性，不把靜態可見路徑當成實機已執行。
