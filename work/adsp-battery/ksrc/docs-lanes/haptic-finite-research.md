# HAP525 PATTERN1、auto-shutdown 與有限 FIFO 研究

研究日期為 2026-11-16。對象是 fuxi 的 SID 7 HAPTICS_CFG/HAPTICS_PATTERN
revision 4、type/subtype 15/0a 與 15/0b，以及 owner-3 HAPTICS_BOOST。
本文件提供寄存器證據與後續 patch 建議。

## Checkpoint：維持唯讀，不開放播放

本輪交付的是研究文件，不是可啟用的 PATTERN1 或 FIFO 生產 patch。
已核對 ksrc `51e7ca9` 與 harness `3c09708` 的 commit 存在；ksrc 該固定
commit 的 `fp_haptic_diagnostic` 仍以 `FuxiHapticIo {..., 0}` 初始化，
`pattern1_finite_verified=0`。5g/9g CI 的 host 與 ARM syntax step 通過、
核心仍編譯中，是主代理提供的狀態，本研究未另外查詢 CI。

| 項目 | 可證範圍 | 仍不能證／本輪決策 |
| --- | --- | --- |
| CFG 0x4a | 名稱 `AUTO_SHUTDOWN_CFG`；bit 2 為 HAP525 起適用的 `EN_WFHOLD_FIFO_BIT` | 不能由寄存器名稱推論 timer；bit 7 與其餘欄位未知 |
| CFG 0x4a=0x84 | bit 2 已開啟，OEM 明述 FIFO dry 時可保持前一輸出 | 清 bit 2 僅是 FIFO 候選必要設定，不構成 PATTERN1 截止證明 |
| CFG 0x4d=0xc8 | 名稱 `EXT_TRIG`；bits 7、6、3 為 1，其餘為 0 | enable、來源、極性、edge/level、retrigger、timeout 均無匹配 decoder |
| PATTERN1 | 八筆 sample 配置；PLAY_EN clear 與 HPWR_DISABLED poll 的 command-stop 路徑 | 未證 PLAY_EN 保持 1、CPU/SPMI 停止服務時仍自行結束且不重播；gate 維持 0 |
| 有限 FIFO | HAP525 hold-disable 有匹配 OEM 證據；HAP530 primary patch 明述 FIFO-empty auto-stop | HAP530 語義不能直接移作 HAP525 保證；HAP525 電氣輸出／HPWR／PLAY_EN／路由仍缺證 |

要開放 PATTERN1，仍需匹配 HAP525/PM8550B 的有限／重播／end-of-pattern
欄位定義與適用條件，尤其 PLAY_EN 未清除時的行為，以及外部 trigger/SWR
能否接管或重新開始播放。要主張 CPU 或 SPMI 失聯下的自主截止，還需該
硬體資料路徑、clock 與觸發條件的證據，不能只提供正常軟體停止的測試結果。
Software stop、sample 容量、software sleep/watchdog 與未驗 warm-reset
均不滿足獨立硬體截止條件。

本文件可由主代理同步至 canonical sources，並納入後續 checkpoint。
本代理不提交、不操作手機、不改 sync／聚合 patch，亦不修改正在測試的
`fuxi_pmic.c`、haptic headers 或既有 tests。文件中的寫入方案一律尚未套用，
不應加入本趟唯讀 probe；沒有額外 HEADERS 或 build 整合需求。

## 目前可採用的結論

- OEM 公開 driver 明確定義 config 0x4a bit 2 為 `EN_WFHOLD_FIFO_BIT`，並註明
  適用 HAP525_HV 與後續版本。fuxi 的 0x84 因此具有 FIFO waveform-hold enable。
- 同一 driver 明確說明 FIFO 耗盡時，hold 會維持前一個輸出，最後一筆非零且
  SPMI_PLAY 未及時清除時會持續輸出。它以 masked write 清除 bit 2。
- 對 FIFO 分支，有證據的最小設定變更是保存其他 bits，將 0x84 改為 0x80。
  這個欄位的已知作用範圍是 FIFO。PATTERN1 的自主結束與重播語義仍待確認。
- 本輪讀到的 Android、OEM driver 與相容寄存器版型的 UEFI BSP，仍未提供
  config 0x4d 的 bit-field decoder。0xc8 的 bits 7、6、3 已設定，這些 bits 的
  語義維持未定。
- 獨立 FIFO-empty 截止是可追溯的替代候選。HAP525 實機的輸出截止、
  HPWR_DISABLED 與外部觸發接管條件，仍需分別確認。

上述 FIFO-hold 判斷使用 OEM primary source。兩個 OEM repository 保留相同
Qualcomm driver 內容，屬於同一實作的交叉核對。
[Sony 定義](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L114)
[Sony 行為與 masked write](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L4053)
[OnePlus 對應實作](https://github.com/OnePlusOSS/android_kernel_oneplus_sm8750/blob/6028f47faddaa27700f8dd3a1d83906ea8f27170/drivers/input/misc/qcom-hv-haptics.c#L4488)

## 0x4a=0x84 的解碼程度

| Bits | fuxi 值 | 本輪證據 | 可採取的判斷 |
| --- | --- | --- | --- |
| 2 | 1 | `EN_WFHOLD_FIFO_BIT = BIT(2)`，HAP525_HV 起適用 | FIFO dry 時可維持前值 |
| 7 | 1 | 已讀來源缺少 field 定義 | 保存原值，截止作用未定 |
| 6、5、4、3、1、0 | 0 | 已讀來源缺少 field 定義 | 保存原值 |

Sony driver 的 HAP525_HV enum 明確標示 PM8550B，revision 值為 4。它的
`haptics_init_fifo_config` 位於一般 FIFO 初始化路徑，hardware condition 為
`chip->hw_type >= HAP525_HV`。目前固定檔案中，0x4a 的 macro 出現兩次，
分別是定義與該 masked write。
[Sony HAP525 識別](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L588)
[Sony FIFO 初始化](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L4053)

driver 的說明建立了 hardware FIFO dry 與輸出 hold 之間的因果關係。
對 bit 2 清零且資料供應結束的 FIFO，這提供了硬體消耗完資料後釋放前值的
實作線索，但沒有完整列出 hold-disabled 時的電氣輸出、功率狀態及觸發
狀態轉移。HAP525 上自動轉為 HPWR_DISABLED 的時間與 SPMI_PLAY bit 的
自清除行為，該段程式仍未明確保證。

Qualcomm 發布的 2026-08-28 v7 driver patch 另有明確描述，所有 FIFO samples
播放完會由硬體自行停止，refill 失敗後已入列的資料也會播放完並自行停止。
該 patch 的對象為 PMIH0108/HAP530_HV。這提供後續硬體的 primary-source
語義，HAP525 的適用性主要依據仍是上述 OEM driver 的 revision condition。
[Qualcomm v7 FIFO-empty handler](https://lkml.iu.edu/2608.3/09547.html)

## 0x4d=0xc8 的解碼缺口

固定 Android msm driver 將 0x4d 命名為 `HAP_CFG_EXT_TRIG_REG`，其內容只有
offset 定義。固定 Sony 與 OnePlus driver 也各只有一次該 macro，未提供
field masks、source selection、enable polarity、edge/level、retrigger 或
timeout 的定義。由 0xc8 可以確認 raw bit 狀態，具體 trigger 行為仍未解出。
[Android msm 固定來源](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#117)
[Sony offset 定義](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L126)
[OnePlus offset 定義](https://github.com/OnePlusOSS/android_kernel_oneplus_sm8750/blob/6028f47faddaa27700f8dd3a1d83906ea8f27170/drivers/input/misc/qcom-hv-haptics.c#L169)

公開的 BOOT.MXF.2.5.1 BSP mirror 提供 `pm_haptics_cfg_driver.*`，其
subtype 0x0a、SPMI_PLAY 0x4c、VMAX 0x48、TLRA 0x5c/0x5d 與本機版型相符。
初始化允許 digital major/minor 合成值至 0x51，涵蓋 revision 4.0。
其寄存器表省略 0x4a 與 0x4d，API 使用 direct play 開始／停止。此 mirror
保留 core.boot/6.5.1 路徑與版本標記，release 的官方發布完整性未獨立驗證。
[BSP subtype 與版本檢查](https://github.com/mobstyle10-arch/BOOT.MXF.2.5.1/blob/c60ac2f1da8da430f246da52f375e1d986e77349/buildpath0/boot_images/boot/QcomPkg/Library/PmicLib/drivers/haptics/src/pm_haptics_cfg_driver.c#L38)
[BSP 寄存器表](https://github.com/mobstyle10-arch/BOOT.MXF.2.5.1/blob/c60ac2f1da8da430f246da52f375e1d986e77349/buildpath0/boot_images/boot/QcomPkg/Library/PmicLib/drivers/haptics/src/pm_haptics_cfg_driver.h#L40)
[BSP direct-play API](https://github.com/mobstyle10-arch/BOOT.MXF.2.5.1/blob/c60ac2f1da8da430f246da52f375e1d986e77349/buildpath0/boot_images/boot/QcomPkg/Library/PmicLib/drivers/haptics/src/pm_haptics_cfg.c#L55)

此 BSP 的 recursive tree 有 21,199 entries，GitHub API 回報
`truncated=false`。已檢查 haptics driver、public API、app 與 haptics DTS
schema。這些檔案未補足 0x4d decoder。後續需要 HAP525/PM8550B 對應的
register specification，或含 named masks/values 的匹配 BSP 實作。

## PATTERN1 與停止命令

既有 Android primary source 已與本機 reference 逐 byte 核對一致，Git blob
為 `c01dba8a56be60caca240a28d43cf522f27183ed`。
`haptics_set_pattern` 寫入八筆 sample，`haptics_enable_play` 設置／清除
SPMI_PLAY bit 7，`haptics_wait_brake_complete` 在停止命令後 poll
HPWR_DISABLED。這建立了 command-stop 與停止觀察的路徑。
[Android pattern programming](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#1812)
[Android stop verification](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#1677)

新版 Sony 的 impedance test 對 HAP525 仍選 PATTERN1，等待指定長度後呼叫
`haptics_enable_play(chip, false)`。容量、軟體等待與 trailing-zero samples
各自提供不同資訊，PLAY_EN 一直設置時的 PATTERN1 循環與自主停止仍待
對應硬體定義確認。
[Sony PATTERN1 測量分支](https://github.com/sonyxperiadev/kernel/blob/59bc62dc3045c334b51a8794ffe434cbeee2a886/drivers/input/misc/qcom-hv-haptics.c#L5240)

目前的 `pattern1_finite_verified` 固定維持 0。FIFO-hold 欄位的新證據
可用於獨立 FIFO 方案。Software sleep、workqueue timeout、CPU watchdog
及尚待驗證的 warm-reset 行為，均無法補足這個 PATTERN1 硬體截止證據。

## 主代理後續可安排的純唯讀 survey

以下是候選補值清單，不修改目前已整合的 probe。所有地址均為 SID 7，
offset 以各 peripheral base 為基準。先紀錄 APID、owner、每次 read 的
return code，再解碼有效資料；read 失敗不可用零值替代成功結果。

| Peripheral | 唯讀 offset | 用途與限制 |
| --- | --- | --- |
| CFG base 0xf000，APID 631／owner 0 | 0x00..0x05 | revision、type/subtype 身分；不能套用舊單一 haptics layout |
| CFG | 0x0b、0x0c | HPWR_INTF bits 1:0 為 0 表示 HPWR_DISABLED；fault 的 SC／auto-res／HPWR-ready flags |
| CFG | 0x46、0x48、0x49、0x4a、0x4b、0x4c、0x4d、0x4e | module enable、VMAX、waveform、hold、priority、SPMI 命令與未解外部觸發／SWR 設定 |
| CFG | 0x50、0x51、0x5c、0x5d、0x63、0x68、0x72 | brake、校準 TLRA、auto-res、VSET 與 clock-cal 配置；不觸發校準或清除 fault |
| CFG | 0x70、0x71，及 0x09、0x0a | 先讀現有 status selector，再讀其資料，最後重讀 selector 確認未變；不寫 selector |
| PTN base 0xf100，APID 632／owner 0 | 0x00..0x05、0x08、0x09 | 身分、FIFO_READY bit 0、NUM_PAT；READY／NUM_PAT 不代表自主截止 |
| PTN | 0x24、0x2a、0x2d、0xa0 | FIFO rate、empty threshold、memory-access／flush 狀態、FIFO memory 存在與配置容量 |
| PTN | 0x30、0x31、0x34..0x4b | 可選：PATTERN1 TLRA 與八筆三-byte sample 設定；只證設定／容量，不證播放終止 |
| BOOST base 0xf200，APID 556／owner 3 | 0x00..0x05、0x0b、0x41、0x46 | 僅觀察身分、STATUS4、follow 與 enable；絕不寫入 owner 3 |

最值得補值的是 PTN `0x24/0x2a/0x2d/0xa0/0x30/0x31`，以及 CFG
`0x4d/0x70/0x71` 的同趟值。後三者在舊 survey 已有讀值，但需要保留與
本趟 HPWR/fault/source 配置同一時序的紀錄；不必為本輪 checkpoint 改 probe。

固定 Android source 的 `haptics_get_status_data` 先寫 CFG 0x71，再寫
0x70，才讀 0x09/0x0a。因此呼叫該 helper 不是純唯讀。只有既存 raw
selector 為 `0x71=0x80、0x70=0x05` 時，才可將讀值解為 FIFO_REAL_TIME_STS：
`fill=((MSB & 0x0f)<<8)|LSB`，MSB bit 6 為 FIFO_EMPTY。既存 selector 為
`0x71=0x00、0x70=0x05` 時，LSB bits 2:0 才是 driver source status。
若為舊 survey 的 `0x00/0x00`，0x09/0x0a 是校準狀態，不是 FIFO fill 或
目前 source。Selector 不匹配或前後變動時，只記 raw，不能強行套 decoder。
CFG 0x4c 的 source bits 是 SPMI 命令設定，不能單獨證明仲裁後的實際 source。
[Android selector 寫入與資料解碼](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#1005)

舊 survey 的 CFG `0x4b=0x04` 沒有設定 `SWR_IGNORE_BIT` bit 4；`0x4e=0xe0`
的 SWR_PAT_CFG_EN／SWR_PAT_INPUT_EN／SWR_PAT_RES_N bits 7/6/5 均為 1。
這不證明當時有 SWR 播放，但不能據此宣稱外部路徑已隔離。`0x4d=0xc8`
的 GPIO/EXT_TRIG 解碼仍缺，純唯讀取得更多 raw 值也不能自行補出 field 語義。

舊 survey 的 CFG `0x48=0x1c` 按匹配 HV driver 的 50 mV/code 編碼是名義
1400 mV，不是 Android DT 的 1200 mV；這是 register 編碼，非輸出電壓量測。
未來任何非零診斷仍需另外寫入並驗證不超過 1200 mV 的 VMAX，不能把現值
當成符合電壓 gate。CFG `0x5c/0x5d=0x04/0x76` 依 5 us/code 為 5710 us，
保留該校準值，不以 DT period 5882 us 覆蓋。BOOST `0x41=0xe0` 是
HW_EN／HW_CCM／HW_VSET bits 7/6/5，不是 PSskip；`0x46=0` 是當下
VREG_EN 未設定，不能單靠該值保證未來播放的功率狀態。
[Android VMAX 寫入編碼](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#1295)

上述 survey 不讀 FIFO 入列 ports `0x20..0x23/0x2c`、不 flush、不選 mux、
不清 fault、不設定 PLAY_EN。它只能補足身分、配置及當下狀態，不能證明
PATTERN1 或 FIFO 在播放後自主截止，也不能取代 matched register specification。
本輪既有實機證據來自
`D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109\native-hw000torch-cc-boot-1\boot.log:236`，
不是本代理重新操作手機所得。

## 舊 UEFI WF_REPEAT 的版型核對

舊 `pm_haptics_driver.h` 使用以下 layout。

| Offset | 舊 layout | HAP525 config layout |
| --- | --- | --- |
| 0x4a | EN_CTL3 | AUTO_SHUTDOWN_CFG |
| 0x4d | LRA_RES_TYPE | EXT_TRIG |
| 0x51 | VMAX_CFG | CL_BRAKE_CFG |
| 0x5e | WF_REPEAT | RC_CLK_CAL_COUNT_MSB |
| 0x70 | PLAY | MOD_STATUS_SEL |

Rivko SDM670 mirror 與較新的 XBL mirror 所找到的舊 header 具有相同 SHA-256。
舊 `pm_haptics_wf_repeat` 將 repeat 欄位以 mask 0x73 寫入 0x5e，而相容新
CFG driver 的同名 API 是直接回傳 success 的空實作。API 名稱與 repeat enum
保留了歷史介面，移植需要以實際 register layout 為依據。
[舊 register layout](https://github.com/Rivko/android-firmware-qti-sdm670/blob/20bb8ae36c93fc16bbadda0e0a83f930c0c8a271/boot_images/QcomPkg/Library/PmicLib/drivers/haptics/src/pm_haptics_driver.h#L40)
[舊 repeat 寫入](https://github.com/Rivko/android-firmware-qti-sdm670/blob/20bb8ae36c93fc16bbadda0e0a83f930c0c8a271/boot_images/QcomPkg/Library/PmicLib/drivers/haptics/src/pm_haptics.c#L420)
[新 CFG repeat 空實作](https://github.com/mobstyle10-arch/BOOT.MXF.2.5.1/blob/c60ac2f1da8da430f246da52f375e1d986e77349/buildpath0/boot_images/boot/QcomPkg/Library/PmicLib/drivers/haptics/src/pm_haptics_cfg.c#L261)

## 未套用的 FIFO 最小變更候選

以下只表示已有匹配來源支持的單一 FIFO 欄位變更，不是完整安全播放 patch，
不授權執行；完整 HAP525 cutoff 與 trigger 證據尚未補齊。

```c
uint8_t fifo_shutdown = saved_shutdown & 0xfbu;
int result = fuxi_haptic_write_checked(io, 0xf04a, fifo_shutdown);
```

在 fuxi survey 的 0x84 上，結果為 0x80。`fuxi_haptic_write_checked` 的
allowlist 與 PMIC adapter 需先加入 0xf04a，才能使用這個片段。
完整 FIFO 分支還需要以下可追溯操作，現有 PATTERN1 分支的能力條件保持
原有判斷。

| Register | 後續 FIFO 分支用途 |
| --- | --- |
| CFG 0x4a | 保存／masked clear bit 2，驗證實際值 |
| CFG 0x71、0x70 | 依序選 FIFO_REAL_TIME_STS=0x8005，再讀 0x09/0x0a |
| PTN 0x24 | 保存上半 byte，選擇已知 FIFO play rate |
| PTN 0x2a | FIFO-empty threshold 清零，資料一次全部入列 |
| PTN 0x2d | HAP525 的 MEM_FLUSH_RELOAD 寫入值 1→0 sequence |
| PTN 0x2c | 已知的單 byte FIFO data port |
| CFG 0x4c | FIFO source 0，PLAY_EN=1 的命令值為 0x80 |
| PTN 0xa0 | 讀取 HAP525 FIFO memory present 與容量，確認可容納 N 筆 |

MEM_FLUSH_RELOAD 的欄位是 bit 0，上表的 1→0 表示兩個寫入值。
每個會改變狀態的操作仍需 owner-0 檢查與可適用的讀回確認。
FIFO data port 屬於入列介面，普通 register readback 的 payload 驗證語義
尚待確認。可以讀 fill count 驗證入列數量，該 count 僅證明數量。
HAP525 fill count 使用 MSB mask 0x0f，FIFO_EMPTY 使用 MSB bit 6。
[Android FIFO data port 與 flush](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#1873)
[Android status selector](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#1005)
[Android fill count](https://android.googlesource.com/kernel/msm/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c#1997)

建議先採用獨立的零資料 FIFO qualification。它需要先確認外部 trigger/SWR
路由在該 boot 配置下會保持既定 source，並保留 type/revision/fault/idle/
boost-follow 檢查。這一輪的 research 本身尚未解決 0x4d 路由問題。
以下是條件補足後的研究設計，不是本趟唯讀 probe 的執行項目。

1. 保存設定並確認 HPWR_DISABLED，清除 FIFO hold，選定已知 rate，flush。
2. 一次入列 N 筆零 sample，在 PLAY_EN 尚未設置前確認 fill count 為 N。
3. 啟動 FIFO，維持 SPMI_PLAY 的 PLAY_EN，不 refill、不發出軟體 stop。
4. 讀取 fill count、FIFO_EMPTY、HPWR_INTF、fault 與目前 source，紀錄
   FIFO 耗盡前後狀態。若 PLAY_EN 仍為 1 而 fill=0，這是資料消耗的直接證據。
5. 在資料耗盡後另行做 command-stop、HPWR_DISABLED 驗證與還原。
   Restore 仍以停止確認為前提。Hold=0 與有限資料設定需保留至安全停止確認。

零 payload 的 FIFO_EMPTY/fill=0 只證明資料被消耗。零資料原本就不會要求
非零輸出，所以它不能證明非零尾 sample 的自主截止；只有在沒有 software
stop 前觀察到 HPWR_DISABLED，才有該次自主功率狀態轉移的證據。後續的
command-stop 驗證不得倒算為先前自停成功。電氣輸出截止、重播及外部
retrigger 的完整主張仍需對應硬體定義與適當觀察。

非零低幅 FIFO 診斷可在上述條件與外部路由得到確認後另行準備，保留
VMAX<=1200 mV 與校準 TLRA。候選 payload 為八筆
`{0x20, 0x20, 0x20, 0x20, 0, 0, 0, 0}`，一次入列後停止補充資料。
選 T_LRA 時，完整資料區間的名義長度是 N×TLRA，對 N=8、TLRA=5710 us
為 45.68 ms。PMIC sample clock 持續工作是資料消耗的前提，觀察結果需確認
實際耗盡時間。這個名義長度用於判讀觀察資料。

FIFO 候選截止機制是 dry/hold-disabled 的資料路徑，但完整 HAP525 自主
停止語義尚未證實，不得因此放開 production gate。
Observer polling 的 sleep 只控制取樣時機。CPU 完全停止、SPMI command
channel timeout 與 GPIO/SWR retrigger 等情境的主張，需依各自硬體證據與
實測範圍描述。外部 trigger 若可接管其他 source，單次 FIFO 耗盡也只建立
該 FIFO 播放的截止結果。

## 可重現來源與 hash

以下 SHA-256 對應本輪由固定 commit raw URL 讀到的 bytes。

```text
Android msm 9671bc qcom-hv-haptics.c
a430f63af76c84b1e520de8fcc5f279db38f6905ecccc3469d89f80d40851b83
Sony 59bc62 qcom-hv-haptics.c
2cddf73ecb41b0b98f2db731221d8e249030ef2e5e13ad08cc428b2c434742eb
OnePlus 6028f4 qcom-hv-haptics.c
8bf939e279ab5fd4bbd7abf9f21af5c3327424789c2e80da713db328b89e79d1
BSP c60ac2 pm_haptics_cfg_driver.h
f372357d3c68e90f7907e6f03b021586b2ecab297dc6b2bb533aa71977aeb90a
BSP c60ac2 pm_haptics_cfg_driver.c
3c822d6821df96a9f02573fe4140f80ceb4bb0369f2030068189e3b3f58d2fbe
BSP c60ac2 pm_haptics_cfg.c
532f67aa7d04c9136c2f1198d129805825ef732e57ae4033efd21a546d0e337e
SDM670/XBL old pm_haptics_driver.h
f0f06e82a422ad846060d6e3bf76bca92102be973a11565a0a3423a6b6c98652
```

本輪的實作來源核對包括 byte identity、版本條件、field 定義與 actual caller。
GitHub code search 的未命中只用於描述搜尋範圍，公開資料是否完整仍有不確定性。
本文件的實機狀態依據為使用者提供的既有 survey。
