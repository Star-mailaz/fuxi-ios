# RTC → UTC boot-time handoff：唯讀準備 checkpoint

## 範圍與可交接結論

本輪只新增本文件；不修改 C、loader、ADT、測試、sync、kernel 或持久化格式，
不操作手機、不執行裝置工具、不取鎖、不 commit。目標是本機 iOS 16.7.16
20H392 / XNU 8796.141.3，不沿用 iPadOS 27 的 boot_args 長度。

最小入口已存在：主代理在既有 payload command line 放入唯一一組
`fuxirtcoffset=<非負十進位秒數>`，確認沒有 `fuxirtc=0`；重製 payload / boot artifact，
不必修改 kernel 或新增 ADT property。只有 Android UTC 與「同一個、仍持續
計數的 PMIC raw RTC」有可核對的配對樣本，才可以計算及沿用 offset。
研究開始時尚無 Android 配對結果；後續主代理已完成下列單次短測，數值不供其他裝置或未核對的日常開機沿用。

主代理後續 checkpoint（2026-11-16）：`rtc-calibration.py` 同期讀取 Android
UTC 及同台 rtc0，得到 raw=39432、offset=1794782947、UTC=1794822379。
host 採樣區間為200ms，前後 UTC／RTC counter 穩定；建置及開機前再次讀取
live counter／UTC，要求 offset 差不超過2秒、counter 不倒退。
第21趟暫時開機在 `native-hw000rtc-calibrated-boot-1/boot.log:203–204`
記錄 raw=39569、epoch=1794822516、calendar readback=1794822516.000002。
這支持本台本次 sysfs→raw→calendar 換算；尚未證 UI／時區、長時間走時、
sleep/wake 或冷啟動 retention。舊 MKB 持久化1970 timestamp 沒有改寫。
本機 helper 最大接受一小時校準紀錄，且每次暫時開機前重新核對 Android
live UTC／counter；這是已實作的監督式短測政策，不是 kernel expiry 或
已部署的日常校時方案。

這是受監督、單次短測的準備方案，不是具備 reset / expiry 防護的完成實作。
現有 kernel 只檢 epoch 範圍，不能驗證樣本年齡、RTC 身分或 continuity。
任何資料缺失或不一致，現有 helper 拒絕建置或開機；若另做無校時診斷，
才使用明確的 `fuxirtc=0`，不把它加入成功校時候選。
既有程式的 enable 預設其實是 1，本輪沒有把 production 改成 default-off。

## 已有實際證據

`work/Codex-Xiaomi13-GPU-20261109/native-hw000batpause-hap-boot-1/boot.log`
第 197–198 行：`apid=53/ee4 raw 68 94 00 00 counter=37992 offset=0 epoch=37992`，
被 sanity window 拒絕，沒有設 calendar。第 630、640、662、672 行 MKB
session create/login timestamp 仍為 `1970-01-01 00:00:48 +0000`。
這是該趟 kernel calendar 未校正的證據，不是 RTC 永久保持或 MKB 根因證明。
不能把這個舊 `37992` 直接與稍後 Android `date +%s` 相減；兩者不是同期樣本。

## 本機 owning source 與 primary source

以下本機位置相對 `ksrc`；遠端固定到 source tag / commit，不引用移動分支。

| 原碼／精確位置 | 已核對的行為 |
| --- | --- |
| `xnu/fuxi-h1/fuxi_keys.c:66`、`:242` | SID 0 / PPID `0x0061`，讀 `0x6148..0x614b` 四個 little-endian bytes；最多兩輪 carry 檢查。沒有 RTC data/control 寫入。 |
| `xnu/fuxi-h1/fuxi_keys.c:272`、`:292`、`:299`、`:304` | unsigned offset；64-bit 加總；只接受 inclusive `[1700000000,2200000000]`；以 `clock_set_calendar_microtime(epoch,0)` 設 calendar，再讀回。 |
| `shim/fuxi-loader/loader.c:12`、`:45`、`:128`、`:178`、`:200` | payload v1 command line 608 bytes；`boot_args.CommandLine` offset 108；驗最後一 byte 是 NUL；ADT 與 command line 分開複製。 |
| `tools/mkpayload.py:64`、`:326` | 8796 使用 608-byte command line；v1 會靜默截到 607 bytes，不能依賴它拒絕過長輸入。 |
| `tools/mkadt-fuxi.py:159` | 既有 `/chosen` firmware / identity / root props；本輪查無現成 RTC UTC offset 消費入口。新增未知 ADT property 不會取代既有 bootarg。 |
| `../ram-source-reference/xnu-8796.141.3/pexpert/pexpert/arm64/boot.h:26`、`:69` | actual 8796 header 的 `BOOT_LINE_LENGTH=608` 與 `CommandLine[608]`。 |
| [Apple clock.h:49–58、161–163](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/kern/clock.h#L49) | LP64 `clock_sec_t` 是 unsigned long；setter 的 microseconds 類型是 unsigned int。 |
| [Apple bootargs.c:191–196、362–383、410–482](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/pexpert/gen/bootargs.c#L362) | `PE_parse_boot_argn` 讀 `PE_boot_args()`；4-byte 結果經 int32 cast 寫回，支援負號／其他 radix／suffix，並非 unsigned decimal validator。 |
| [matched OEM rtc-pm8xxx.c:70–105、234–246、523–551](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/7fad87dc178d09489b74a714e4a525d56f546855/drivers/rtc/rtc-pm8xxx.c#L523) | `qcom,pmk8350-rtc` 對應 ctrl `0x6146` / write `0x6140` / read `0x6148`；read_time 將 raw secs 轉成 calendar，該 driver 路徑未加 nvmem UTC offset。這不證明目前 Android binary 正是此 build。 |
| [同 commit RTC sysfs.c:32–75](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/7fad87dc178d09489b74a714e4a525d56f546855/drivers/rtc/sysfs.c#L32) | date/time/since_epoch 都是獨立 `rtc_read_time()`；since_epoch 轉成 epoch 秒，不是「系統目前 UTC」別名。 |
| [同 commit RTC interface.c:23–43、84–103](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/7fad87dc178d09489b74a714e4a525d56f546855/drivers/rtc/interface.c#L23) | class 層有 `rtc_add_offset()`，在 driver read_time 後可能加入 `rtc->offset_secs`。所以只看 pm8xxx driver 或 sysfs 名稱不能認定 since_epoch 等於 raw counter。 |

已讀 source 的 SHA256（遠端為回應文字 UTF-8、保留其原始換行）：

| source | SHA256 |
| --- | --- |
| 本機 `fuxi_keys.c` | `081bbbf41718e0949f366875fb6a24a21bf9e93d21e24ed5df93e1d25750c794` |
| 本機 `shim/fuxi-loader/loader.c` | `1cfff775f0507013de14d6a69d348ae66f42cafb78d52e5994dc71c2a3b6254e` |
| 本機 `tools/mkpayload.py` | `0e0fd0f0e8aace130165fa80736531457fff3706d658de2394d9e3522026cece` |
| 本機 actual `arm64/boot.h` | `efdfec46319cb147297682a8faebbe02873f845261b57f7511ab8e15c13ef3439` |
| matched OEM `rtc-pm8xxx.c` | `08e429b1fdded506f8e76b231f3b5ecfe1fc5e60f7326daf0f05a1fc9f6bcc8f` |
| matched OEM `drivers/rtc/sysfs.c` | `3f6d2bad461759e3c09ac047c74ff3eef15c114485d257439f51e6ea3d88fae9` |
| matched OEM `drivers/rtc/interface.c` | `90381150e8b0b9cfafa9f77d243f132bd71642f20603c9de63b70f5f22dcfe68` |
| Apple `osfmk/kern/clock.h` | `a2657effae6e918f73f815d9c53e73054cd0a716a38a3ccd77b71050e957afe6` |
| Apple `osfmk/kern/clock.c` | `001630fcf2089f7f8df7c39ee79f8ba9279b84aa06ec5d8883b016eb15fdc5b1` |
| Apple `pexpert/gen/bootargs.c` | `1431f1f8aacae240b87bd29cd91905784c968f8014784201b3ed862bdb1b4ed9` |
| Apple `iokit/Kernel/IOPlatformExpert.cpp` | `94a5bd0e0ae79f0deb504fb84cc186dec00bd6dd483bfce6c7c5ce20284533e3` |

## 主代理唯讀取樣與 offset 計算

1. 由主代理在 Android 原本授權的唯讀流程取得 rtc0 的 `name`、device/driver
   路徑與 compatible／實際 kernel provenance，以及
   `/sys/class/rtc/rtc0/{since_epoch,time,date}`、`date +%s`、`/proc/uptime`。
   可記 `/proc/sys/kernel/random/boot_id` 識別 Android session；它不證明 PMIC
   continuity。這些值由主代理擷取，本 worker 沒有執行任何手機命令。
2. RTC 秒數 R 的讀取前後各取 system UTC 整秒 U0/U1 與 uptime P0/P1；
   留存原始輸出／讀取順序／host UTC／artifact lineage。再取第二組。
   建議每組 bracket ≤1 秒、兩組隔 2–5 秒；這是採樣政策，不是硬體保證。
   若 UTC 跳變、RTC 不增、增量不符 uptime 或輸出失敗，拒用。
3. 必須先證明 R 就是 SID0 `0x6148` raw secs，或有已核對且適用該 Android
   build 的 class/driver offset 逆轉。若 since_epoch 已是現代 epoch，但 XNU
   raw 仍很小，列為 mapping blocker，不能用 `U-R≈0` 或猜 nvmem 修正。
   `/proc/uptime` 是 AP boot elapsed，不是 RTC 原點，也不能代替 raw counter。
4. 算式是 `O = AndroidUTC_at_R_sample - raw_secs_at_same_sample`，不是 timezone
   差；`date +%s` 是 Unix epoch，不能另加 UTC+8 或 DST。整秒 read 量化與
   順序誤差需保留：保守單組 candidate interval 可取
   `[U0-R-1, U1-R+1]`，兩組應有交集；沒有交集就不給 O。
   這只能界定取樣誤差，不能證明 Android UTC 已可信同步。
5. host 用寬整數檢 `0≤O≤4294967295`、預期下一次 raw+O 在既有 sanity window，
   然後輸出純非負十進位，不帶正負號、hex、suffix 或小數。負 offset 或
   不可表示 offset 不支援，不能利用 parser cast wrap 繞過。
6. offset 與 source/sample metadata 留在 host 的該次 boot artifact 旁；整條
   command line UTF-8 長度 ≤607 bytes、兩個 RTC token 各唯一、未遭截斷。
   payload 是持續攜帶 O 的既有入口；不需要把每次 UTC 秒數硬編 kernel。

若 RTC 在 reboot 期間仍以一秒／秒增加，`raw_new + O` 會自動包含 reboot
耗時，不再另加 `/proc/uptime` 或 host elapsed。若只有前趟 raw，沒有同期
Android raw/mapping，最小入口雖存在，數值校正仍 defer。

## Continuity、reset、過期與持久化界限

- 「PMIC keeps this across reboots and power loss」是 `fuxi_keys.c:270` 現有
  註解，不能升格為本台已驗證 retention。RTC disable、PMIC reset、失電、
  Android／firmware 寫時鐘、32-bit wrap、換裝置或不同 RTC driver 都使 O 失效。
- AP reboot 不等於 RTC reset，也不證明沒有 reset。每次 Android 接續取樣
  都重新核對身分與 counter 增量；冷啟動、電池斷接或 UTC 被校時後取消舊 O。
  RTC 停走／漂移會讓時間逐漸錯誤；offset 不修復振盪器或 retention。
- 研究初始建議第一趟 artifact 在10分鐘內單次使用；後續實作政策為最多
  一小時，且每次開機前重新核對 live UTC／counter，如前述 checkpoint。
  不作無期限／日常 artifact；此期限是 host verifier 政策，不是 kernel TTL。
- reset 後 `raw_new+O` 仍可能落在 2023–2039 sanity window，kernel 仍會接受；
  只帶 O 的現成入口做不到 boot 前自動 fail-closed continuity 檢查。若要求
  無人值守、多次 reboot 或冷啟動可靠，需另行分配帶 raw reference、expiry、
  provenance 與拒絕規則的 consuming code；本轮只列 gap，不新增抽象驅動。
- 不借用 mtd 當 UTC mailbox：`xnu/fuxi-unixnu/sweet_ufs.c:1257` 的
  `fx_log_header` 是 SWEETLOG v2，沒有 UTC/raw/expiry 欄位；`:1332` 每次 flush
  `bzero` 整個 header block，再寫 header 與 byte 2048 stamp。旁邊空白 bytes
  不是穩定保留区。`:231`、`:240` 限制 stamped 2049-block log area；既有 log
  授權不代表 RTC mailbox ownership。禁止新 mtd/nvmem/MMIO data 寫入。

## Calendar setter 不是單純記憶體寫入的假設

[Apple clock.c:718–727、826、843–844](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/kern/clock.c#L718)
明確呼叫 `PESetUTCTimeOfDay()`，並發 calendar change/set notification。
[IOPlatformExpert.cpp:1375–1380、501–503、400–402](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/iokit/Kernel/IOPlatformExpert.cpp#L1375)
會 dispatch 到 `gIOPlatform->setUTCTimeOfDay()`；base class 最終
`setGMTTimeOfDay()` 是空函式。本機
`xnu/patches/0016-sweet-device-tree-platform-expert.patch:46` 的
SweetPlatformExpert 沒有覆寫這些 setter，本輪 scoped source scan 亦未找到
新的覆寫。這支持現有 base path 不寫 PMIC，但不能代替 actual linked class /
override 核對；主代理須確認沒有另個 platform clock service 寫硬體。
本文件不建議 Android RTC set_time、alarm/control enable 或任何 PMIC 寫回。

此外 `clock.c:1297` 的 wake 路徑可能再讀 platform UTC；boot-time 單次設
calendar 不等於 suspend/resume 或 cold boot 已橋接，另列未驗證。

## 下一趟成功判準與 PowerLog 邊界

- 主代理保留 fresh Android 配對資料、唯一 O、完整 bootarg 與實際 artifact
  SHA。下一個 XNU log 必須有同 RTC 身分的 raw_new、offset=O、epoch=raw_new+O
  與 `clock set, now=...`，而非 sanity rejection；counter 增量須與可信 host
  elapsed 符合，差值依取樣／oscillator 誤差預算判定，不只看年份變現代。
- 再驗 userland UTC、後續短時間前進、launchd/MKB 新 session timestamp
  與 host UTC 一致；timezone 顯示另驗。舊持久化 MKB timestamp 不會因 setter
  自動改写；看新 session，不以舊值單獨判失敗或重寫既有資料。
- 正確 calendar 是 epoch-based log／跨 boot 時序分析的必要輸入之一，不
  證明 PowerLog 已可用，也未找到 actual 20H392 PowerLog 的 primary caller
  證據可宣稱「1970 是其唯一 blocker」。需另驗 PowerLog service、資料庫、
  power source／IOReport、clock-change handling 與事件落盤。
- Apple `IOPlatformExpert.cpp:517–519` 的 kernel `PMLog` 使用
  `clock_get_system_microtime()`，不是 calendar。不能把所有 PM logging 都
  當 UTC 依賴；也不能用 RTC 校正冒充電池／PowerLog owner 功能完成。

本 checkpoint 的驗證是 source／document consistency，不是 host emulator、
kernel build、RTC 自主 retention、手機寫時或 PowerLog 實測。
