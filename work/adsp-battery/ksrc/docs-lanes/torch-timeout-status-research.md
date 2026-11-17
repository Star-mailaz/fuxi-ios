# Torch timeout/status 與 continuous 路徑研究

## 本輪界限與結論

本輪只新增本文件，讀取既有 host log 與 primary source。沒有修改 canonical
C、測試、sync 或 `0117`，沒有手機操作、commit 或新硬體交易。

- matched OEM source 沒有定義 `0x09`，也沒有給出該 status 的 read-to-clear、
  write-one-to-clear、timer/module disable 清除或 clear deadline 語意。
- Linux v6.12 四通道 decoder 把 `0x09 bit4` 報為 channel index 2 的 timeout。
  這是 driver 的軟體分類，不是本台 PM8550 該 revision 的 exact decoder 證明。
- 已找到明確的 IRQ latch acknowledgement，但它操作 peripheral `0x14` 與
  arbiter IRQ clear，不能推導它能清 `0x09`，更不是本輪可移植的 clear 寫入。
- OEM/mainline 都有不保留 flash safety timer 的 torch 路徑；這不能直接滿足
  Fuxi 現在的 fail-closed deadline。真正 continuous 跨越該 deadline 的安全
  路徑仍 defer，不能停用 timer、猜測 re-arm、忽略 bit4 或重試 failed worker。

## 實際 trace 與 provenance

主代理稱此情況為「第18趟 first attempt」。本機能逐筆核對此失敗型態的 raw 是：

`D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109\native-hw000torchraw-120s-boot-1\boot.log`

SHA256 `0175941f15cd14ae850c1ac8cde4d7cc285a47e4dec4e565bdbc3db0b8b96918`。
這份 trace 的 audit 11/12 明確寫入並讀回舊 byte `0x8a`，不能把它當成新的
`0x89` device result；使用者的趟次標籤也不被拿來推算其他 boot/CI provenance。

| 階段 | raw line / audit | 實際證據 |
| --- | --- | --- |
| pre-enable | 3697–3699 / 8–10 | `0x06/07/09=0/0/0`，全部 `rc=0` |
| enable | 3708–3711 / 19–22 | module `0x80`、channel `1`，write/readback 全 `rc=0` |
| 80 ms wait 後、disable 前 | 3714–3716 / 25–27 | `0x06/07/09=0/0/0`，全部 `rc=0` |
| off pair 1 | 3719–3720 / 30–31 | channel/module `0/0`，兩筆 `rc=0` |
| off pair 2 | 3723–3724 / 34–35 | channel/module `0/0`，兩筆 `rc=0` |
| post-disable status | 3725–3727 / 36–38 | `0x06/07/09=0/0/0x10`，全部 `rc=0` |
| restore | 3728–3737 / 39–48 | 四個 saved config writes、六個 saved reads 全 `rc=0` 且匹配 |
| 最後摘要 | 3686–3688、3738 | helper `-5`；後來 stopped survey `0/0/0`；49 events、dropped 0 |

這次 trace 有一次 channel-enable write，沒有失敗後 re-enable。`pulses=0`
是沒有成功完成的 pulse 計數，不能推論沒有嘗試點燈或沒有光輸出。

Audit wait 實際為 80.022 ms；channel-enable write 完成到 disable write 完成
87.327 ms，到 post-disable `0x09` read 完成 100.182 ms。timestamp 是 callback
完成時間，不是 PMIC 內部 timer start、光輸出截止或 rail transition 的時間。
軟體早已 disable，因此時間接近 100 ms 不是自主截止或 timer fault 根因證據。
兩次 off register readback 也不是光學/電流輸出或 boost 完全關閉的證明。

後來摘要的 `0x09=0` 不能證明 read-to-clear：其間已經過時間、restore writes
及其他 reads。不能區分自然狀態變化、配置/disable 關聯清除與讀取副作用。
目前 worker 保留 `-5` 並 latch off 是現行保守政策；不得因後來 status 零而解除。

## 第20趟 HAP525：獨立的唯讀證據，不能推導 torch 能力

本輪另核對主代理已取得的
`D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109\native-hw000batpause-hap-boot-1\boot.log`，
SHA256 `7a09d39036572652f5e1db96c4a9b9c71b101b54260714de4b0d4a6eaaf84134`。
Lines 380/410 的兩輪摘要都是 selector-stable、identity-valid、TLRA-valid，
TLRA 為 5710 us；但 `FIFO-status=unavailable`、`writes=0`、
`cutoff-verified=0`。Line 411 總結 58 attempts、active-gate 0、
start-attempted 0、route-verified 0。沒有主動啟動或截止驗證。

`fill=0 empty=0 capacity=0` 是 unavailable 摘要的數值，不能解讀成 FIFO
已 empty、有已知 capacity 或沒有尚待排空的資料。5710 us 是 TLRA 設定的
有效唯讀解碼，不是 finite completion/cutoff bound。HAP525 是另一個
peripheral；`0xf063=0x89` 也不是 flash SID1 `ee3e` 的 timer byte。
本趟不構成新的 `0x89` torch pulse 或 PM8550 自主截止證據。

## Primary source 鎖定與 match 程度

以下原始檔在本輪直接讀取並做 UTF-8 bytes SHA256，沒有引用二手 register 表。
MiCode kernel pin 為 `7fad87dc178d09489b74a714e4a525d56f546855`；DT pin 為
`5647c799a064dfec73332a4fe2ef7aa3fb2f4887`；mainline 固定為 Linux `v6.12`。

| ID | Primary source | SHA256 |
| --- | --- | --- |
| O1 | [MiCode leds-qti-flash.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/7fad87dc178d09489b74a714e4a525d56f546855/drivers/leds/leds-qti-flash.c) | `56e96975b820e8f88b4ae6fcf7acedfb53f577424e9f7d9b16637c86652f514d` |
| O2 | [MiCode pm8550.dtsi](https://github.com/MiCode/kernel_devicetree/blob/5647c799a064dfec73332a4fe2ef7aa3fb2f4887/qcom/pm8550.dtsi) | `71eba0d97e9f00543f23d01d8c3338eedd5ab167b6350ea9337d094d3b08cfc2` |
| O3 | [MiCode spmi-pmic-arb.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/7fad87dc178d09489b74a714e4a525d56f546855/drivers/spmi/spmi-pmic-arb.c) | `6c7c31ed1b96093b5c6780640710bb5f30a992471b2b12d3390757cf4f662a6d` |
| O4 | [MiCode qcom-spmi-pmic.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/7fad87dc178d09489b74a714e4a525d56f546855/drivers/mfd/qcom-spmi-pmic.c) | `78c31447ff9b7dcf7847a9fd76bd4eb3d54a16ed919736f11eae7613e8ae3d98` |
| L1 | [Linux v6.12 leds-qcom-flash.c](https://github.com/torvalds/linux/blob/v6.12/drivers/leds/flash/leds-qcom-flash.c) | `41575a93352acf5598563bcb943fbdf07931a443fd5ad649dc1d4bd836a0916f` |
| L2 | [Linux v6.12 spmi-pmic-arb.c](https://github.com/torvalds/linux/blob/v6.12/drivers/spmi/spmi-pmic-arb.c) | `37913bfb3d7678bbb87f4f4ab6445d1910bd6d1259c7f6a45ce3970a62c7c0f2` |
| L3 | [Linux v6.12 regmap.c](https://github.com/torvalds/linux/blob/v6.12/drivers/base/regmap/regmap.c) | `405be7c9fd3f91fa82be98e35c1c6129d45e7e9eb4089572d38829fa277ab8a4` |

本機 `D:\xiaomi13\fuxi_ios\dtb\fuxi-live.dtb` 的 SHA256 是
`0f4f5e4fbc64619b2753062b8a9785e76261dc1ab434cc79d8f7f82046289f31`。
先前已純 host 解析 node
`/soc/qcom,spmi@c42d000/qcom,pm8550@1/qcom,flash_led@ee00`：compatible 是
`qcom,pm8350c-flash-led`、base `0xee00`、status `ok`，IRQ sources 0/3/4。
O2 lines 120–128 使用同一 PM8550 flash compatible/base/IRQ layout；O1
lines 1921–1923 的 match table 對它配置四通道，lines 107–109 定義 subtype 7。

這足以鎖定要研究的 OEM driver family。它不是對本機 Android loaded module
binary、silicon revision、每個 status bit 或 PMIC analog 時序的驗證。Raw 只
有 flash type `0x18` / subtype `0x07`；沒有這個 peripheral 的 revision read。
L1 lines 838–862 依 type/subtype 選通用四通道 map，而不是依本台 PM8550
revision 選一份已實測 decoder。不能把「同 compatible/subtype」升格為
「本台 PM8550 exact status decoder」。

## Status / latch-clear 能證明什麼

### OEM flash driver

O1 lines 30–40 定義 status1 `0x06`、status2 `0x07` 和 IRQ RT status `0x10`。
`qti_flash_led_read()` 在 lines 264–277 呼叫 `regmap_bulk_read()`。
`qti_flash_led_irq_handler()` 在 lines 1385–1424 讀 `0x10`、`0x06`、`0x07`
並記錄 IRQ/channel/VPH 訊息；該函式沒有 status clear、reset 或 re-enable。
lines 1333–1339 的 `flash_ops` 也沒有 `fault_get`。

O1 沒有定義或讀取 status3 `0x09`，因此不能由此取出 `0x09 b4` 的確切名稱、
清除條件或容許值。它不讀該 register 並不代表 byte 可忽略、必為正常或不存在。

O1 對 IRQ RT status `0x10` 的 bit4 命名為 all-ramp-up-done，bit3 為
all-ramp-down-done，bit0 為 open/short/vreg-not-ready aggregate。它們是
peripheral `ee10` 的 bits，不是 `ee09` 讀到的 value `0x10`。尤其不能把
「`0x10 bit4` 是完成事件」套到「`0x09 bit4` 是正常完成事件」。

### Mainline flash decoder

L1 lines 135–144 的四通道 map 指定 `0x06` status1、`0x07` status2、
`0x09` status3。`qcom_flash_fault_get()` lines 488–561 只讀這些 fields 並
輸出 `LED_FAULT_*`；四通道 timeout 使用 `BIT(chan_id * 2)`。
因此該 decoder 對 channel index 2 會把 `0x09 bit4` 報為 timeout；channel0
timeout mask 則是 bit0。它沒有依 pre-enable/post-disable 階段改變分類。

這不證明本台的 bit4 真由第三通道 timer 觸發，也不證明因 channel0 是此次
caller 的唯一輸出而可以遮掉其他 bits。不能添加 `status & 1` 之類的豁免。
原始 register byte 和 decoded hypothesis 必須分開記錄。

L1 沒有對 `REG_STATUS1/2/3` 發出 clear write。L3 lines 3056–3068 的
`regmap_field_read()` 是 read、mask、shift，沒有額外 clear write。
這只證明所看軟體沒有顯式清除，不能排除 silicon 本身的 read-to-clear。
O4 lines 122–145 是一般 16-bit address / 8-bit value SPMI regmap 配置與
建立；沒有 flash-specific status-clear hook 或 bit4 lifetime 定義。

### 明確存在的是 IRQ latch ack，不是 `0x09` clear protocol

O3 lines 481–490、L2 lines 580–589 都定義 peripheral IRQ RT status `0x10`、
LATCHED_CLR `0x14`、EN_SET `0x15`、EN_CLR `0x16`、LATCHED_STS `0x18`。
O3 `qpnpint_irq_ack()` lines 626–637、L2 lines 752–764，清 arbiter IRQ
並把該 IRQ 的 `BIT(irq)` 寫到 peripheral `0x14`。Unmask 路徑也在 enable
IRQ 前處理 pending latch。O2 的 flash IRQ sources 是 0/3/4，屬同一 IRQ
namespace；不是 `0x09` decoder 的 channel-index masks。

這是 Linux IRQ owner 的 ack 工作。上述來源沒有指定「ack 某 IRQ 後清掉
`0x09 b4`」的關係。Fuxi 目前只有受限 flash write allowlist，沒有在此
移植 Linux IRQ ownership；不能新增 `0x14/15/16` 寫入，更不能嘗試往
`0x09` 寫 0、`0x10` 或 `0xff`。列出 IRQ registers 僅作 source 區別，
不是硬體 clear 操作指示。

### 尚缺的語意

| 問題 | 本輪能否確立 |
| --- | --- |
| PM8550 該 revision 的 `0x09 b4` 名稱/來源 | 不能；只有 L1 通用 decoder 假說 |
| `0x06/07/09` 是 live、latched、read-to-clear 或混合 | 未被上述 matched sources 逐 bit 指定 |
| IRQ ack `0x14` 是否影響 `0x09` | 沒有關聯證據 |
| channel/module off 或 timer restore 是否清 b4 | log 時間序不能區分，source 沒有保證 |
| clear、ramp-down、timer cancel 的有限最長時間 | 沒有 hardware-backed bound |
| 自主 cutoff、光輸出 off、boost/vreg root cause | 未實測/未捕捉；不能猜 thermal 或 boost fault |

所以本輪沒有 status-clear patch 提案。全部非零 status 拒絕和 failed latch
必須維持，即使將來觀察到 byte 再次歸零也不能因此 retry。

## Continuous torch 的 primary 路徑與安全缺口

### OEM 路徑：configure 與 switch 是兩階段

O1 `qti_flash_led_enable()` lines 425–463 設 IRESOLUTION/ITARGET；只有
`FLASH_LED_TYPE_FLASH` 會在這裡寫入 safety timer enable。對已 enabled 的
TORCH/INDICATOR，函式在 current 配置後直接返回，不重啟 channel。
Setup lines 1358–1364 先清各 configured fnode 的 timer-enable bit。
因此不能假設 OEM torch 自帶 Fuxi 的 100 ms fail-closed timer。

一般 torch brightness configure 不等於 channel 已 on：lines 571–576
只有 INDICATOR 直接 strobe；switch enable lines 692–745 按已配置 fnode、
switch mask、channel map 再 enable。`qti_flash_led_strobe()` lines 367–417
先確保共享 module enable，再做 masked channel enable；disable 時先關
channels，在沒有剩餘 caller/channel 時關 module。

O1 lines 385–391 的 switch off hrtimer 只在 caller 配了非零 `off_time_ms`
時啟動；初始值在 line 1502 為零。`off_timer_function()` lines 846–859
仍需 CPU 執行、拿共享狀態並經 SPMI 關 switch。它不是 PMIC 自主 deadline，
不能代替對 stalled worker、IRQ 或 NoC/SPMI failure 的獨立硬體關斷證據。
Brightness zero lines 529–539 與 switch disable lines 748–790 會關 channel，
再由 `qti_flash_led_disable()` 清 current/timer；這不是 `0x09` clear 語意。

### Mainline 路徑：明確停用 flash timeout

L1 `qcom_flash_led_brightness_set()` lines 564–599 的順序是：

1. 對該 LED 的 channels destrobe，釋放該 LED 的 module reference。
2. 計算 shared current budget，設定 `TORCH_MODE` current/IRESOLUTION。
3. 呼叫 `set_flash_timeout(led, 0)`，明確停用 flash safety timer。
4. 取得該 LED 的 module reference，再 SW strobe 該 LED 的 channels。

Module references 在 lines 175–196 使用所有 caller 的 `chan_en_bits`；
channel writes 在 lines 394–428 使用該 LED mask，不是覆蓋其他 caller。
`TORCH_MODE` 的 current 配置在 lines 320–365 使用 5 mA resolution；這
不是證明存在另一個可猜測的「continuous mode」寄存器。

完整 mainline 流程亦不能只挑最後幾個 writes 套入：
`update_allowed_flash_current()` lines 199–317 管 shared current，且暫時
寫 thermal threshold fields、讀 status，再 restore thresholds。這些不是
Fuxi 現有 pulse allowlist；本輪不移植、不修改 thresholds 或 rail/boost votes。
OEM current/switch ownership 也不能用 Fuxi 一個 worker mutex 取代。

### Fuxi 可保留的路徑，以及目前不能通過的 gate

目前可保留的是已授權的 default-off、明確 opt-in bounded pulse 路徑：
`0x89`、80 ms wait、20–80 mA、兩秒 lease、全 byte status 拒絕、bounded
off confirmation、restore 及 failed latch。它不是跨越 timer deadline 的
真正 continuous torch，也不是本輪授權增加的測試或 worker 重試。

Source-derived timer table 的精確入口：

- [O1 `timeout_to_code()` lines 221–226](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/7fad87dc178d09489b74a714e4a525d56f546855/drivers/leds/leds-qti-flash.c#L221)
  使用 `round(timeout_ms / 10) - 1`；lines 42–47 定義 channel timer base、
  bit7 enable 與 10 ms step。
- [L1 `set_flash_timeout()` lines 368–386](https://github.com/torvalds/linux/blob/v6.12/drivers/leds/flash/leds-qcom-flash.c#L368)
  使用 `timeout_ms / 10`；lines 45–47 定義 bit7 enable、低7 bits 與 10 ms
  step，line 139 的四通道 map 指定 timer base `0x3e`。

以下是整數 10 ms multiples 的 source programming formula 反解，不是實際
PMIC 的計時、公差或 autonomous cutoff measurement：

| Byte | OEM model | Mainline model |
| --- | --- | --- |
| `0x8a` | 110 ms | 100 ms |
| `0x89` | 100 ms | 90 ms |

兩套都不構成實際 PMIC 自主截止證明。`0x89` 不能被當作可無限維持的 timer。
不允許為了消除 timeout status 而清 timer enable，也不允許假設寫回同一
byte 會安全 re-arm。失敗後把 continuous 路徑當作「另一模式」重試同樣禁止。

將來若另行分配 continuous 實作，最低 acceptance gates 是：

- 新 opt-in 預設 off；failed worker 絕不透過模式切換或 status 清零恢復。
- 先有四通道、所有 caller 和共享 module/current/boost/rails 的明確 ownership；
  保留 external refs，不靠整字 restore 覆蓋其他 caller。
- 先有實際 revision 與 raw status/clear 生命週期證據，不能以 L1 decoder
  或軟體模擬解除任何 bit4 fault 拒絕。
- 若未來另行申請無 flash timer 的 continuous 路徑，必須先有另行批准、
  已證明有限 deadline 的獨立 fail-closed 輸出關斷機制，能涵蓋 lease/client
  消失與 CPU/worker/SPMI 停滯。本輪不授權取消 timer；僅移動 IOSleep、
  加 hrtimer 或續租不能滿足這項。
- 保持電流/lease 上界，不改變 thermal thresholds、boost ownership 或未分配
  register allowlist。驗證任何中途失敗都關斷或明確保留 unresolved ownership，
  不 restore 可導致重啟輸出的 active external state。

這些是 future gates，不是本台已有能力。沒有獨立 cutoff 證明前，安全結論是
**defer true continuous，維持現有 bounded 路徑與 failure containment**。

## 留給主代理下一輪只讀診斷的證據清單

這只是已命名 register 的讀候選，不增加本輪 read/write，也不授權再次啟用
已 failed 的 worker。主代理須自行保持現有 opt-in、time/audit budget 與 owner
檢查；每筆記錄完整 raw byte、transport rc、階段與完成 timestamp。

- Identity：peripheral revision `0x00`、type `0x04`、subtype `0x05`。
- 四通道配置：timers `0x3e..0x41`、ITARGET `0x42..0x45`、IRESOLUTION
  `0x49`、strobe controls `0x4a..0x4d`、module `0x46`、channel bits `0x4e`。
- 分階段保留 `0x06/07/09` 原始值；可在既有固定只讀 budget 內觀察 subsequent
  samples，但不得把重複讀當作無副作用 clear 或 fault retry。
- OEM 真正使用的 peripheral IRQ RT status `0x10` 可作為 ownership 核對後
  的候選；IRQ latched status `0x18` 只有 generic irqchip 定義，不將其提升為
  已驗證 flash 讀取或把 IRQ pending 消失當作 `0x09` 清除證明。
- 不在同一「只讀」診斷中 ack IRQ、clear status、寫 peer channel、改 timer
  或再次 enable。診斷容量不足時明確標 dropped/缺樣，而非無限補讀。

新增 snapshot 會增加實際 transactions/time；沿用 80 ms sleep 不代表額外
讀取仍落在原來的輸出時間內。應由主代理預先安排 admission/off 後的額外
reads，保留最遲 disable 時間，不能在 active window 內無界加入全通道 dump。

本文件驗證是 host log 逐筆核對、七份 primary source hash 與呼叫路徑檢查；
沒有新增或執行硬體/host transport 測試。尚無 b4 exact decoder、可靠 clear
protocol 或 continuous fail-closed route，不能把研究文件當作這些能力的驗收。
