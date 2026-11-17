# Fuxi BDF 唯讀 inventory 與選擇證據

## Checkpoint 與界線

工具 `tools/fuxi-wlan-bdf-inventory.py` 僅讀取明確指定的本機 regular files，
輸出 JSON 至 stdout，不掃描手機、不寫入輸入檔、不提取／安裝／自動選 BDF。
測試 `tools/test-fuxi-wlan-bdf-inventory.py` 直接 import production helpers。

主代理已確認 `work/statusbar-fix/inspect-radio-assets-20261116-1436/assets.json`
的 NBD/HFS 唯讀盤點成功。本 worker 隨後核對 manifest、`guest.log` 與
`mapping.txt`；manifest SHA-256 為
`8935a695c4ced61a125f33bb0342b3c694a9afedf28b67dbef6772ad4a62125c`。
guest log 有 mount/success receipts，並明確記錄
`ROOT_DIRECTORY {"path": "/usr/local/share/fuxi/wlan", "exists": false}`。
這是該次 guest root 目錄不存在的觀察，不是猜測主機缺檔名。

Capture time 為 `2026-11-16T14:36:55.240799+08:00`，root 為
`/data/gsi/codexnative1108b/codexnative_root_1108b.img.0000`、20 GiB；
mapping receipt 記錄 inode 199819／39 extents、FIEMAP/DM/pin checks 通過。
manifest 只有 `/usr/sbin/BlueTool` 與 `/usr/sbin/bluetoothd` 兩份紀錄，
沒有 WLAN payload。工具不把它們送進 BDF parser，也不把 synthetic parser
fixtures 升級成實物。後續 Android 1447 receipts／1450 六檔已成功交接並核對，
結果見下文；15:32 主代理成功 staging/readback 已在 M3 收尾段更新。

之後取得真正 BDF 實物時，由主代理傳入確切檔案路徑，並將輸出 hash 與
capture manifest 逐一比較。`--provenance` 是必填來源紀錄，不是校正適配證明。

```powershell
python -B D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc\tools\test-fuxi-wlan-bdf-inventory.py -v
```

後續盤點成功後的呼叫形式：

```powershell
python -B D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc\tools\fuxi-wlan-bdf-inventory.py --provenance $successfulCaptureRecord $capturedBdfPaths
```

兩個變數必須由主代理的成功盤點設定；沒有預選檔案。輸出列出具體檔名、
整檔 SHA-256／bytes、容器 name／IDs／data offset／data SHA-256 或 raw 格式
缺口，永遠保留 `selected=false`、`calibration_compatibility=unverified`。
CLI 不解析未知形狀的手機 manifest、不執行 manifest 中任何命令。

### Receipt-only 主機檢查

```powershell
python -B D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc\tools\fuxi-wlan-bdf-inventory.py --provenance root-assets-1436 --capture-manifest D:\xiaomi13\fuxi_ios\work\statusbar-fix\inspect-radio-assets-20261116-1436\assets.json
```

這個入口只讀 manifest（最多 256 KiB）與其 capture 目錄內的 guest log
（最多 1 MiB）。它核對成功 markers、版本、目錄 boolean、FILE_SENT/count
與 manifest 一致性；拒絕重複 JSON attrs／receipts、目錄缺席卻聲稱有 WLAN
檔案、缺 required evidence、guest-log 路徑逃逸與過大輸入。它不打開 manifest
列出的 payload，不替其 payload hash 背書。1436 結果為 `files=[]`、
`wlan_directory.exists=false`、`wlan_files_recorded=0`、`payload_files_opened=0`。

## 已核對 primary 格式

來源是 Linux v6.12 [ath12k hw.h](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/hw.h#L91)
與 [core.c](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/core.c#L252)。
此工具是獨立有界格式檢查，不複製 kernel loader／selector 實作。

| 層級 | 格式事實 |
| --- | --- |
| Magic | `QCA-ATH12K-BOARD` 加 NUL，共 16 bytes；不是 `ATH12K-BOARD` |
| TLV header | little-endian u32 id、u32 payload length，payload 後補至 4-byte 對齊 |
| Top-level 0 | BOARD；可重複出現不同具名 records |
| Top-level 1 | REGDB；與 BOARD 分別建立 name namespace |
| Nested 0 | NAME，使用 TLV 長度，不含 NUL；可有多個不同 aliases 共用下一份 DATA |
| Nested 1 | DATA，雜湊的是未含 padding 的確切 payload |

本工具的保守 policy：拒絕未知 TLV、非零 padding、截斷、u32 對齊溢位、
重複同 kind/name、重複 DATA、DATA 前無 NAME、DATA 後再出現 NAME、空 DATA、
缺 NAME/DATA、無 BOARD record。不同 aliases／不同 top-level BOARD 不視為
duplicate。Linux 本身會略過某些未知 IE／padding；這裡的嚴格拒絕不是宣稱
它們都必然被 firmware 拒絕，而是避免 inventory 靜默忽略不懂的內容。

容器最多 16 MiB、1024 records、8192 TLVs、每 record 64 aliases；name 最多
512 bytes；每份 DATA 最多 1 MiB。後者對齊現行 XNU BDF file bound，其他是
主機 inventory policy，不是 firmware 容量規格。只有兩層解析，沒有 recursion。
regular-file 單次 read 有 size bound、identity／mtime／size 前後檢查，拒絕
symlink／Windows reparse file。所有 count／offset／length 都先檢查再切片。

## Board name 與 Android raw 格式

Linux [core.c 的命名](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/core.c#L162)
有兩種 BOARD key：

```text
bus=<bus>,qmi-chip-id=<decimal>,qmi-board-id=<decimal>[,variant=<string>]
bus=pci,vendor=<4hex>,device=<4hex>,subsystem-vendor=<4hex>,subsystem-device=<4hex>,qmi-chip-id=<decimal>,qmi-board-id=<decimal>[,variant=<string>]
```

工具要求 BOARD 的 bus 與兩個 QMI IDs，PCI 四個 IDs 一起存在；REGDB 另接受
`bus=pci` 形式。拒絕重複／未知／空 attributes、控制字元／NUL、超長名字、
部分 PCI／QMI 欄位，以及把 `0xff` 當 decimal QMI ID。這些 IDs 僅是容器
name 的宣告，不是本機 endpoint／OTP 的新觀察，不觸發任何 matching／fallback。

`variant` 也不能由顯示 panel 推定。Linux v6.12 的
[SMBIOS BDF extension](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/core.c#L608)
有自己的驗證及來源；不能把 Xiaomi 的 country/project 名稱直接搬成它的 variant。

Linux [qmi.c](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/qmi.c#L2643)
只用 ELF magic 判定傳輸 type，否則送 BIN。CNSS 也直接下載檔案 bytes，
這兩份來源沒有提供 Android raw BDF 內部 board/chip/calibration ID 的穩定偏移。
因此工具僅對 ELF32／ELF64 wrapper 做 generic header、endianness、table／segment
bounds 與 segment hashes 檢查，最多各 128 headers，不 map／執行內容；不宣稱
已理解其校正 payload。ELF section table 僅驗範圍，不解碼其 payload。
未識別 raw BIN 僅標記 `opaque-raw-not-schema-verified`／hash，IDs 為 missing。
已知 magic 或 `.elf`／`board-2.bin` 解析失敗，不會自動退回 opaque。

## Fuxi CNSS filename 分支

已直接核對 Xiaomi [CNSS qmi.c 固定 revision](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c#L622)：

| CAP／type 分支 | 已發布規則，非本輪選擇 |
| --- | --- |
| ELF board ID `<0xff` | `bdwlan.eXX`；chip ID `&0x10` 分支使用 `bdwlang.eXX` |
| BIN board ID `<0xff` | 對應 `.bXX`，亦有 GF stem |
| ID `>0xff` | `bdwlanHH.eLL`／`.bLL`，程式只取 low 16 bits；不可反推完整 u32 ID |
| ID `==0xff` | generic ELF／BIN；ELF 非 GF 才有 Xiaomi M2／M3／M11 country/project overrides |
| CAP board TLV 缺席 | [CNSS](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c#L531) 與 [ath12k](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/qmi.c#L2480) 使用 default `0xff`；不是讀到 OTP=255 |
| REGDB | Xiaomi 明確使用 `regdb_xiaomi.bin` |

工具從檔名產生的 `board_id_hint` 只是該名稱的 low-16-bit 編碼線索；GF stem、
M3/global 名稱亦只是 filename hints。不能據此補出 live validity、認證校正、
當前載入選擇或 `--bdf`。不翻譯／移植 CNSS selector。

## 現有本機證據與不能合併的資料

既有 `wlan-w14.md` 保留 try13 的 supplied excerpt（chip/family 2/4、board 0、
SoC `0x40170200`、FW `0x1103006c`），也保留後續 board TLV absent 的 W15 結果。
`wlan-w16.md` 記錄兩趟接受 88,760-byte ELF BDF 與 MODE timeout。
這些文件不是本輪 raw boot capture；本輪未在既有搜尋範圍找到可重新核對
CAP validity／Android 實際 filename request 的 raw log，也沒有 try16 原始完整參數。
不得把 board 0 與 absent→default 255 合併成同一份 live selector。

本輪讀到的是既有 `work/hw-survey/fuxi-live-20261116.dtb` 主機快照，SHA-256
`2d7e97ea52bf67a79ef7b99487131a41bd87fc0ab774983ce62bfb9fa79fb9fa`。
其 model 是 fuxi，AP `qcom,board-id` 為 `<0x10008 0>`；這不是 WLFW board ID。
`/chosen/bootargs` 有 `hwid.hwid_value=589824`、`hwid.project=2` 與
`msm_drm.dsi_display0=qcom,mdss_dsi_m3_38_0c_0a_dsc_cmd:`，沒有 WLAN BDF filename，
亦沒有證實 `get_hw_country_version()` 的回傳值或 Global BDF 適配。
CNSS 使用的 owning hwid decoder／country runtime export 路徑在本輪未核對到，
故這兩個 numeric bootargs 不能自行譯成 M3/Global。

DT 的 `/soc/qcom,cnss-qca-converged/chip_cfg@1/supported-ids` 為 `<0x1107>`；
`@0` 為 `<0x1103>`。這是支援表，不是 live PCI ID；不能把 `supported-ids`
或 AP board ID 拿來代替 WLFW CAP。參考 sheng manifest／唯一候選檔案／成功
BDF_DOWNLOAD 或 FW_READY 同樣不證明 Fuxi RF 校正適配。

## 最小 live 唯讀取證：由主代理統一操作

worker 不執行以下裝置操作。主代理可先使用現有 read-only logs/captures，
不為本工具重開機、重新開 Wi-Fi 或寫入 debugfs／dynamic_debug。

| 需要的欄位 | 確切讀取／比對入口與缺席政策 |
| --- | --- |
| 同趟 CAP 成功與 presence | Android 既有 `dmesg`／`/dev/kmsg` snapshot 的 `Target capability:`、`fw_version:`；若 debug log 未留下，列 missing，不啟用 logging。XNU 用完整 `FUXI WLAN: W12 cap: valid ...` raw boot line 加 CAP reply result/error |
| chip/family/board/SoC/FW identity | 上述 CAP snapshot：chip/family、board TLV present/absent、soc_id、fw_version、timestamp/build ID；不能用 PHY_CAP board ID 替代 CAP board ID |
| XNU CAP validity 解讀 | 現行 production `valid` mask：chip TLV `0x10`=`0x2`、board `0x11`=`0x4`、SoC `0x12`=`0x8`、FW/version `0x13`=`0x10`、build `0x14`=`0x20`；缺 board bit 時顯示的數值 0 不是有效 board 0 |
| endpoint major／active AMSS | XNU raw boot 的 `FUXI WLAN: TCSR_SOC_HW_VERSION ... major ... firmware ...`；對該確切 root firmware path 的 bytes/SHA-256。SoC CAP ID 不能替代 endpoint TCSR major |
| Android 真正 requested BDF | 既有 `dmesg` 的 `Downloading BDF: <requested-name>, size: <bytes>` 加同趟 download 成功／失敗；[primary qmi.c:911](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c#L911)。此名稱可能含 [CNSS prefix](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/pci.c#L5159)，不得只取任意同 basename 檔案 |
| request-name → 實際檔案 | 唯讀 `/sys/module/firmware_class/parameters/path`，以及主代理已成功 root/firmware capture 中 request path 的實體／symlink 解析及 SHA-256；未找到解析證據則 missing，不猜 `/vendor`／`odm` 路徑 |
| PCI vendor/device/subsystem IDs | 唯讀 `/sys/bus/pci/devices/*/vendor`、`device`、`subsystem_vendor`、`subsystem_device`，先辨識實際 endpoint BDF，再記錄完整 sysfs path；不預設 domain/bus number |
| Xiaomi fallback 分支 | 唯讀 `/proc/cmdline`、`/proc/bootconfig`，與 owning hwid decoder 的 project/country enum／回傳值證據；若有同趟 Android 實際 requested BDF 證據可直接核對，不必猜 enum |
| native-root staging 關聯 | 成功 capture manifest 的 root identity/time、`/usr/local/share/fuxi/wlan/<確切檔名>` 的 bytes/SHA-256；與 actual requested／container DATA hash 分別比較 |

只要缺同趟 CAP validity／FW identity，或缺 actual BDF selection + exact content
的來源鏈，結果維持 missing，仍可交 inventory checkpoint。真實選擇的最小
來源鏈是「Fuxi 同趟 firmware/CAP → 實際 request／已核對平台 selector →
確切 file／container DATA hash → 此次 native-root staging」，不是取唯一檔案。
此鏈建立後仍需受控硬體驗證 RF/calibration；工具不把它提升成已連線／已校正。

## 真實 Android 1447／1450 checkpoint

已核對 `work/adsp-battery/android-radio-survey-20261116-1447/manifest.json` 與
identity/capability bytes/hash；manifest SHA-256 為
`de80c002d89f835f7143280ae41207fc8d4c0e4e5eadea8bd3c869f7b0847605`。
CAP receipt SHA-256 為
`b89e16715038be5f50364867b611770e2511d877dc17878ea1775d78670b9cbe`。
identity 的 device 是 fuxi，記錄的 kernel 為 Android 5.15.178；這與歷史 W15
的 upstream firmware 測試不是同一份 firmware/boot，不能聲稱復現 try16。

| 真實 Android receipt | 結果 |
| --- | --- |
| Active FW request/resolver | `kiwi/amss20.bin` → `/vendor/firmware_mnt/image/kiwi/amss20.bin` |
| CNSS normalized CAP | chip `0x2`、family `0x4`、board `0xff`、SoC `0x40170200`、OTP `0` |
| FW identity | `0x1003003a`、`2025-11-06 04:51`、hwid bitmap `0` |
| Build ID | `QC_IMAGE_VERSION_STRING=WLAN.HMT.1.0.c2-00058.3-QCAHMTSWPL_V1.0_V2.0_SILICONZ-1.103297.3.120264.11` |
| First download | type 4、`kiwi/regdb_xiaomi.bin`、24,278 bytes，ueventd resolver 指向 image/kiwi 同名檔案 |
| Board download | type 1、`kiwi/bd_m3.elf`、88,728 bytes，同樣有 explicit request/resolver/download receipt |
| Host BDF | `HW_XPA=1`、`CalDB=0`，不當作內嵌校正 ID 或 RF 適配證明 |
| M3_INFO log | printed va `0`、`pa=0xa2a00000`、`size=0x4928c`（299,660 bytes）；不能直接推定 CPU 實體位址或 NULL va |

後面的 WMA `Board id: 0` 不是 CAP board ID，工具不將它覆蓋 CNSS normalized
CAP。CAP log 沒有 optional-valid flags，故 `board_tlv_presence` 保持
`not_logged_CNSS_normalized_value_only`；不把 `0xff` 譯成已讀 OTP=255。
現在的 BDF 依據是 explicit Android request，不需靠唯一檔案或猜 project/country。

已核對 `work/adsp-battery/android-wlan-assets-20261116-1450/assets.json` 與六份
真實本機 bytes/hash，manifest SHA-256 為
`ef107f3969c4ca9800d99907b56f42124048c30212f5c94d38c33082bd632a2f`。
主代理記錄 before/after phone hashes 通過；本 worker 做的是本機 payload hash
核對，沒有重讀手機。manifest 的 `root_staging_verified=false`，不可提升成
已安裝到 iOS。

| 本機資產 | bytes | SHA-256 |
| --- | ---: | --- |
| `amss20.bin` | 5890112 | `cc25a432aa19e71e8503b424c9a52be952f6dd1d2f93f38f1ff754f748d97667` |
| `amss.bin` | 7458880 | `c42e06f534c07ffdaec3b265ff1e38b312741e35eb5fb21b5ca77995fab8d688` |
| `bd_m3.elf` | 88728 | `c2758deed972b5ee52c425936b498f81e93458147ad69780688d0bfd75db5c06` |
| `regdb_xiaomi.bin` | 24278 | `26fc3ac9bebd438cd3d4731680c1cc6925cef5e7cadcb3a3e9b0986c900cd6d4` |
| `Data20.msc` | 1455782 | `e5afcef07fd98e7c0785527a88fc6686c23d258ac2476992efde828b3ab2ee36` |
| `Data.msc` | 1455171 | `fb63d326a067f11926ecb3ac4a1cf48cdbcef5f8301e1e222d62af98941a7fd3` |

`amss20.bin` 的實物 bytes 含完整上述 build ID。`bd_m3.elf` 不是 board-2
容器：已通過 ELF32 little-endian wrapper，ET_EXEC、EM_ARM=40、一個 program
header、五個 section headers；LOAD segment offset 1024、filesz/memsz 87040，
其 SHA-256 為 `0718b7ee9761dcbd34cd0e77f923a15b68657b377c89a76ae17b9b45e56a71e9`。
這是格式及來源核對，不宣稱已解碼 raw calibration schema；BDF 下載仍使用
整份 88,728-byte ELF，而不是該 LOAD segment。沒有 board-2 實物；相關 tests
仍是 synthetic fixtures。

### Android receipt / assets 主機入口

```powershell
python -B D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc\tools\fuxi-wlan-bdf-inventory.py --provenance actual-android-1447-1450 --android-survey-manifest D:\xiaomi13\fuxi_ios\work\adsp-battery\android-radio-survey-20261116-1447\manifest.json --android-assets-manifest D:\xiaomi13\fuxi_ios\work\adsp-battery\android-wlan-assets-20261116-1450\assets.json
```

Production helper 核對 timestamp/order、唯一 CAP/FW identity、REGDB→BDF type、
prefix/request/sysfs/resolver/download path 與 size、HostBDF/M3 metadata；拒絕
duplicates、missing required attrs、overflow、路徑逃逸、file hash/size 或 wire
type/ELF magic 不符。不執行 `records.command`。Android survey 僅讀 identity/CAP
紀錄，Android assets 批次最多 32 MiB、64 files、每檔 16 MiB。實際 BDF 才跑
format helper；Data*.msc/AMSS 不誤送進 raw-BDF parser。

`Downloading BDF` 在 primary source 中位於 QMI segment loop 前，因此工具不
宣稱逐段 ACK 已直接觀察；HostBDF/M3 的後續進度與 published
[main.c ordering](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/main.c#L547)
一致，可記錄 `host_progressed_to_m3=true`。工具永遠不選 XNU `--bdf`、不 boot、
不 stage，Android manifest 的 staging 宣告也不替代 guest-root staging 驗證。

## M3 critical gate：primary 來源與安全取出路徑

### 15:32 收尾：staging gate 已解除，不重做提取

主代理已確認 same-device 五份 OEM assets changed-block staging/readback
成功。本 worker 只讀核對
`work/statusbar-fix/run-wlan-oem-assets-crlf-20261116/receipt.json`，SHA-256
`e8b258ce12d02327ec0878dba7e8f592c755f21a9a1abcf948a10033bb4f5627`：
state 為 `written`，五份 runtime file bytes/hash 均與先前實物一致，包含
`/usr/local/share/fuxi/wlan/m3.bin` 的 299,660 bytes／
`bab0d04bf693476d574e721296426e5701c3c6e96438e76ee63f0ab82ffd164f`。
`input-receipt.json` hash 與 receipt 所指一致；guest log 有五檔 hash OK、
`WLAN_STAGE_RESULT`、`FAST_WLAN_STAGE_SUCCESS`／`GUEST_OK`，write log 有
`PRE_OK 9`／`WRITE_OK 9`。本 worker 未重新操作手機或重做 staging/readback。

主代理回報 15:32:22 的 `native-hw000w18-oem-assets-boot-1` 已接受 BDF
全部 15 segments，M3 299,660 bytes accepted、reply=0；這是本趟主代理
硬體觀察，worker 未在本次交接另讀 raw boot log。它證明該趟接受進度，
不宣稱已取得 firmware loaded-buffer hash、RF/calibration 適配或 MODE 成功。
**先前 M3/staging 缺口已解除，不再拿歷史 missing 或 inventory 工具的保守
`m3_payload_hash_verified=false` 阻塞這趟測試。** MODE/root cause 由主代理追。

本輪 M3 ELF／provenance 工作收尾：兩份 inventory/tests source 不再修改，
只追加本段歷史更新；三檔仍由主代理統一同步／提交。沒有發布私有 firmware。

### OEM FW_READY timeout：本機 raw 與 primary 比對

後續已只讀核對本機
`work/adsp-battery/fuxilog/20261116-153920/console.txt`，307,228 bytes，
SHA-256 `3e54202b8794e1d9d16cdc677384f05297c2401892a4c0e77db2484a9195ede7`。
Raw `:1242–1253` 記錄最後 BDF txn 24 result/error 0/0、額外 TLV
`0x10 bytes 8`、全 15 segments 完成、M3 299,660-byte IOVA `0xa1e80000`
mapped、txn 25／msg `0x3c` result/error 0/0；`:2617` 是 W14 FW_READY
10-second timeout。這份 raw 的 QMI indication 行只見 REQUEST_MEM `0x35`
與 FW_MEM_READY `0x37`，沒有已解析的 `0x38`／premature-ready 行，也未見
WLAN INI/CFG/MODE 送出。它不是「MODE reply 卡住」的同一階段。

| 已證 source 差異／一致性 | 對下一趟判斷的意義 |
| --- | --- |
| Primary CNSS HOST_CAP `qmi.c:295–339` 會有 host_build_type，視 bus queries 結果帶 DDR IOVA range、視 wake IRQ 帶 wake_msi；現行 XNU `wl12_host_cap()` 沒有 TLV `0x20`／`0x1f`／`0x11`，另明送 `0x13=0x0e`／`0x1c=0` | 這是最具體的 pre-FW_READY host-contract 差異；公開 source 不等於 installed Android 的逐 byte request，不猜 host_build enum／wake data 或移植 Android DMA handle |
| CNSS KIWI MLO 明設 capable=1、one chip/two links、max peers=32；XNU default variant 0 亦使用 two links，variant 2 才省略 MLO | `fuxiwlanmlo=2` 是已核對 selector 的單變量 A/B；不是復現 try16，也不是還原公開 CNSS default。應核對下一份 raw 的 MLO omitted 與是否收到 `0x38` |
| Primary CNSS M3_INFO 後再呼叫 QDSS config download；XNU M3 reply/TX drain 後直接等 readiness | 真實順序差異，但 CNSS 上層忽略 QDSS call return；缺它致 timeout 尚未證。不在這份 worker patch 自動加 tracing／memory dump／額外 QMI experiment |
| Primary CNSS 將 `FW_INIT_DONE=0x38` post 成 driver FW_READY event；XNU 同樣等 `0x38`，只記錄 `0x21` | 不要改成接受 `0x21` 來掩蓋 timeout。CNSS callback 不受 XNU 的 M3-stage gate 限制，但本份 raw 未見可證的提前 `0x38` 被丟棄 |

Primary links：[HOST_CAP/MLO](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c#L244)、
[HOST_CAP EI TLV IDs](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss_utils/wlan_firmware_service_v01.c#L3203)、
[M3→QDSS ordering](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/main.c#L552)、
[FW_INIT_DONE callback](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c#L2517)。

BDF reply 的額外 u64 是 `host_bdf_data` metadata，不是 rails vote。
[CNSS qmi.c:975](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c#L975)
使用 HW_XPA／CBC_FILE_DOWNLOAD bits；1447 actual Android 記錄 HW_XPA=1、
CalDB=0，XNU 這份 raw 只記錄 TLV 寬度，不能補出其值或稱六條外部 rails
未投票。Android `0xa2a00000` 來自 DMA handle，不是已驗 CPU PA，也不能因
XNU M3 IOVA 不同而宣稱配置錯誤。M3/staging 已交付，不重做 staging。

### 15:11 歷史交接：不等待手機也不降低 gate

本次主機重核對已交接的 1450 `assets.json`：仍為上述六檔，manifest hash
仍為 `ef107f3969c4ca9800d99907b56f42124048c30212f5c94d38c33082bd632a2f`；
沒有 `phy_ucode20.elf`／已驗證 M3 payload。本 worker 不輪詢 session 60004、
不判定鎖／手機狀態，也不推定另有未交接的導出已成功。

1447 `capability.txt:26–27` 只有 M3_INFO 起始及 metadata：
`pa=0xa2a00000`、`size=0x4928c`（299,660 bytes）。Primary `qmi.c:1029–1046`
在 `qmi_txn_init()`／`qmi_send_request()` **之前**印出這份 memory metadata；
所以此 receipt 不單獨證明 M3_INFO reply/ACK、loaded payload identity 或 CPU
physical mapping。JSON 明列 metadata 行號／時間與
`m3_info_reply_observed=false`，不將「已進入 M3 host path」升級為 reply 成功。

Primary `pci.c:47–51` 定義 `phy_ucode20.elf`／`amss20.bin`，
[`main.h:57`](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/main.h#L57)
定義 `FW_V2_NUMBER=2`；KIWI 的兩個 selector 都依 device major version 分支。
本趟 actual AMSS20 request 與該公開分支一致，仍不等同直接觀察 installed
selector inputs／source revision。JSON 的 M3 candidate 明列兩者未驗證；
candidate 不是自動選取或已載入檔案。

主代理最小下一項仍是**普通檔案唯讀導出**
`/vendor/firmware_mnt/image/kiwi/phy_ucode20.elf`：交接確切 host path、
Android source path、bytes、before/after phone SHA-256 驗證 receipt、local
SHA-256 與捕獲時間／device identity；保留同 bundle AMSS20 hash 關聯。
若既有完整 Android log 有該 file request/resolver，可一併交接；目前 filtered
CAP 不含此 receipt，不能聲稱有。相同 299,660-byte size 只能作 consistency。
不使用 `0xa2a00000` 作 `/dev/mem` 讀取位址、不觸發 memory dump、
不重命名 Data20 slices 為 M3，也不取 sheng 私有 firmware 替代。

現有工具可以對明確交接的 local file／manifest 做有界 hash inventory；
不能因此自動把 `m3_payload_hash_verified` 提升為 true。M3 來源核對與
native-root staging/readback 尚缺，**W18 保持禁止開機**。本次只修改三份
獨占 inventory／tests／本文件，沒有修改 driver／profile／sync／build／patch。

### 15:18 實物核對：staging input PASS，loaded identity 仍未證

已讀主代理明確交接的
`work/adsp-battery/android-wlan-m3-20261116-1518/assets.json`，manifest SHA-256
`feb5bd74650c68c20383e2e94c02e1a03382973b86c842003769f65d9914c572`。
Capture time 為 `2026-11-16T15:18:43.734895+08:00`；Android source 是
`/vendor/firmware_mnt/image/kiwi/phy_ucode20.elf`，與 primary candidate 一致，
`selection_evidence` 指向同一份已驗證的 Fuxi 1447 CAP receipt。主代理確認
before/after phone hashes；本 worker 獨立核對 local regular-file bytes/hash：
299,660 bytes，SHA-256
`bab0d04bf693476d574e721296426e5701c3c6e96438e76ee63f0ab82ffd164f`。

| Gate | 實際結果 |
| --- | --- |
| 傳輸完整性／manifest 關聯 | PASS；確切 source path、local bytes/hash、同份 CAP selection evidence |
| ELF 結構完整性 | PASS；ELF32 little-endian、ET_EXEC、machine 3、一個 program header、六個 section headers；header/table/segment/section payload bounds、section alignment/link/name-string bounds 通過 |
| M3_INFO size consistency | PASS；全檔 size 等於 actual `0x4928c`，不等同 loaded identity |
| 同台 AMSS20／公開 V2 selector 來源鏈 | PASS 作為 source-backed staging candidate；1450 AMSS20 hash/build ID 重核對通過、兩份 manifest 指向同 CAP；不宣稱 installed module revision 或 live selector inputs 已直接驗證 |
| Host staging input | PASS；使用整份 299,660-byte ELF，不提取 segment |
| Actual loaded M3 identity／M3_INFO reply | UNVERIFIED；現有 log 無 M3 request/resolver 或 loaded-buffer hash／reply receipt |
| Native-root staging/readback | MISSING；本 worker 不 stage、不操作手機，不將 manifest 的 false 改為 true |

LOAD segment 為 offset 4096、filesz/memsz 294912，SHA-256
`b30dbf0614b29c2cbcd90cabd93b6807c4ca7302dc36451c1da4f0ce465bf810`；
此 segment hash 僅描述容器，不能代替整檔 hash。machine 3 是 actual ELF header
宣告，不把這個 device firmware wrapper 當主機 executable 執行，也不假造 ARM
header；primary CNSS 路徑不依 e_machine 執行它，只 memcpy 全檔。

M3「缺實物／host hash」門檻已解除，**足以交主代理作 staging input**：整檔以
`/usr/local/share/fuxi/wlan/m3.bin` staging，再讀回比對上述全檔 bytes/hash。
Loaded identity 待證與 staging input 可用是不同 gate，不以同 size 單獨背書；
`m3_payload_hash_verified=false` 是現有工具的保守輸出，不否認本次 local hash
已核對。W18 開機仍須主代理滿足 native-root readback 與既有 loader／guard
門檻；本次沒有操作手機、發布 firmware 或修改 driver／profile／sync。

Primary [CNSS2 pci.c](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/pci.c#L4099)
的 `cnss_pci_load_m3()` 是可證的 ordinary-file 路徑：KIWI/MANGO major 2
使用 `phy_ucode20.elf`，其他 KIWI 版本使用 `phy_ucode.elf`；M3 名稱 `m3.bin`
是另一些 device IDs 的分支，不是 KIWI major-2 的 standalone filename。
prefix helper 加 `kiwi/`；當 M3 buffer 尚未有 va/size 時，先 request firmware，
再 `dma_alloc_coherent()`，`memcpy()` 完整 `fw_entry->data`，size 等於完整檔案
大小。沒有在此解出 ELF LOAD segment，也沒有讀 Data20.msc、AMSS segment。
[bus.c](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/bus.c#L120)
將 PCI bus 的 M3 load 送到這個函式，然後
[qmi.c](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c#L1023)
把 `m3_mem.pa/size` 送入 M3_INFO。

**最有證據的下一份唯讀導出：**
`/vendor/firmware_mnt/image/kiwi/phy_ucode20.elf`。
1447 已核對 hash 的 `firmware.txt` 列出這個 ordinary file，但 1450 六檔不包含
它；這是 15:11 的缺口，15:18 已由上述實物核對解除。主代理可
用原來的唯讀檔案導出流程，取此確切路徑並驗 before/after phone SHA-256；
不用 raw `/dev/mem`、不用有 trigger 的 debugfs、也不用 DT carveout memory dump。

### 為何不能拿 va=0／pa=0xa2a00000 當預載實體記憶體證據

CNSS M3 log 的 va 使用 `%pK`。
[Linux 5.15 vsprintf](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v5.15/lib/vsprintf.c)
明確有遮蔽並輸出 0 的路徑；因此 printed va=0 不證明 `m3_mem.va == NULL`，
也不證明存在 DT 預載。沒有讀／改 `kptr_restrict` 來嘗試揭露 kernel pointers。

雖然 CNSS `struct cnss_fw_mem.pa` 宣告為 `phys_addr_t`，這條 M3 路徑把它傳給
`dma_alloc_coherent()` 的 DMA handle 輸出參數，再送給裝置。
[DMA API](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v5.15/Documentation/core-api/dma-api-howto.rst)
明確區分 bus/DMA address 與 CPU physical address。既有 Fuxi DT 快照的 CNSS
IOVA pool 為 `[0xa0000000,0xb0000000)`，`0xa2a00000` 在其內；這支持 DMA/IOVA
解讀，卻不是已證實的 CPU 實體對應。不把它用作 `/dev/mem` 讀取位址，也不
把這個 Android DMA address 硬編成 XNU M3 address。

對該 DT 快照的 CNSS／reserved-memory 節點與屬性做限縮核對，沒有 M3 專用
預載 record；普通 CNSS memory-region／其他 panel/GPU Cortex-M3 名稱不能代替
WLAN M3 preload 證據。Published source 也沒有建立 Data20.msc→M3 或 AMSS→M3
segment 的路徑。不能由這些檔名、或與 sheng 恰好同為 299,660 bytes，推定同一
firmware。Public revision 是行為 reference，不宣稱已驗證安裝中的 module binary
與此 revision 完全相同；CAP filter 也沒有 actual phy_ucode request receipt。

### Host M3 與 firmware 匹配要求

- 先取得上述同台 Android ordinary file 的實物與 before/after phone hash，核對
  本機全檔 bytes/hash；與同份來源鏈的 `amss20.bin` hash
  `cc25a432aa19e71e8503b424c9a52be952f6dd1d2f93f38f1ff754f748d97667` 綁定。
- 比較實物大小是否等於本趟 M3_INFO 的 299,660；相同大小只是 consistency
  check，不是 identity。不同則保持 critical gap，不改採 sheng 或猜 Data20 slices。
- primary 路徑是全檔 memcpy；只有確認 bytes/hash/來源相符後，才可由主代理把
  整份檔案以 XNU 所需的 `/usr/local/share/fuxi/wlan/m3.bin` 名稱 staging。
  不做 ELF segment extraction，不改 driver；15:18 時 root staging/readback
  尚未驗證，15:32 成功收尾已更新於本節開頭。
- 若不能從 ordinary file 的來源鏈解釋本趟 M3_INFO，缺口維持 unknown；不得
  直接讀 `0xa2a00000` 來補證據，也不自行觸發 QDSS/M3 dump/debugfs。

現有工具仍輸出 `m3_payload_hash_verified=false`，不宣稱 loaded identity；
15:18 已建立 source-backed M3 staging input，BDF 的 actual Android 選取依據
亦已具備。15:32 主代理完成 staging/readback 並回報 W18 BDF/M3 accepted
進度，M3/staging gate 不再阻塞。Loaded-buffer hash 與 MODE 結果不可由
host inventory 推定；後續 MODE 取證由主代理處理。

## Host checks

46 個 production-helper tests：全部截斷 prefix、malformed top/nested TLV、
padding／alignment u32 overflow、duplicate names/data/attrs、missing required
attrs/name/data、decimal/hex boardname、合法多 aliases／REGDB、file/count bounds、
256 個 bounded malformed fixtures、ELF32/64/endian/table/segment bounds、opaque
不假造 IDs、CLI provenance/duplicate-path 拒絕與 input 不變檢查。
另檢查 receipt-only 目錄缺席／JSON duplicates／success markers／count／version、
contradictions、provenance required attrs、路徑逃逸與 no-payload-open。
測試資料都是 synthetic，不是盤點實物，不宣稱 Fuxi 適配。
另檢查 Android CAP normalized validity、不混淆 WMA board ID、request/resolver/
download order、path/type/size、M3 pointer redaction／非 physical、manifest hash
與 receipt association、batch bounds、wire magic、no auto-select/staging。
另驗證 M3 metadata 不等於 QMI reply、非 V2 FW 不產生 V2 candidate、M3
zero／overflow 拒絕，以及相同大小的 synthetic candidate 不提升 loaded M3 identity。
本機執行為 45 passed／1 skipped；Windows 不允許建立 synthetic symlink，
該 case 的 symlink 部分未驗證。AST、CLI help 與三個新檔 whitespace checks 通過。
