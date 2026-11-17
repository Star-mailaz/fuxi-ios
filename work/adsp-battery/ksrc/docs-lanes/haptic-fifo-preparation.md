# HAP525 FIFO preparation：純 host 編碼與唯讀拒絕 gate

## Checkpoint 與邊界

本 checkpoint 新增 `xnu/fuxi-haptic-prep/fuxi_haptic_fifo.h`、
`fuxi_haptic_fifo.c`、`test_fifo.c`、`tools/test-fuxi-haptic-fifo.py` 與本文件。
不修改既有 PMIC、PATTERN1 helper、sync、patch、build 或 CI workflow。
主代理提供的唯讀實機結果為 `result=-11 probed=1 TLRA5710us
start-attempted=0 writes=0`；這是既有 probe 的結果，不是新 FIFO helper
已接上或已播放的證據。

`FUXI_HAPTIC_FIFO_ACTIVE_GATE=0`，實際 write allowlist 為空，helper 沒有
呼叫 `io.write` 的路徑。`active_requested` 與 `evidence` 只保留呼叫者意圖／
來源分類，均不能開 gate；即使填入未定義 enum 值也不能代替證據。
`fuxi_haptic_fifo_independent_cutoff_verified()` 固定回傳 0，沒有以 HAP530
auto-stop、HAP525 hold-disable、last-zero 或 sample 容量推出有限 property。

本次 host-only 接續補強 callback 成功卻未填 output 的觀察防護、精確
allowlist／API 邊界與未知欄位測試，沒有加入 active 分支。C11 compile-time
assertions 固定 write/refill/stop-poll gate 為零，並核對 snapshot inventory
與 104 read／110 owner-read budgets 一致。

## 有匹配來源的資料編碼

Sony 固定 OEM source 對 HAP525_HV=4／PM8550B 提供以下依據。

| 行為 | 固定 source |
| --- | --- |
| 四 byte 原序寫入 PTN FIFO_DIN_0=0x20；餘下每 byte 寫 FIFO_DIN_1B=0x2c | `haptics_update_memory_data`，2243 起 |
| HAP520 才有尾數補零至四 byte 的 workaround；HAP525 餘數不補齊 | 同一函式，2276 起 |
| HAP525 起非 refill 寫 MEM_FLUSH_RELOAD=1 再 0 | `haptics_update_fifo_samples`，2302 起；本 helper 不執行 flush |
| 0x4a bit 2 為 EN_WFHOLD_FIFO；FIFO dry 可保持前一輸出 | 115、4053 起；本 helper 不執行 masked write |
| MMAP_FIFO 的長度編碼為 step 數減一，並設定存在 bit | `haptics_mmap_config`，3559 起 |

[Sony HAP525 身分](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L588)
[Sony FIFO packing](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L2243)
[Sony hold-disable](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L4053)
[Sony mmap programming](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L3559)

本機匹配 Android msm primary `9671bc00773d7f73172f1cf38a7cd638091d0214`
提供 HAP525 的 MMAP_FIFO bit 7／低四 bits／128-byte step、FIFO status
MSB 低四 bits、empty bit 6、full bit 5，以及 status selector 0x8005。
[Android register definitions](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#248)
[Android status selector](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#1005)

上述固定檔案的 SHA-256 分別為 Sony
`2cddf73ecb41b0b98f2db731221d8e249030ef2e5e13ad08cc428b2c434742eb`、Android
`a430f63af76c84b1e520de8fcc5f279db38f6905ecccc3469d89f80d40851b83`。

編碼器接收原始 unsigned byte sample codes，僅接受 0..0x20，不猜 signed
轉換、波形位元 packing 或 actuator 的實際力道。輸出是 host-memory
資料計畫，port 地址不是開放的硬體 write allowlist。限制為 5..32 samples、
最後四筆零、VMAX 50..1200 mV 且為 50 mV 整數步階、TLRA code 1..4095。
四-byte group 保持輸入順序，尾數保持一-byte port，不額外補 sample。
`nominal_data_us=N*TLRA_code*5` 最大 655200 us，僅為資料時間估計，
不是硬體截止、軟體 timeout 或 hard deadline。

## State machine 與交易紀錄

`init → encode → 兩輪 read-only snapshot → validate → rejected`。
I/O／身分／owner／fault／busy／不穩定／profile fork／plan corruption 會進入
failed latch。Rejected 與 failed 皆不可重入；重試前需呼叫者明確初始化新的
診斷 state。Cleanup 只清除 host plan，保留 snapshot、result 與 latch，
不寫硬體、不 stop、不 restore、不宣稱停止已確認。

- 實際硬體上限：104 byte reads、110 owner reads、0 writes、0 refill、
  0 stop polls；兩輪與各 read 均不 retry。
- 每個 read 前重新確認 CFG/PTN owner 0、BOOST owner 3；每輪末尾再確認
  三個 owner。這只縮小觀察競態，不是手機鎖或原子硬體 ownership lease。
- 兩輪 sampled raw 值必須相同；selector 在每輪讀資料前已有值，讀資料後
  重讀比對。不讀 FIFO enqueue ports，不寫 mux、不清 fault。
- Byte read 使用隨觀察次序變動的初始 output 值，兩輪可識別同一地址的
  callback 都報成功卻沒有填 output。Owner output 預置非法值，未填即拒絕。
  這是 host I/O contract 防護，不是偵測所有一致錯報的硬體資料。
- Profile 僅支援此次 HAP525 revision/layout、5710 us、FIFO T_LRA rate、
  clock-cal auto 配置、sine waveform 與既有 auto-res 配置。差異拒絕為
  profile fork；匹配數值不等於 sample clock 在 CPU/SPMI 失聯下仍獨立運行。
- MMAP_FIFO 必須明確有 present bit，容量 `(low_nibble+1)*128`。不將
  Linux driver 的 640-byte 軟體 fallback 猜成本機硬體配置。

`record_transfer` 是不帶 I/O callback 的純 host acknowledgement journal。
每個 chunk 僅可依序紀錄一次；partial／超長 count／error-even-full-count
一律鎖停、不更新 committed count、不 retry、不 refill。它只測 metadata
處理，不能證實 bytes 真正入列：transport 報成功但丟寫仍無法靠此偵測。
Plan validation 比對重新編碼結果，可偵測結構／單側資料 corruption，
不是防止同時一致改寫 payload 與 plan 的 cryptographic integrity proof。

## 不得放寬的未證條件

所有完成唯讀 preflight 的 state 都保留 active gate、independent cutoff、
外部 route 與 clock proof 四個 blockers。VMAX 不等於目標、hold bit 尚開、
FIFO threshold 非零另列 staging needs，但不進行任何 staging。

- 0x4a bit 2 清零的匹配證據只涵蓋 FIFO hold；bit 7／其餘欄位未知。
- 0x4d=0xc8 僅有 EXT_TRIG 名稱，enable／來源／極性／retrigger 未解。
  即使 raw 值為零或 SWR bits 已清，也不能猜成路由已隔離。
- HAP525 仍缺資料耗盡後電氣輸出、HPWR_DISABLED、PLAY_EN、retrigger
  與 clock 前提的自主截止證據。HAP530 說明不能代入。
- FIFO_EMPTY 與 fill=0 只代表該 mux 的資料狀態。矛盾 flags／超容量拒絕；
  一致的假 empty 報告仍可能無法識別，因此永不提升為自主停止證明。
- 軟體 stop、poll 次數、sleep/watchdog、last-zero、sample 容量和未驗
  warm-reset 都不滿足獨立硬體截止。I/O callback 本身可能阻塞，這些
  操作次數上限也不構成 wall-clock hard deadline。

## 主代理後續精確唯讀補值

SID 7 CFG base 0xf000：`0x00..0x05、0x0b、0x0c、0x46、0x48、0x49、
0x4a、0x4b、0x4c、0x4d、0x4e、0x50、0x51、0x5c、0x5d、0x63、0x68、
0x70、0x71、0x72`。PTN base 0xf100：`0x00..0x05、0x08、0x09、0x24、
0x2a、0x2d、0x30、0x31、0xa0`。BOOST base 0xf200 僅讀
`0x00..0x05、0x0b、0x41、0x46`，絕不寫 owner 3。

最優先新補值是 PTN `0x24/0x2a/0x2d/0xa0/0x30/0x31`，與同趟 CFG
`0x4d/0x70/0x71/0x72`；host fixture 的 PTN rate=0、access=0、MMAP=0x84
是合成資料，不是實機已知值。應逐筆保留 read rc 和前後 owner。
兩輪 snapshot 並不是原子快照，無法識別兩輪都被一致錯報的資料。

CFG `0x09/0x0a` 只有現有 `0x70=0x05、0x71=0x80` 才解 FIFO status；
`0x05/0x00` 是 source status，而 `0x00/0x00` 是校準狀態。保持 selector
不變；若不匹配就標記 FIFO status unavailable，不能為取 fill 寫 selector。
現有 CFG VMAX=0x1c 名義為 1400 mV，不能當成符合 1200 mV gate；
calibrated TLRA=0x04/0x76 必須保留，不由 DT 5882 us 覆蓋。

## 測試與主線整合

Windows MSVC host assertions：

```text
python tools/test-fuxi-haptic-fifo.py
```

腳本可找到已確認的 VS18 Enterprise Hostx64/x64 cl.exe，自動載入 vcvars64
environment，以 `/std:c11 /W4 /WX` 編譯實際 `.c` 與獨立 `test_fifo.c`。
Clang／GCC host 模式預設 ASan+UBSan；ARM64 syntax 是另一個獨立步驟：

```text
python tools/test-fuxi-haptic-fifo.py --cc clang
python tools/test-fuxi-haptic-fifo.py --cc clang --syntax-only
```

覆蓋所有 5..32 長度、byte order／tail port、整數 bounds、plan corruption、
partial/error journal、104 read 與 110 owner 故障點、owner change、clock/profile
fork、假 FIFO_EMPTY、拒絕 gate、零硬體寫入與 cleanup latch。
本次新增 50 個 read-allowed 地址的未填 output 測試、110 個 owner output
未填故障點、全部 65,536 地址的精確 read allowlist 與零 write allowlist
（length 0/1/4/UINT_MAX），以及 write callback 為 NULL、API 空參數、
重入／cleanup、in-place encoding。EXT_TRIG 的全部 256 raw 值及 0x4a
bit 7／hold bit 組合均維持拒絕 gate，沒有把 raw 值誤當已解碼的安全路由。
2026-11-16 本機 MSVC 14.50 `/std:c11 /W4 /WX` 已編譯並執行通過
639,687 checks；Python parser 與五檔 UTF-8/LF／whitespace 校驗亦通過。
本機 PATH 與已檢查的 LLVM 安裝位置沒有 clang，ARM64 syntax 與 ASan/UBSan
尚待主線 CI，沒有將 MSVC host assertions 代作這兩項驗證。

實際 active hardware partial-write、stop timeout／restore 仍無可執行路徑，
不能聲稱這些已驗證。後續 active 實作需先補證據，再獨立設計與測試。

可同步這五個 canonical sources。主代理可自行新增 host／ARM syntax CI
steps；本 checkpoint 不需接 PMIC、改 HEADERS 或加入核心 build。若未來
決定編入核心，需把 `.c` 與 header 一起整合，且仍不可因此啟用 active gate。

## 準備合併的精確五檔

以下路徑均以 `D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc` 為根：

```text
xnu/fuxi-haptic-prep/fuxi_haptic_fifo.h
xnu/fuxi-haptic-prep/fuxi_haptic_fifo.c
xnu/fuxi-haptic-prep/test_fifo.c
tools/test-fuxi-haptic-fifo.py
docs-lanes/haptic-fifo-preparation.md
```

這五檔可同步 canonical sources，交由主代理納入提交。只需安排上述獨立
host／clang syntax tests，不應接到 PMIC active call site，不修改原有
PATTERN1 helper、sync／聚合 patch／build。FIFO 自主截止、0x4a bit 7 與
EXT_TRIG 欄位仍未證；本次純 host 更新沒有新增實機證據。

## a948742 後的最小 primary 證據 checkpoint

本輪只重用既有固定 Sony／Android msm source；Sony bytes 的 SHA-256
與前述記錄一致。已核對 a948742 的 active gate 仍為 0，四個 C/header/test/
runner 檔案相對該 commit 沒有變更；fastCI／639687 checks 複核由主代理回報。

- **0x4a bit7 未解**：Sony 0x4a macro 僅定義於 114、用於 4067 的
  bit2 masked clear；沒有 bit7 decoder 或硬體 timer 定義。Bit2 的
  dry/hold 行為是匹配 HAP525 證據，不等於完整自主截止。
- **0x4d EXT_TRIG 未解**：Sony macro 僅出現於 126 的 offset 定義。
  0xc8 的 bits 7/6/3 可觀察，enable／來源／極性／retrigger 不能由 raw 推出。
- **OEM finite sample 源鏈**：4336 起從 `qcom,wf-fifo-data` 讀 u8 array，
  將 byte 數存為 `num_s`；1075 的 T_LRA 長度計算會略去尾端零值。
  2534 的入列路徑在全數寫完時設 `written_done=1`、threshold=0。
  這些只證有限資料與軟體估時計算，沒有設定已解碼的硬體截止 deadline。
- **播放完成路徑仍有 software stop**：4143 IRQ 在 `written_done` 且 fill=0
  後呼叫 `haptics_stop_fifo_play`；3065 的該函式呼叫
  `haptics_enable_play(chip, false)`。Android msm 3336 起亦相同。
  不能由此證明或否定硬體先前已自停；它沒有保證不服務 IRQ／不清 PLAY_EN
  時的 HAP525 行為。4203 起的 padding-zero／HW stop-driving 描述也是
  refill 資料語境，不是 HPWR_DISABLED／自主截止／retrigger specification。

[Sony finite sample parser](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L4336)
[Sony software length／trailing zeros](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L1075)
[Sony terminal IRQ](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L4143)
[Sony stop command](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L3065)

**最小唯讀補值**：若尚未留存，補 PTN `0x24/0x2a/0x2d/0xa0` 與 CFG
`0x72`，確認實際 rate／threshold／memory state／capacity／clock profile；
同趟保留 CFG `0x4a/0x4d/0x4b/0x4e/0x4c/0x0b` 的 raw 與 owner。
只在既存 CFG `0x70=5、0x71=0x80` 時解 `0x09/0x0a` 為 FIFO status，
不為讀 fill 改 mux。這些靜態唯讀值只能補配置，不能解出 bit7／EXT_TRIG
欄位，也不能證明播放後自主截止。仍需匹配 HAP525 的 cutoff／clock／
retrigger 定義及適用條件；不以 HAP530、尾零、容量或 software stop 代入。
