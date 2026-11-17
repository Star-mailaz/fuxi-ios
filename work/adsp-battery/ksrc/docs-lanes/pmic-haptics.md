# Fuxi iOS 16 HAP525 diagnostic

## 本次可同步版本

Canonical sources 已可供主代理同步。本次 boot 入口採唯讀診斷。
`/chosen` 的 32-bit `fuxi,haptic=1` 或 boot arg `fuxihaptic=1` 啟用一次檢查。
Boot arg 存在時優先於 device-tree property，包括明確指定零的情況。
兩個入口皆缺省時 haptic 診斷關閉。此開關獨立於 `fuxi,pmic`，可與既有
PMIC mode 3 及 RAM mode 2 同一版本整合。

正常的已知 survey 預期得到以下紀錄。

```text
FUXI PMIC: haptic diagnostic begin PATTERN1 finite-bound-verified=0
FUXI PMIC: haptic result=-11 probed=1 TLRA=5710us start-attempted=0 started=0 stopped=0 restored=0 locked=1
FUXI PMIC: haptic probe accepted HAP525/owner/fault/idle/follow; PATTERN1 autonomous stop unverified; writes=0
```

`probed=1` 表示硬體識別、ownership、fault、idle、boost follow、校準週期與
保存值的一致性均通過。`-11` 表示 PATTERN1 自行停止的有限性仍待確認，入口在
第一次寫入之前返回。此分支僅使用 observer read channel，haptic write channel
保持未映射。`locked=1` 是本次診斷的單次拒絕鎖存。

## 語義依據與尚待確認事項

本次檢查使用 `work/adsp-battery/ref-linux/qcom-hv-haptics-9671bc.c` 對應的
Android msm commit `9671bc00773d7f73172f1cf38a7cd638091d0214`。

該 driver 的 `haptics_get_revision` 以 config 與 pattern revision 4 識別
HAP525_HV。`haptics_set_pattern` 的 PATTERN1 使用 pattern offsets 0x30/0x31
設定週期，0x34..0x4b 保存八筆三 byte sample。Sample 依序包含 period 與
frequency-doubling、amplitude MSB、amplitude LSB。Source enum 的 PATTERN1
值為 2。`haptics_enable_play` 在 config 0x4c 設置 bit 7 開始播放，清除此位
停止播放。`haptics_wait_brake_complete` 以 config 0x0b bits 1..0 等於零
確認 HPWR_DISABLED。

`haptics_parse_effect_pattern_data` 明確限制八筆容量。該限制本身不足以證明
PLAY_EN 保持設定且 SPMI 失聯時，硬體一定於八筆後自行停止。
`haptics_measure_realtime_lra_impedance` 的單週期範例仍在 sleep 後送出軟體
停止命令。`get_pattern_play_length_us` 的迴圈上限為 `j < i`，其估算也未提供
硬體獨立停止的保證。因此 production adapter 的
`pattern1_finite_verified` 固定為零。

後續需要確認 HAP525_HV PATTERN1 在 PLAY_EN 未清除時的重播與結束行為，
以及相關 auto-shutdown/外部觸發設定。可採用明確的硬體文件或可追溯的
對應實作證據。既有 0x4a=0x84 與 0x4d=0xc8 僅有 survey 值，本版保留這些值。
Host 模型中的有限播放是測試前提。完整 kernel build 與實機紀錄仍由主代理完成。

## Production helper 與預備脈衝

`xnu/fuxi-adsp/fuxi_haptic_pulse.h` 可直接抽出為 host C 編譯單元。
I/O adapter 提供 ownership、register read/write 與 wait callbacks。
每次 checked write 會重新確認 owner，SPMI adapter 也再次驗證 owner、APID、
poison 狀態與映射位置。Write allowlist 限於 SID 7 owner-0 config 0x46、
0x48、0x4b、0x4c、0x4e、0x63，以及 owner-0 pattern 0x30、0x31、0x34..0x4b。

Probe 接受 config revision/type/subtype 04/15/0a、pattern 04/15/0b、
boost revision 0002/type/subtype 31/01，以及 owner 0/0/3。Boost 0x41 bits
7/6/5 必須全部設定，分別為 HW_EN、HW_CCM、HW_VSET。Boost 0x46 bit 7 與
0x0b bit 0 必須為零。Config fault 必須為零，HPWR_DISABLED 與 PLAY_EN 清除，
0x68 force-ready/ack bits 清除，0x49 採 sine/2's-complement 格式。
Identity、校準與保存值均重讀確認，整份 snapshot 後再次確認 idle。

預備的寫入分支只有在 I/O contract 已確認 PATTERN1 硬體有限性時才可執行。
其順序為 module disable、PATTERN1 stop、SWR ignore/input gate、VMAX 1200 mV、
短效果 autores disable，以及八筆完整 pattern 的寫入與讀回。
前四筆 amplitude 為 64，後四筆為零，每筆採 T_LRA、frequency-doubling 關閉。
Config 0x5c/0x5d 的校準值保持原值，僅將相同週期放入 PATTERN1 的週期欄位。
VMAX 診斷值為 24 × 50 mV。硬體 waveform 是 9-bit signed 格式，64 是正向
低幅 sample code，實際位移與觸感需要實測。

啟動前重讀全部 staged registers 並再次驗證 fault/idle/follow。
SPMI_PLAY 僅以 0x82 啟動一次。等待涵蓋完整八筆週期與 10 ms margin。
對目前 TLRA 5710 us，四筆非零 sample 的名義長度為 22.84 ms，完整八筆
觀察區間為 45.68 ms。Stop 同時送出 0x4c=2 與 module disable，至多以
20 次 1 ms poll 驗證兩個 command 值及 HPWR_DISABLED。

只有停止得到確認才還原。Payload 先在 module 關閉時還原，再還原 voltage、
autores、原始 off PLAY、SWR gates，最後還原 module enable。原始 survey
VMAX 0x1c 代表 1400 mV，該原值只會在已確認停止且 module 關閉時還原。
停止無法確認時，保留已驗證的低幅 PATTERN1、1200 mV 與 SWR gates，
等待有限模型的完整區間後鎖存拒絕重試。Restore 錯誤會再次停止並鎖存。
APID timeout 會沿用 PMIC transport 的 poisoned-channel 機制。

## 主代理 sync/build 整合

1. 將 `fuxi_haptic_pulse.h` 加入 `tools/sync-fuxi-adsp.py` 的 `HEADERS`。
2. 用既有流程執行 `python tools/sync-fuxi-adsp.py`，再執行相同命令的 `--check`。
   `fuxi_pmic.c` 已列於 `SOURCES`，build-list 可沿用既有項目。
3. CI 加入 `CC=clang python tools/test-fuxi-haptic-pulse.py`。
4. CI 加入 `CC=clang python tools/test-fuxi-haptic-pulse.py --syntax-only`，再執行
   正常 iOS 16 XNU build。
5. RAM+haptic 的短測 loader 增加 `/chosen/fuxi,haptic` 的 32-bit 值 1。
   收集 `haptic result` 與 `haptic probe accepted` 紀錄，確認 `start-attempted=0`
   及 `writes=0`。手機、loader、CI 與提交整合由主代理處理。

## 本地驗證

Windows MSVC 14.50 以 C11、`/W4 /WX` 編譯並執行 production-helper fault model。
涵蓋 231 個成功路徑 read 點、68 個 write 點、71 個 ownership 點，以及
write 丟失、read corruption、write 已落地但回報錯誤、APID quarantine、
停止命令丟失、HPWR 卡住、停止讀取失敗、owner 變化、保存值與還原、錯誤鎖存。
唯讀 production gate 另外確認相同硬體 fixture 上完整 registers 保持一致、
write count 與 start count 均為零。

Android NDK 26.1.10909125 clang 通過 helper 的
`arm64-apple-darwin -ffreestanding -std=c11 -Wall -Wextra -Werror -fsyntax-only`。
ASan/UBSan host 執行與完整 `fuxi_pmic.c` 的 XNU 編譯仍待 CI。
本輪交付涵蓋 boot 診斷與可抽出的預備序列，iOS UI 觸覺 hook 待後續整合。

## Mode1 FIFO 純唯讀擴充 checkpoint

實際 owning path 為 `xnu/fuxi-adsp/fuxi_pmic.c`，與 torch 共用。
本次僅新增 `fp_haptic_fifo_observe`、`fp_haptic_fifo_survey`，及 init 中一個
呼叫點。Torch／新 raw 診斷／PATTERN1 分支與原有 generic survey 保持原樣。
不接 FIFO preparation active 分支、不改已提交的 FIFO C/header/tests。

新 survey 只在 `fuxipmic=1` 或 `/chosen/fuxi,pmic` 的 32-bit 值為 1 時執行。
單純收資料可省略 `fuxihaptic`／`fuxi,haptic`。預設兩個開關為零時，不 map、
不讀 PMIC；mode2／mode3 不執行這個新 survey，既有行為保持原樣。

每輪依序讀取以下 SID7 地址，總共兩輪：

- CFG：`0x70/0x71` selector，`0x0b/0x0c/0x46/0x48/0x49/0x4a/0x4b/
  0x4c/0x4d/0x4e/0x5c/0x5d/0x63/0x68/0x72`，以及 `0x01/0x04/0x05` 身分。
- PTN：`0x24/0x2a/0x2d/0xa0`，以及 `0x01/0x04/0x05` 身分。
- 每輪結尾再讀 CFG `0x70/0x71`，驗證讀取前後 selector 未變。
- 僅在本輪身分匹配 HAP525 CFG `04/15/0a`、PTN `04/15/0b`，且現有
  selector 已是 `0x70=5/0x71=0x80` 時，才額外讀 `0x09/0x0a`。不寫 mux。

額外 survey 最多 62 次 byte-read attempts、124 次 owner/APID 查詢；
不包含原有 generic survey。每個 attempt 都記錄 round、地址、前後 APID、
前後 owner、raw value、實際 read rc 與 validity。只讀 owner0 CFG/PTN，
owner 不符、APID 改變或 channel poisoned 時拒絕有效資料。Skipped read
記 `rc=-1 valid=0`；read 成功但 owner/APID 後驗不符記 `rc=0 valid=0`。
這些零值不能當成成功的寄存器讀值。

新函式不讀 FIFO enqueue ports、不讀／寫 owner3、不 clear fault、不 flush、
不寫 voltage／hold／SWR／PLAY_EN、不 start／stop／restore。`writes=0`
是 PMIC peripheral register writes；既有 `fp_read` 的 observer command
MMIO 操作仍是讀取傳輸所需，並非驅動器寄存器寫入。既有 APID timeout
quarantine 沿用，不重試被 poisoned 的 channel。

`valid` 只代表本輪 read 與 owner/APID/selector 觀察有效；`stable` 只比較
兩輪已採樣的值，並非原子快照或安全 active preflight。Fault、busy 或不同
clock/rate profile 的 raw 值仍會保留供主代理判讀，不能因 `valid=1` 就接受
為可播放配置。HAP525 身分不匹配時，不解 TLRA／FIFO status。
FIFO flags 矛盾或 fill 超容量時記 `FIFO-status=contradictory`、`valid=0`。
FIFO status 不可用時不宣稱 fill=0；相關數值欄位必須配合 status label 解讀。

驗收本趟資料應見兩輪逐筆 `rc=0 valid=1 owner=0/0`、前後相同 APID，
end 為 `rounds=2 valid=1 stable=1 identity-valid=1`，且固定
`active-gate=0 start-attempted=0 writes=0 cutoff-verified=0 route-verified=0`。
另外檢查 fault=0、HPWR bits1:0=0、PLAY_EN bit7=0；busy／fault／profile fork
不能當成安全 idle 配置。這仍不證 FIFO 自主截止、0x4a bit7 或 EXT_TRIG。

新增 `tools/test-fuxi-haptic-survey.py` 從實際 PMIC C 抽出新函式及完整 init，
測 bootarg／DT 預設關閉、mode1 啟用、one-shot、58 read 故障點、116 個 owner
及 APID 變化點、selector race、timeout quarantine、假 empty／矛盾 flags、
身分不匹配，以及 mode2/mode3 既有 dispatch 不變。這是輕量 host transport
stub，不是新 actuator／自主截止模型。腳本重用已提交 FIFO runner 的 compiler
與 MSVC environment 探測，不修改該 runner。

```text
python tools/test-fuxi-haptic-survey.py
python tools/test-fuxi-haptic-survey.py --cc clang --syntax-only
```

本機 MSVC 14.50 `/std:c11 /W4 /WX` assertions 與 NDK 26.1 clang 的
`arm64-apple-darwin -ffreestanding -mgeneral-regs-only` 新 survey 函式語法
檢查通過。ASan/UBSan 與完整 XNU PMIC 編譯仍由主線 CI 驗證。
未操作手機，沒有本擴充的新實機結果。

只交 canonical C、自己的 host test 與本文件。Workspace 沒有獨立 C mirror；
`0117` 為生成來源，由主代理／Bacon 統一 sync。本次不改 sync／0117，
不新增 HEADERS 或 build-list 項目；`fuxi_pmic.c` 已在既有 SOURCES 中。
