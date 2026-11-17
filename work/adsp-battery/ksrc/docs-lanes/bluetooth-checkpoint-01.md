# Fuxi iOS16 Bluetooth checkpoint 01

日期為 2026-11-16，來源分支為 `adsp-battery`。目標為 SM8550 / WCN7850、QUP2 SE6、iOS16.7.16 20H392 / XNU8796.141.3。

## 可合併範圍

| 檔案 | 行為 |
| --- | --- |
| `xnu/fuxi-bluetooth/fuxi_bt.h` | 狀態碼、UART callback 合約、探測結果與硬體 snapshot 結構 |
| `xnu/fuxi-bluetooth/fuxi_bt.c` | 有界 QCA version transaction、串流 H4 解析與唯讀 clock/pin/engine snapshot |
| `xnu/fuxi-bluetooth/fuxi_bt_xnu.c` | 預設關閉的 XNU 啟動入口、fallible 16 KiB MMIO mapping、同步 abort 保護與一次性 worker |
| `tools/test-fuxi-bluetooth.py` | 執行 production C 的協定、bounds、清理、clock gate 與 fuzz 測試 |
| `tools/test-fuxi-bluetooth-xnu.py` | 執行 production XNU 入口的主機模型，替換 XNU 宣告、MMIO 與 thread 服務 |

`fuxibt` 省略或設為 `0` 時，入口立即返回。`fuxibt=1` 讀取 GCC、GPIO76–83，並在五條 clock branch 的 `CLK_OFF` 全清除時讀取 QUP wrapper / SE6。`fuxibt=2` 在成功 snapshot 後，透過已註冊的 UART callbacks 執行 version transaction。其他整數會留下 rejected log 並返回。

主機驗證已通過以下兩個命令。

```sh
python tools/test-fuxi-bluetooth.py
python tools/test-fuxi-bluetooth-xnu.py
```

編譯器為本機 MSVC 14.50，C11 `/W4 /WX /Od`。協定測試覆蓋 320 組 RX/TX 分段組合、21 種截斷長度、Command Status / Complete、ACL/SCO/ISO 邊界、舊 QCA VSE、IBS、stale RX drain、逾時、byte/frame/poll budgets、partial-acquire 清理、64 組 clock gate 狀態、35 個 snapshot MMIO 故障及 10,000 筆 deterministic fuzz。入口模型另覆蓋預設關閉、參數拒絕、一次性啟動、註冊、成功 worker、6 個 allocation、7 個 pmap 及 35 個 MMIO 失敗點的回收。

本文件的 sync 小修改亦已在記憶體套用到現有 `sync-fuxi-adsp.py` 並執行其 `expected()`。生成內容中的三個 BT 檔案逐位元組對應 canonical sources，兩個 C build entries 均存在。

Sanitizers 尚待具備 Clang/GCC 的 CI 執行。這兩個命令在該環境使用 `--sanitize` 會啟用 ASan/UBSan。XNU8796 SDK 編譯、kernel link 與手機結果由主代理的批次 CI / 測試提供。

## 主代理的最小 build / sync 接線

### 現有 0117 聚合路徑

已核對 `tools/ci/prepare-kernel.py` 從 `xnu/patches/` 複製 patch。`tools/sync-fuxi-adsp.py` 生成 0117，並用 `SOURCES` 生成 `bsd/conf/files`。主代理可將下列小修改納入其批次，完成後由主代理重新生成 0117。

在 `tools/sync-fuxi-adsp.py` 的 `FILES = SOURCES + HEADERS` 前增加以下內容。

```python
SOURCES += ('fuxi_bt.c', 'fuxi_bt_xnu.c')
HEADERS += ('fuxi_bt.h',)
BLUETOOTH_SOURCE = ROOT / 'xnu/fuxi-bluetooth'
SOURCE_PATHS = {
    'fuxi_bt.c': BLUETOOTH_SOURCE / 'fuxi_bt.c',
    'fuxi_bt_xnu.c': BLUETOOTH_SOURCE / 'fuxi_bt_xnu.c',
    'fuxi_bt.h': BLUETOOTH_SOURCE / 'fuxi_bt.h',
}
```

在 `expected()` 中，`FILES` 的 byte 檢查與新增檔案 unified diff 共用以下路徑選擇。`MODIFIED` 的來源使用 `SRC` 解析。

```diff
 def expected():
     for name in FILES:
-        data = (SRC / name).read_bytes()
+        data = SOURCE_PATHS.get(name, SRC / name).read_bytes()
         assert b'\r' not in data, name + ' has CR line endings'
         assert data.endswith(b'\n'), name + ' lacks a final newline'
-    new = ''.join(''.join(difflib.unified_diff([], (SRC / name).read_text().splitlines(True), fromfile='/dev/null',
+    new = ''.join(''.join(difflib.unified_diff([], SOURCE_PATHS.get(name, SRC / name).read_text().splitlines(True), fromfile='/dev/null',
                                                tofile='b/bsd/dev/' + name)) for name in FILES)
```

此修改使三個來源安裝到 `bsd/dev/`，並增加以下兩筆 build list。

```text
bsd/dev/fuxi_bt.c                        standard
bsd/dev/fuxi_bt_xnu.c                    standard
```

### 啟動接線

現有 0106 已在 `sweet_ufs.c` 啟動 persistent log 後呼叫 `fuxi_adsp_init()`。為 RAM/haptic/BT 批次，主代理可在 canonical `xnu/fuxi-adsp/fuxi_adsp.c` 的獨立探測區增加兩行，讓現有 sync 生成呼叫。位置在 ADSP 的 `if (!run || gStarted) return;` 前，因此 BT 的啟動條件由 `fuxibt` 控制。

```diff
 extern void fuxi_ramtest_init(void);
+extern void fuxi_bt_init(void);

     fuxi_pmic_init();
     fuxi_ramtest_init();
+    fuxi_bt_init();
```

若主代理已按較早 checkpoint 在 `sweet_ufs.c` 呼叫 `fuxi_bt_init()`，可使用該入口。函式的一次性 guard 會阻止重複啟動。此文件的 `fuxi_adsp_init()` 入口可直接由現有 0117 sync 收錄。

### CI 命令

在 `tools/ci/build.sh` 的 `kernel()` 主機 checks 加入以下兩行。

```sh
python3 tools/test-fuxi-bluetooth.py
python3 tools/test-fuxi-bluetooth-xnu.py
```

主代理生成 0117 後執行 `python3 tools/sync-fuxi-adsp.py --check`，再執行 RAM/haptic 批次 kernel build。具備 ASan/UBSan runtime 的 runner 可對兩個 BT 測試加上 `--sanitize`。主機測試直接編譯 canonical sources，主代理的 sync check 負責驗證打包內容一致。

## 首趟唯讀測試

新增參數為 `fuxibt=1`。沿用主代理既有 recovery / log 流程及日常 `sweetnoexec`。必須取得完整的 `FUXI BT:` log。

成功判準為 `survey status=ok`、GPIO76–83 的八筆記錄、零 `read fault`，以及 worker 完成後系統繼續運行。

若 `off_mask` 非零，`engine_read=0` 表示 gates 正確限制了 SE6 / wrapper 存取。這是有效的 cold-clock snapshot。若 `off_mask=0`，應取得 `engine_read=1` 與 `protocol=2`。`if_disable` 來自 SE6 的 `GENI_IF_DISABLE_RO` offset `0x64`，bit0 表示 FIFO interface 被禁止。此欄位決定下一輪 FIFO 或 DMA transport 的方向。

Snapshot 使用三個 GCC tiles、兩個 TLMM tiles，最多再加 SE6 / wrapper 兩個 tiles，共 112 KiB 暫存 VA。所有 mapping 在 snapshot 結束時釋放。讀取 SE6 前，主代理的資源擁有者需讓五條 clock branch 在該讀取期間持續運行。同步 abort 保護能處理可恢復的 read fault，實際 NoC clock gating 的持續性由板級資源擁有者管理。

## 下一輪 active UART 接線

入口為 `fuxi_bt_register_uart(&ops)`，在啟動 BT worker 前註冊，結構與 context 需保持有效至 worker 結束。註冊會複製 ops，使用 release/acquire publication；重複註冊回傳 `busy`。主代理完成 callbacks 後使用 `fuxibt=2`。

| callback | 合約 |
| --- | --- |
| `acquire(context, 115200)` | 取得 UART14 獨占使用權，處理 WCN rails / BT_EN / settling、QUP2 shared clocks / SE6 source、GPIO76–79、UART 115200 8N1 RTS/CTS 及 RX 啟動，回傳本檔 enum status |
| `write(context, bytes, capacity, &count)` | 非阻塞接受 H4 bytes，支援 partial write；`again` 時 count=0；接受數量只計入 `tx_bytes` |
| `read(context, bytes, capacity, &count)` | 非阻塞讀取 UART bytes，傳遞 parity / overrun / bus error；`again` 時 count=0 |
| `release(context)` | 在 acquire 曾被呼叫的每條退出路徑回收本 transaction 的資源，包括 acquire 中途失敗；須可處理 ownership 尚未取得的情況，回傳清理結果 |
| `now_us(context)` | 單調遞增的微秒時間 |
| `wait_us(context, usec)` | 可在 worker context 等待，主迴圈要求 1000 us |

所有 callback 必須有自身的 bounded implementation。探測的 2 秒 elapsed budget 包含 acquire 時間；核心在 callback 返回後檢查時間。回收耗時由 release 自己的 timeout 管理。板級 shared rail 與 clock votes 的 ownership、RSC mutex 與其他 lane 的引用關係應使用現有平台管理。`release` 的回報與原始失敗會同時保留，成功版本回覆加上失敗清理會成為 `cleanup` 結果。

核心先 drain 最多 1024 bytes，取得 RX idle boundary，之後恰好發送 `01 00 fc 01 19`。耗盡 drain budget 而尚未觀察 idle 時回傳 `budget`。其 active budgets 為 2 秒、最多 2000 polls、4096 RX bytes 與 64 frames，每次 read 的 capacity 受剩餘 byte budget 限制。partial TX 支援從未接受的 offset 繼續，probe 的完整 HCI command 只發送一次。

WCN7850 的正確 Command Complete 為以下 21 bytes。`product` / `patch` / `rom` / `soc` 為小端。

```text
04 0e 12 <ncmd> 00 fc 00 19 00 <product:4> <patch:2> <rom:2> <soc:4>
```

Active 成功判準為 `probe status=ok cleanup=ok tx=5 ... valid=1`，`QCA version` 的 `soc`、`rom` 非零，以及板級 release 的狀態回收。`tx=5` 代表 host UART 接受命令，`valid=1` 代表 controller 回覆已完成嚴格解析。零 opcode mismatch、零 controller status error、正確 EDL 前置位元組與固定長度都要成立。

IBS byte `fc/fd/fe` 出現在 H4 frame boundary 時回傳 `ibs`，舊型 QCA 的 `ff / 00 02` version VSE 回傳 `legacy`。這兩種結果提供下一輪選擇 transport / power state 的證據。ACL/SCO/ISO 內同值 bytes 依 frame length 跳過。未知 frame type、畸形 completion、零 ROM / SoC 或超過 budgets 都會結束 transaction 並呼叫 release。

## iOS16 與 sheng 的差異

本機已讀 `docs-lanes/wlan-bt.md`、QcaBluetooth 的 `qbt_tty.c` / `qbt_transport.c` / `qbt_core.c` / `qbt_linux.c` / `qbt_geni.c` / `BlueTool.c` / `native-ios27.md`，以及 UniXNU-sheng 的 `BluetoothProbe.cpp`、startup record、build interface 和共用 `Sm8550GeniUart`。

sheng 的 native adapter 綁定 24A446 的 arm64e bluetoothd SHA-256 `cfd94854d0a2efd3ca4a2de6e55349f43fd0d274a4b8bfa9937f29d9f7208cb1`，包含 UART.SK、Skywalk、Type0 capability hooks、BlueTool XPC bootstrap 與 daemon instruction patches。其 `qbt_tty.c` 是 macOS serial frontend。這些功能需要各自目標的 ABI 和 native binary。

本地工作區可供檢查的 BlueTool C 是 sheng 的 replacement，Apple 的 20H392 BlueTool / bluetoothd 原始碼或獨立 executable 尚未取得。現有 lane 的 iPhone X strings / ADT 調查提供 `/dev/cu.bluetooth`、`/dev/uart.bluetooth`、`com.apple.uart.sk.bluetooth` 的候選介面。20H392 的實際 factory、transport ioctl / kernel-control option、sandbox / XPC 合約仍需主代理從該版 binary 驗證。Apple XNU8796 的 tty / kern_control / Skywalk 公開原碼提供 kernel API 定義。

此 checkpoint 的 controller identity 使用 QCA version 原值。此 round 的量測目標是 UART / QCA 證據。掃描與配對的可用性需要後續 firmware 與 iOS16 userland 整合測試。

## Primary sources

- Fuxi live DT `work/hw-survey/fuxi-live-20261116.dtb`，SHA-256 `2d7e97ea52bf67a79ef7b99487131a41bd87fc0ab774983ce62bfb9fa79fb9fa`，其 `qup_uart@898000` 記錄 `qcom,msm-geni-serial-hs`、SPI `0x1cd`、RX GPIO79 wake 與 clock。`bt_kiwi` 記錄 reset GPIO81 / SW_CTRL GPIO82。BT 的 18-aon 使用 ldob15 1.8 V，dig / aon / rfaOp8 共用 smpe4 0.95 V，rfa1 使用 smpg4 1.35 V，rfa2 使用 smpg6 1.9 V。active pinmux 為 GPIO76 `qup2_se6_l0` / bias-disable、77 `l1` / pull-down、78 `l2` / pull-up、79 `l3` / bias-disable，全部 2 mA。供電與 pinmux callback 使用此板級設定。
- QcaBluetooth 的 source-lock 鎖定以下 Linux commit。本輪已重新讀取 `btqca.c` / `btqca.h` 並確認其 SHA-256 與鎖檔相符。`qca_read_soc_version()` 要求 WCN3991+ Command Complete，EDL header 後多一個 byte，version copy 從 `edl->data + 1` 開始。`btqca.c` SHA-256 為 `1c703048b005aa407e32bfecaedccf1c28f6a78e1e4a384d51215abfcdec6d16`，`btqca.h` 為 `075eeaf78e4a9288ae228c0f99edbd137fcbd87c2645872cf748a9a33752205e`。[btqca.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/bluetooth/btqca.c) [btqca.h](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/bluetooth/btqca.h)
- SE6 source RCG `0x1e760`、branch `0x1e754`、shared vote `0x52010` bit10，以及 GENI firmware / interface / status 定義由同一 source pin 核對。`GENI_IF_DISABLE_RO` 是 `0x64`。[gcc-sm8550.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/clk/qcom/gcc-sm8550.c) [geni-se.h](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/include/linux/soc/qcom/geni-se.h) [qcom_geni_serial.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/tty/serial/qcom_geni_serial.c)
- XNU8796 的原型已核對 `TIOCGETA_64` / `TIOCSETA_64`、`ctl_register` / `ctl_enqueuedata` 與 kernel-pipe source。實際 daemon 的 UART.SK options 需用 20H392 caller 驗證。[ttycom.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/ttycom.h) [kern_control.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/kern_control.h) [nx_kernel_pipe.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/skywalk/nexus/kpipe/nx_kernel_pipe.c)

## 後續工作與工時

以下為單一熟悉 XNU / QCA 的工程師、已有 CI 與 recovery 的有效工作時間估計。hardware / firmware / private ABI 問題會擴大範圍。

| 待完成項目 | 可驗證產出 | 估計 |
| --- | --- | --- |
| 板級 rails / BT_EN / clocks / pinmux 與 115200 transport callbacks | `fuxibt=2` 真實 QCA version + release 成功；先由 snapshot 決定 FIFO 或 DMA | 1–3 天；若需 DMA/SMMU/IRQ bring-up，3–7 天 |
| WCN7850 rampatch / board ID / NVM、baud change、IBS、final HCI reset | 根據回覆 ROM / board ID 選取 `hmtbtfw*.tlv` / `hmtnv*`，完成下載並讀 supported commands / LE features | 2–5 天 |
| iOS16 transport / reset-power ABI 與 BlueTool bootstrap | 驗證 20H392 binary 的 tty 或 UART.SK 選擇、flow/backpressure、sandbox / XPC、原生初始化成功 | 3–7 天 |
| iOS16 QCA generic controller factory / capabilities / scan policy | 保留 QCA identity、HCI/LE capabilities 有效發布、真實 inquiry / LE advertising report | 4–10 天 |
| 配對、bond persistence、重連、power toggle、Wi-Fi coexistence | Settings 配對、key 儲存、冷啟動重連、basic profiles | 3–7 天 |

第一輪實機 UART version 成功後，基本掃描 / 配對的順序工作粗估為 3–7 週。若第一個 UART milestone 需要額外 DMA/SMMU/IRQ bring-up，整體範圍約 3–8 週。A2DP、HFP/SCO、deep sleep / wake 和 Apple vendor-specific 功能各需獨立驗證與估時。主代理可先合入本 checkpoint，在 RAM/haptic 同批 CI 取得編譯結果後安排 BT snapshot。
