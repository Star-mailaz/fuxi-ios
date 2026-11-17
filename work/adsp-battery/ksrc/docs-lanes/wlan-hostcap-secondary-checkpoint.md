# W18 HOST_CAP SECONDARY 單變量 checkpoint

日期：2026-11-16。這是可測的 opt-in host-contract 差分，不是已證 native FW_READY 修正；沒有重建或聲稱復現缺少 raw／參數的 try16。

本輪文件以已交付的兩個 source/test 檔為凍結 checkpoint。手機、整合、canonical patch、提交與 CI 均由主代理處理；本 worker 沒有操作手機、拿鎖、sync、commit 或發布原廠模組／private captures。

## 1. 原廠模組實物與證據界限

已確認的本機 receipt：`D:\xiaomi13\fuxi_ios\work\adsp-battery\android-wlan-modules-20261116-1634\modules.json`，捕獲時間 `2026-11-16T16:36:19.651303+08:00`。

| 項目 | 實證 |
| --- | --- |
| Android source path | `/vendor_dlkm/lib/modules/cnss2.ko` |
| Host file | `D:\xiaomi13\fuxi_ios\work\adsp-battery\android-wlan-modules-20261116-1634\00-cnss2.ko` |
| Bytes／SHA256 | `978880`／`32f9cbf282f00ce1447942a78668d53b3023b3e8119eca61a8cf19cff03e5390` |
| ELF | ELF64、little-endian、ET_REL、AArch64 |
| Module name／SCM | `cnss2`／`scmversion=g63d958adf1cd` |
| Build ID | `bc6b02f634a5d641d91d4416735e5ab2e26e0996` |
| Module vermagic | `5.15.78 SMP preempt mod_unload modversions aarch64` |
| 同次 kernel uname release | `5.15.178-android13-8-00021-g6f2f96be86b9-ab13729987` |
| Kernel metadata SHA256 | `487232d79d64fcc164ac44277a94f99c17aa9b6fa4d7879a6dc9a44b648f5dd7` |
| Loaded identity gate | receipt 明列 `loaded_module_buffer_identity_verified=false` |

主代理記錄了 phone before/after 與 host hash 相符。本 worker 再驗證五份 exported modules 的 host bytes/hash，以及 `kernel-modules.txt` 的 hash，全部符合 receipt；沒有使用別台裝置或未匹配 hash 的 candidate。

這證明的是同台 Android filesystem 上該份模組檔案的 static behavior，不是 loaded buffer hash 或 live QMI request capture。`/proc/modules` 列出 `cnss2`，不代表其 loaded bytes 已與 disk file 匹配。vermagic 與 uname 數字不同，不能宣稱完整 runtime ABI identity；也不能僅據此推定模組未載入或不相容。Build ID／SCM 亦不等於下面 primary revision 的整份 source commit。

`user/release-keys`、firmware build 字串或 debug logs 都沒有用來推定 `CONFIG_CNSS2_DEBUG`。

## 2. HOST_CAP 的兩個關鍵 store

`cnss_wlfw_host_cap_send_sync` 沒有獨立 symbol；其 request 建立與送出已 inline 到 `cnss_wlfw_server_arrive`，symbol 起點 `.text+0x27940`、size `0xa38`。

| Instruction offset | Request field／寬度 | 已追到的值 |
| --- | --- | --- |
| `.text+0x280a8` | `strb w8, [x21, #0x130]`；`host_build_type_valid`／1 byte | `.text+0x28098` 將 `w8` 設為 `1` |
| `.text+0x280ac` | `str w10, [x21, #0x134]`；`host_build_type`／4 bytes | `.text+0x2809c` 將 `w10` 設為 `2` |

`x21` 是 `.text+0x27e24` 配置的 request，配置大小 `0x1e0`。上述 stores 在後面的 MLO device-ID 分支之前，並非從其他無關常數猜測。`.text+0x281a8` 將此 request 放入 `x6`；`.text+0x281ac` 的 relocation 指向 `qmi_send_request`，message ID 為 `0x34`、max encoded length 為 `0x1eb`，EI symbol 是 `wlfw_host_cap_req_msg_v01_ei`。

可重查的只讀工具是現有 NDK `llvm-nm`、`llvm-readelf` 與 `llvm-objdump`；disassembly 的 HOST_CAP 有效範圍可限制在 `.text+0x27e14` 到 `.text+0x281b0`，不必發布整份 disassembly 或模組 bytes。

## 3. Primary enum／schema 與 source-ABI 對照

Primary revision 固定為 MiCode `518147fd7e0199758efe9bd96a22c9c2ea30bcd9`：

- [wlan_firmware_service_v01.h:205](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss_utils/wlan_firmware_service_v01.h#L205)：`UNSPECIFIED=0`、`PRIMARY=1`、`SECONDARY=2`。
- [wlan_firmware_service_v01.c:3535](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss_utils/wlan_firmware_service_v01.c#L3535)：TLV `0x20` 是 `QMI_OPT_FLAG` 加 `QMI_SIGNED_4_BYTE_ENUM`。valid byte 是 host-side presence control，不是 payload；payload 為四-byte LE enum。
- [cnss2/qmi.c:328](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c#L328)：primary 設 `host_build_type_valid=1`，並呼叫 selector。
- [cnss2/qmi.h:328](https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.h#L328)：primary 的 `CONFIG_CNSS2_DEBUG` branch 選 PRIMARY，另一 branch 選 SECONDARY。這不是對 installed module compile flags 的獨立證明；本次直接由 disk instruction store 證明值 `2`。

Cached primary header／`qmi.c` 已與固定 revision 原始內容比對，僅正規化 CRLF。用原始 request declaration 做 AArch64 C11 compile-only `_Static_assert`，通過以下對照：

| Primary AArch64 layout | 值 |
| --- | --- |
| `sizeof(wlfw_host_cap_req_msg_v01)` | `0x1e0` |
| `num_clients` | `+0x4` |
| `bdf_support_valid`／`cal_done_valid` | `+0x9a`／`+0xa6` |
| `ddr_range_valid`／`ddr_range` | `+0xf8`／`+0x100` |
| `host_build_type_valid`／`host_build_type` | `+0x130`／`+0x134`，enum width `4` |
| `feature_list_valid`／`feature_list` | `+0x159`／`+0x160` |
| Max encoded length | `0x1eb` |

這些 size、field offsets 與 CNSS disk code 的配置、stores、send arguments 相符，是 source request ABI corroboration，並非整份 source identity 或已安裝 EI binary 的證明。同次 `/proc/modules` 的 EI provider 是 `wlan_firmware_service`；該模組不在已導出的五份檔案內。Live TLV presence／loaded EI identity 仍不得冒稱已觀察。

## 4. 已交付 encoder／guard

凍結檔案與交付時 SHA256：

| 檔案 | SHA256 |
| --- | --- |
| `xnu/fuxi-wlan/fuxi_wlan.c` | `6d0465f9df8bee29c75c85952451f7f6310dcbef1e45a2b707c639b71ec15de3` |
| `tools/test-fuxi-wlan-w18.py` | `4a82f8cdfa784e53c0c159f203e7b654520658977132c723fbecf66bd9f3b2e6` |

- 只有 `fuxiwlanqrtr=5` 且 `fuxiwlanw18=1` 的 lane 解析新 selector；其他 lane 不啟用此 profile。
- 缺省與精確字串 `0` 保持原 HOST_CAP wire；精確字串 `1` 只增加 `0x20`，payload `02 00 00 00`。
- Selector `1` 不等於 enum PRIMARY `1`；完整新增 TLV 是 `20 04 00 02 00 00 00`，只多 `7` bytes。
- 使用 string API 避免數字 coercion；`-1`、`2`、`01`、`+1`、`0x1`、尾隨文字、空字串、overflow／長字串均拒絕。
- 專屬 invalid-cap guard 在 `fw_run` 首行返回，早於 WLAN power writes；有效／缺省 selector 不改原啟動序列。
- 原 `0x13=0x0e` 與 `0x1c=0` 不省略、不改值；MLO／P17 policy、feature list、readiness `0x38`、10000 ms timeout、BDF／M3、CE containment、ADSP/WLAN joint guard 與 shared RPMh lock 都不改。
- 沒有新增 wake MSI `0x11` 或 DDR range `0x1f`；Android DMA handle 不能當目前 XNU mapping 或 CPU PA 使用。

原 `0x13` 位元來源是 [Linux v6.12 ath12k/qmi.c:15](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/qmi.c#L15)：internal sleep clock `0x02`、non-Qualcomm host `0x04`、PCIe global reset `0x08`，合計 `0x0e`；不是 rail bits。[同檔 host-cap sender](https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/qmi.c#L2069) 說明其語意。Primary CNSS 省略 `0x13/0x1c` 與 XNU 明送值的差異仍存在，但本 checkpoint 故意不把它們混進單 TLV A/B。

## 5. 受控 A/B baseline

尚未宣稱此 HOST_CAP patch 有 native boot 結果。主代理先同步、提交並產出含此 patch 的新 kernel；此前已在 building 的 CI／既有 loader 不應假定含有新 selector。

| 條件 | A | B |
| --- | --- | --- |
| Kernel／loader layout | 同一含 patch 的 kernel hash、同一已驗 statusbar127／ram9g layout | 與 A 相同 |
| OEM assets／stage receipt | 同台已驗五資產與既有 staging/readback receipt | 與 A 相同，不重做選 BDF／M3 |
| ADSP／WLAN／W18 | `fuxiadsp=0`、`fuxiwlan=1`、`fuxiwlanqrtr=5`、`fuxiwlanw18=1` | 與 A 相同，保留 joint guard |
| MLO | 原 OEM baseline 的缺省 policy；不帶 `fuxiwlanmlo=2` | 與 A 相同 |
| HOST_CAP 唯一變量 | 不帶 `fuxiwlancap`，或明設 `fuxiwlancap=0` | 只增加 `fuxiwlancap=1` |
| 尚未驗證功能 | 不啟用 CE／HTC active；不增加 rails／DDR／MSI 實驗 | 與 A 相同 |

其餘有效 boot args 完全沿用同一 baseline loader，不從本文重新組一套長參數。RAM SKU／multirange、loader parser 與 metadata 為其他主線 scope，不由本 worker 改動。

判讀先確認 B 的 selector log 與 `W18 HOST_CAP TLV 0x20 host_build_type SECONDARY=2 len=4`，再核對 QMI reply、BDF／M3、是否收到 `0x38`。若仍 FW_READY timeout，只能說單 TLV 差分未解除該 blocker；不能稱 WLAN_MODE root fix。只有收到 `0x38` 才繼續原 INI／CFG／MODE 流程；不能縮短 timeout 或把 `0x21` 改認 ready。

## 6. Host encoder／tests 結果

`tools/test-fuxi-wlan-w18.py` 的 production C 與 independent peer 檢驗：

- `168` 組 selector/lane 組合，含缺省／0／1、非法字串與長字串；確認狀態 reset、guard 與零 MMIO writes。
- `8` 組 production encoder policy 差分，覆蓋既有 MLO variants 與合法 P17 policies；independent bounded TLV walker 要求唯一 `0x20`、width `4`、LE value `2`，只剝除該 TLV後逐 byte 比對 baseline。
- `6` 組完整 host QMI conversations，缺省／0／1各含成功及 MODE silence；保留原 literal HOST_CAP expectation、其他 request、10000 ms timeout 與 no-CE containment。
- 原 W18 phase transitions、MODE EOT、six read-only accesses、faults、RDDM、quarantine checks 繼續通過。

本機已跑完整 production M6o/W18 peer：MSVC C11 `/W3` 加 AddressSanitizer，PASS；有 `10` 個 generated-peer warnings，沒有聲稱 `/WX` 通過。Windows run 只在 temporary test source 適配 CRT allocation/free、`bzero`／`caddr_t` 與等價 packed-layout pragmas；未改 canonical source、其他 tests 或 build scripts。

Python AST、限定兩檔 `git diff --check`、上述 AArch64 primary layout assertions 均 PASS。Windows host 未跑 UBSan；標準 Linux ASan/UBSan runner `python3 -B tools/test-fuxi-wlan-w18.py --standalone` 交主代理 CI 重跑，本文不把尚未完成 CI 寫成通過。這些是 host simulation／encoder checks，不是 firmware 或手機成功證據。

## 7. 前一趟 no-MLO 已證失敗，不能算 fix

已只讀核對的 raw boot：`D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109\native-hw000w18-oem-nomlo-boot-1\boot.log`，`310984` bytes，SHA256 `dfc5fb83dc536fb68ec2eb7bda084e2a341efd65052ad7e21fa6b0d66f55e2c8`。

主代理操作記錄 `D:\xiaomi13\fuxi_ios\work\statusbar-fix\hw000w18-oem-nomlo-20261116.log` 明列約 `16:23:53` 的 run start、`fuxiadsp=0`、`fuxiwlanw18=1`、`fuxiwlanmlo=2`。本文不複製完整 private boot command。

- Raw line `180`：MLO variant `2` valid。
- Raw line `1003`：HOST_CAP MLO TLVs 確實 omitted，`num_phy=2`。
- Raw line `1377`：M3 `299660` bytes，XNU DMA IOVA `0xa1e80000`。
- Raw lines `2642/2643`：`W14 FW_READY indication (10000 ms)` timeout／failure，contain、no retry。

因此 no-MLO 變量有實際送出差分，但未解除 pre-FW_READY blocker；不是 root fix，也不是已到 WLAN_MODE 的結果。它與本文件的單 `0x20` profile 是兩個分開的實驗。

六條外部 rails 已有投票，不把這個 timeout 說成未上電。BDF reply 的 `host_bdf_data` 不是 rail vote；原廠 M3 log 的 `0xa2a00000` 是 DMA handle，不是已證 CPU PA，也不移植到 XNU。

## 8. 第22趟 SECONDARY 實機結果

2026-11-16 18:04:50 暫時開機，18:09:41 已確認 Android 完成開機、
mapping 解除及自有鎖釋放。未改日常 boot_b。主機監看最高50.5°C。
loader 為 `native-wlan-w18-oem-secondary-ram9g-sb127-loader`，boot SHA256
`4a6b111a2cd855d9411d9f934b605f907090d62c0920ddb5312dfa8cb46c1631`，
kernel SHA256
`aabeb78f6589b5cef2eafa31c8b353aacb857c64c7894884979c40269d8d4338`。
600-byte 命令列僅相對原 OEM baseline 增加 `fuxiwlancap=1`；
MLO 仍為缺省 policy，ADSP／amp／PMIC／haptic 關閉。

原始 log 為
`work/Codex-Xiaomi13-GPU-20261109/native-hw000w18-oem-secondary-boot-1/boot.log`，
SHA256 `72c168f66ce8f43da9656c6b9f1b2a6a6416d0f84569885bc96b9b9a4eb8d4fb`。

- 第182行 selector 1 valid；第974行明列 TLV `0x20`、SECONDARY=2、len=4。
- 第977行 HOST_CAP reply `txn 2 msg 0x34 result 0 error 0`。
- 第1198／1369／1378行分別確認原廠 REGDB、全部15段 `bd_m3.elf`、
  M3_INFO 成功；已越過舊照片中的 BDF 首片卡關。
- 第2639–2644行仍為 `FW_READY indication (10000 ms)` timeout、
  step28 code `0x1c01`，未進 INI／CFG／MODE。
- 第2680–2687行記錄 bus master off、PERST asserted、MSI／SMMU undo、
  buffers freed 與 thread stop，沒有在該 boot 重試。

18:11:00 在下一趟 iOS 前另保存持久化 console：
`work/adsp-battery/fuxilog/20261116-181100/console.txt`，boot#24、
flush#20、294799 bytes。這與上列 USB log 是不同收集路徑，不能互換 hash。

本趟證明 SECONDARY 已送出且被接受，仍未解除 FW_READY blocker。
核心及 RAM runtime guard 與舊 OEM baseline 不同，因此沒有把跨核心比較
當成嚴格 A/B 或根因證明。未驗掃描、連線、TX/RX 或 IP。

## 9. 下一步的同台 Android 實證

18:22:37 已在 Android 唯讀擷取啟動日誌，主機路徑
`work/adsp-battery/android-wlan-init-20261116-1823/cnss_init_events.txt`；
manifest 記錄實際命令、bytes及hash。僅讀 dmesg 與固定 firmware/config
目錄名稱，未啟用debugfs、改參數或觸發firmware dump。

兩輪 CNSS 啟動在同份 log 均記錄：

- HOST_CAP 的 WAKE MSI=13、DDR IOVA start=`0xa0000000`、
  size=`0x10010000`、feature list=`0x6`。
- `wlan-connection-roaming.ini` 取得失敗，仍繼續送BDF與M3。
- M3之後下載 `kiwi/qdss_trace_config_v2.cfg`，4911 bytes；
  其後收到 FW initialization done／FW_READY event。

這排除了「原廠成功必定先取得 connection-roaming INI」的推論；
其他 HOST_CAP 欄位及 QDSS 時序是有實證的差異候選，尚非根因。
不直接移植 Android IOVA／MSI，不宣告 QDSS 是必要條件，也沒有啟用
未實作的 host feature。原廠事件名與 XNU message ID 的對應仍以
各自 primary schema 為準。

此外，第22趟 CB6 的 FSR=`0x400`、FAR、
FSYNR及CBFRSYNRA/SID=`0x139f`，從step20首次CB檢查到step28均相同；
`wl_smmu_fault()` 的既有 `0xc00001fe` fault mask結果為0。
因此 timeout後的tuple不能當作本趟新生DMA fault證據，
更不授權新增stream mapping或清除未知狀態。

## 10. 下一輪 nm_modem 單 TLV 省略候選

2026-11-16 18:35，本輪加入 `fuxiwlancap=2`：沿用 selector1 的
SECONDARY=2，只省略 TLV `0x13 nm_modem=0x0e`。缺省、精確0及1保留原
wire；新 selector2 不改 `0x1c`、feature list、MLO、MSI、DDR IOVA、
BDF／M3或 FW_READY `0x38`／10000ms。其餘字串仍在 WLAN power writes
前拒絕，每次 configure 重設 omission 狀態。前述章節中「2屬非法」是
selector2加入前的歷史結果。

原廠 primary `cnss-qmi.c` 的 HOST_CAP request 未設定 nm_modem。
同台已保存 CNSS disk disassembly 也未觀察到對應 request offset
`0x98/0x99` 的 stores；此靜態觀察不是 live wire capture，也未證明
nm_modem 是目前 blocker。原 ath12k 的0x0e宣告不作為此台原廠已用值。

Loader 必須同時明示 `--host-cap-secondary --omit-nm-modem`，並檢查
新 kernel omission marker。相對 selector1 只改單一 selector字元，
600-byte command line長度相同，拒絕 inherited selector／MLO override。
若 selector2 取得 FW_READY，需再以同 kernel selector1 對照；仍須
另驗 INI／CFG／MODE、掃描、關聯及 TX/RX，不能把 ready 當作上網完成。

本機 production C W18 suite 已以 Unity Emscripten＋Node執行，
ASan／UBSan flags保留：182組 selector/lane、16組 encoder policy
差分及8組完整對話通過。獨立 TLV walker 補回被省略的 literal0x13，
剝除0x20後逐 byte 比對原 baseline。Loader helper自測、45項SKU
preflight（正常與Python `-O`）通過。這是 wasm32 host結果，native
64-bit CI及本輪實機驗證仍待完成。M6i／rails相關 invalid-cap log
expectation已更新以符合新 selector範圍，兩套 production peers亦已
以相同 wasm32 ASan／UBSan工具鏈重跑通過，包含全部W16 variants、
供電順序、共用鎖、fault與quarantine路徑。

## 11. 第25趟 nm_modem 省略實機結果

2026-11-16 18:55:06 temporary boot，18:59:58 已確認Android完成、
root unmapped及自有鎖釋放，未寫daily boot_b。Host TSENS最高50.9°C。
loader為 `native-wlan-w18-oem-no-nm-modem-ram9g-sb127-loader`，
boot SHA256
`5a3a29ac905ab93eb093e67f32c31cd2f16f60c0e6aee0dc29032e7c1f942063`，
kernel SHA256
`1311058383a2680914b77292e4d7883e72de8bdea5ceda6e16c893c592191da3`。

新核心來自harness `5be6591` 的9g CI `43850892720`，production
來源包含ksrc `723e740`及H1生成patch同步`1836f06`。5g CI
`43850892769`同樣成功，兩份下載產物各40項manifest全部通過；
5g kernel SHA256為
`69f551cd5f1d68a914f5ef20cfd70fd4ca83713ff4232dd2f44ef8ecdaf83c89`。
此5g仍是已核對的12GB SKU配置，不是8GB實機驗收。
完整macOS host CI `43850892647`及新增portable／macOS雙job CI
`43851634998`均成功；後者harness `984934e`只改workflow，
未改kernel aggregate或重建上述兩份核心。

同核心cap1對照loader
`native-wlan-w18-oem-secondary-v2-ram9g-sb127-loader`也已建好。
Host byte comparison確認整份payload只差 `fuxiwlancap=1/2` 的一個
字元。此cap1對照尚未上機；不能把本次和舊核心第22趟當成嚴格A/B。
五資產、39 extents、12GB／9g、36份shim來源及600-byte命令列均核對。

USB log：
`work/Codex-Xiaomi13-GPU-20261109/native-hw000w18-oem-no-nm-modem-boot-1/boot.log`，
279875 bytes／4114行，SHA256
`beb4fb316b641167a6ace5ca5d1eabdb313c880d9d3e22cb465e5c3cfb8e528c`。

- 第182行確認selector2 valid；987／988行確認省略nm_modem、
  保留SECONDARY。996行HOST_CAP reply txn2／msg0x34／result0／error0。
- 1201行REGDB最後一段成功；1318／1319行BDF segment14／end1及
  `bd_m3.elf ok`，全部15段完成；1325／1326行M3_INFO reply及m3 ok。
- 2626／2627行仍為FW_READY `0x38`的10000ms timeout及failure；
  2631行step28 code0x1c01。沒有進INI／CFG／MODE。
- 2654–2661行MHI reset、bus master off、PERST asserted、host entries
  pending0、power contained、MSI／SMMU undo、buffers freed與stop均完成。
- Step20及28的CB6 FSR0x400／FAR0x138f1:99dff7a1／
  FSYNR0x3d0d35/0x8d29／SID0x139f完全相同；不當作新增DMA fault，
  不加stream mapping、不清未知狀態。

19:00:38另保存持久console：
`work/adsp-battery/fuxilog/20261116-190038/console.txt`，boot27、
flush20、294002 bytes、SHA256
`e92d865934fc380dfad24a1722fa47fc3d634427d2e9bc15893df7775b497f5c`。

結論僅為此省略候選仍無法取得FW_READY，不是Wi-Fi修復。
原廠HOST_CAP的其餘差異、DDR宣告及後續初始化仍需逐項確認契約；
不直接照搬Android DMA／MSI，也不以0x21取代0x38。掃描、關聯、
CE／HTC資料路徑與IP傳輸均未驗收。
