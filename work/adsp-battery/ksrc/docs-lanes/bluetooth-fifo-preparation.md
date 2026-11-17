# Fuxi iOS16 GENI FIFO preparation

日期：2026-11-16。目標：SM8550 / WCN7850、QUP2 SE6 / UART14、iOS16.7.16 20H392 / XNU8796.141.3。這是可執行的 host transport 準備，不是已接通的手機 UART、Apple controller 或完整藍牙堆疊。

## 本輪交付與目前實機證據

本輪只新增以下四個檔案，沒有修改 snapshot、生產啟動入口、build、sync 或聚合 patch。

| 檔案 | 用途 |
| --- | --- |
| `xnu/fuxi-bluetooth/fuxi_bt_geni_fifo.h` | register offsets、callback / config 合約、狀態與可核對的清理證據 |
| `xnu/fuxi-bluetooth/fuxi_bt_geni_fifo.c` | preflight、115200 8N1 CTS/RFR、partial FIFO TX/RX、poll / cancel / abort / restore |
| `tools/test-fuxi-bt-geni-fifo.py` | 編譯 production C，執行獨立 register / FIFO / controller emulator |
| `docs-lanes/bluetooth-fifo-preparation.md` | source pin、驗證範圍、caller 接線與板級 ownership / shutdown 要求 |

已直接讀取 `work/Codex-Xiaomi13-GPU-20261109/native-hw000iter2-ram512-haptic-bt-torch-boot-1/boot.log` 的 `FUXI BT:` 記錄，首筆位於第 352 行。

```text
survey status=ok vote=0x10000 gpll0_vote=0x11 off_mask=0x12 engine_read=0
branches core=0x4000 s_ahb=0x80000002 m_ahb=0 core2x=0x4000 se6=0x80004000
rcg cmd=0x80000000 cfg=0x100000 m=0 n=0 d=0 dfs=0x8020
gpio76..83 ctl=1,1,3,1,1,1,1,1 io=1,0,1,0,0,0,0,0
```

這是成功的 cold-clock 唯讀 snapshot：`off_mask` bit1 / bit4 分別對應 wrapper S_AHB / SE6 的 `CLK_OFF`。現有入口正確拒讀 SE / wrapper。此輪沒有 `IF_DISABLE`、UART protocol 或 FIFO geometry 值，因此既不能宣稱 FIFO 可用，也不能判定需要 DMA。沒有 `read fault`；這不等於已驗證有 clock 時的 SE MMIO。RCG snapshot 亦不能當作已取得 7,372,800 Hz source。`fuxibt=1` 保持唯讀，不由此 helper 自動開 clocks。

root 上的 20H392 BlueTool / bluetoothd 唯讀擷取尚未成功。本輪沒有該版本 binary 或 ABI 證據。sheng 的 iPadOS27 / 24A446 adapter、BlueTool replacement 與 daemon patches 不是 iOS16 原生介面的驗證。

## API 與 caller 合約

`struct fuxi_bt_geni_fifo` 必須先全零初始化。每個 context 只能由一個 caller 使用；不可並行呼叫。helper 不映射 MMIO、不持鎖、不碰 GCC / TLMM / RPMh，也不註冊 interrupt 或 UART。I/O 只經過以下三個 callbacks。

| callback | 必要合約 |
| --- | --- |
| `read(context, offset, &value)` | 32-bit SE register read；有自身有限完成時間；成功才回傳 `FUXI_BT_OK` |
| `write(context, offset, value)` | 32-bit ordered SE register write；順序等同 driver 的 `readl` / `writel` 合約；成功表示已完成該寫入，不只是排入非同步佇列 |
| `now_us(context)` | 單調、不倒退的微秒時間；helper 額外有 poll 次數上限，不能藉固定時間無限等待 |

offset 是相對於 caller 持有的 SE6 window，最大使用 offset 為 `0xe28`。主代理若將 callback 接到實際 MMIO，須提供有效 mapping、device memory ordering、可恢復 fault 處理及整段 access 的 clock / power 保證。host bounds 無法中斷一個永不返回或觸發不可恢復 NoC abort 的 callback。

`config.opt_in=0` 是 default-off；`open()` 回傳 `OFF`，不呼叫 I/O 或時間 callback。唯一 active 值為 `1`，且 `resources_owned=true`、實際 `qup_version`、已取得的 `source_hz` 都必須成立。這個 boolean 是 caller 的明確承諾，不是 ownership allocator，也不是 shared resource 授權。

| API | 行為與返回值 |
| --- | --- |
| `open(fifo, io, config)` | 先 preflight / 保存設定，再啟動 RX；`AGAIN` 代表 RX command 尚未證明 active，須以 `poll()` 繼續，不可當 acquire 完成 |
| `poll(fifo)` | 檢查 RX active、errors、TX done / inactive / empty 與 time / poll budgets；不代表所有已接受的 TX bytes 都已完成 |
| `write(fifo, bytes, size, &accepted)` | 一個 command 最多 1024 bytes，每次最多 16 FIFO words / 64 bytes；回傳已成功接受的 prefix |
| `read(fifo, bytes, capacity, &received)` | 每次最多讀 16 FIFO words，另可輸出先前保留的至多 3 bytes；無資料回傳 `AGAIN` |
| `close_poll(fifo)` | 非阻塞、有界分段清理；`AGAIN` 代表 caller 必須保留資源並繼續；terminal failure 不可當 shutdown 成功 |

TX command 長度只設定一次。partial write 後，後續 `bytes` 必須指向同一筆 command 未接受的 suffix，`size` 必須恰好等於 `tx_remaining`，否則拒絕。最後不足 4 bytes 的 word 補零，但 wire 長度由 `TX_LENGTH` 決定。`tx_accepted` 只代表 callback 成功寫入 FIFO；`tx_completed` 只在 command done、master inactive、FIFO 空且所有 bytes 已接受時增加。

RX 依 FIFO word count、LAST 與 last-valid count 解包，未交付的 word suffix 保存在 context。LAST valid=0 表示 4 bytes；1–4 使用原值；5–7 或 count 超過 depth 拒絕。parity、break、FIFO read/write error、command overrun / illegal / failure 都是 terminal error，不隱藏或當正常 data。

若一個 TX/RX 呼叫已有成功 prefix，隨後 callback 失敗，該呼叫仍回傳 `OK` 加上成功數量，但 `fifo.error` / `io_fault` 已 latch；下一次操作回報失敗且不重送。失敗的 write 可能已部分生效，不能把未知 bytes 納入 `accepted`，也不能安全重試。`failed_register` / `failed_write` 保留故障位置。

### Preflight：任何寫入前的拒絕條件

第一個 register read 是 `IF_DISABLE`。bit0 為 1 立即回傳 `NO_UART`，無寄存器寫入。其餘拒絕條件為 non-UART firmware protocol、DMA mode bit0、非零 GSI events、任一 engine active、disable / cancel / abort control 尚未清除、非空 TX/RX FIFO，以及不支援的 geometry。要求 TX/RX FIFO width 均為 32 bits、TX depth 至少 1、RX depth 至少 3。

helper 不寫 `IF_DISABLE`、DMA mode / DMA resets、FIFO interface enable 或 `FORCE_DEFAULT`。不臨時開 FIFO、不切 DMA、不載入 GENI firmware、不發送 dummy TX 清殘留資料，也不繼承未知上一個 owner 的 FIFO bytes。

## 有界清理與尚未證明的硬體 gap

startup 為 20,000 us；每筆 TX 為 200,000 us；close 的 cancel 階段為 20,000 us，只有 elapsed deadline 觸發才升級一次 abort，abort / drain / restore 階段再有 20,000 us。startup / 每筆 TX 各有 2000-poll fallback，整個 close 合計最多 2000 polls。固定時鐘或過度頻繁呼叫可能先耗盡 close poll budget，直接回傳 `TIMEOUT`，不能假設一定已送 abort。caller 可在 worker context 使用約 100 us 的有界 wait；helper 自己不 sleep。

每個 poll / read / write 的 register 與 FIFO 操作數有限；elapsed 檢查需要 callback 返回才能執行。實際 wall-clock 上界仍須加上 caller 的排程間隔與單次 callback 延遲。RX transport 沒有自行終止持續 stream 的整體時間限制，QCA transaction 的 2 秒 / byte / frame / poll budgets 由既有 `fuxi_bt_probe_run()` 提供。

close 先以 manual RFR not-ready 限制接收，再對仍 active 且屬於本 context 的 command 請求 cancel；timeout 後對仍 active 的 owned command 請求 abort。它必須同時觀察以下證據，才能標示 `quiescent=true`。

- master / secondary active bit 全清除，cancel / abort control 全清除。
- 每個仍 owned 的 command 有本輪 done / cancel / abort IRQ 退休證據。單純 inactive 不足以證明剛送出、尚未顯示 active 的 command 已退休。
- TX FIFO 為空；停止後的 RX FIFO 已依實際 count / LAST 分批 drain，host pending bytes 亦已核算。

helper 接著清除本輪 IRQ status、倒序恢復 27 個保存的 writable configuration registers，再逐一 readback。全部相等、時間未超限才標示 `restored=true`、`modified=false`、`CLOSED` 並回傳 `OK`。IRQ W1C status / command 歷史是 transient，不能回復成原始歷史；`startup_master_irq` / `startup_secondary_irq` 僅保存診斷。

| gap / failure | 本輪行為 |
| --- | --- |
| cancel / abort 後 TX FIFO 仍有 words | `CLEANUP`，不送 dummy TX、不猜 reset，`restored=false` |
| IRQ ack 有了但 active 或 control 未清 | bounded `TIMEOUT`，不宣稱 quiescent |
| command 寫入成功，但一直未 active 且沒有退休 IRQ | bounded `TIMEOUT`，不以 idle snapshot 冒充已取消 |
| MMIO callback failure / ambiguous write | latch `IO`；修改過後不再嘗試額外 register 清理；保留 ownership 與 `modified` |
| register restore mismatch / restore 期間超時 | `CLEANUP` / `TIMEOUT`；即使 `quiescent=true` 也不宣稱 restored |
| 清理前完全未修改 SE | close 回傳 `OK` 是 no-op，不會設定 `quiescent` 或 `restored` |

鎖定 Linux 的 RX abort sequence 會 poll abort-control clear 並寫 `FORCE_DEFAULT`；其 FIFO TX 還有 cancel 後 dummy transfer 的特殊處理。這不是 Fuxi 上有限完成的 reset / stale-TX 清除證據。沒有找到可直接採用、已在本板證明的完整 finite hardware cleanup。本 helper 不保證成功停止故障硬體，只保證 caller 得到有界、保守的成功或失敗判定。

## 主代理最小整合入口

只需把新 `.c/.h` 納入現有 BT canonical source 路徑；沒有新的 init / boot-arg 接線。主代理在目前 sync 的 BT source additions 後、`FILES = SOURCES + HEADERS` 前補下列等價 entries，再由主代理生成 aggregate patch。

```python
SOURCES += ('fuxi_bt_geni_fifo.c',)
HEADERS += ('fuxi_bt_geni_fifo.h',)
SOURCE_PATHS.update({
    'fuxi_bt_geni_fifo.c': BLUETOOTH_SOURCE / 'fuxi_bt_geni_fifo.c',
    'fuxi_bt_geni_fifo.h': BLUETOOTH_SOURCE / 'fuxi_bt_geni_fifo.h',
})
```

生成後對應一筆新的 build entry：

```text
bsd/dev/fuxi_bt_geni_fifo.c               standard
```

CI 新增 `python3 tools/test-fuxi-bt-geni-fifo.py --sanitize`；具備 Clang/GCC 的 runner 執行 ASan/UBSan。若只先打包 helper，沒有 UART registration，`fuxibt=1` 及 default-off 行為不變。

真正的 active adapter 仍由主代理另行實作，入口維持 `fuxi_bt_register_uart(&ops)`。接線方式如下：

1. `acquire(context, 115200)` 先完成板級 ownership / resources；設定 `config`，呼叫 `open()`；若 `AGAIN`，在有限迴圈內 wait / `poll()`，直到 `OK` 或 terminal error。不可直接把 `AGAIN` 回給既有 acquire caller 當作成功。
2. `write` / `read` 轉發本 helper，遵守 prefix / suffix 合約；callbacks 的 context / mapping 持續有效。
3. `release` 在 acquire 每條失敗路徑及 transaction 結束都可被呼叫；有界驅動 `close_poll()`，同時保留原始 error 與 cleanup error，再按照下節 unwind 自己取得的 resources。
4. `now_us` / `wait_us` 由平台 worker 提供。沒有板級 adapter、owner 與 shutdown 證據以前，不註冊此 helper 到手機，也不使用 `fuxibt=2` 驗證 active UART。

## 下一板級最小 clock / pin / rail 接點

第一個接點可以只處理 **SoC 的 SE MMIO clock lease**，在另行 opt-in / owner 控制下取得並保持相關 clocks，再做 engine 唯讀 preflight；這一步不需要由 BT helper 修改 pins、WCN rails 或 BT_EN。它必須先證明 host SE / wrapper 所屬 power / interconnect 可安全存取。不要把今日 `fuxibt=1` 改成會默默投票的入口。

以下 GCC offsets 相對 `0x100000`，clock names / masks 已核對同一鎖定 Linux source。五條都是 shared-vote clock；不能把整個 `0x52010` 寫成 BT mask 或在 shutdown 恢復整個舊值。

| clock | branch offset | `0x52010` vote bit | caller 要求 |
| --- | --- | --- | --- |
| `gcc_qupv3_wrap2_core_clk` | `0x233d4` | 0 | shared 引用，整個 SE access / cleanup 期間保持 |
| `gcc_qupv3_wrap_2_s_ahb_clk` | `0x233d0` | 1 | 今日 off；需有界確認 `CLK_OFF` 清除 |
| `gcc_qupv3_wrap_2_m_ahb_clk` | `0x233cc` | 2 | shared 引用；不能因 BT 結束關掉其他 UART / SPI / I2C 使用者 |
| `gcc_qupv3_wrap2_core_2x_clk` | `0x23004` | 3 | shared 引用，保留其他 consumers |
| `gcc_qupv3_wrap2_s6_clk` | `0x1e754` | 10 | SE6 專屬 command / source ownership，仍須經共用 vote 管理 |

SE6 RCG 為 `cmd/cfg/m/n/d/dfs = 0x1e760/64/68/6c/70/74`。Linux `ftbl_gcc_qupv3_wrap2_s6_clk_src` 的 7,372,800 Hz entry 是 GPLL0_OUT_EVEN、pre-divider 1、M=384、N=15625。這是 caller clock-provider 的目標 rate，不是六個 raw register 值的直寫配方。caller 必須擁有 SE6 RCG / DFS rate control、取得 parent GPLL0 引用、使用已核對的 RCG update / lock handshake 並有 timeout；目前未實作該 clock owner。不得任意修改 shared GPLL0 rate / vote 或忽略 DFS ownership。

wrapper 版本由安全的 live read 提供，不能硬填 host model 的 `0x30090000`。helper 使用 QUP >=2.5 的 16 倍 oversampling，較舊版本使用 32 倍，並要求 `source_hz` 可被 `115200 * sampling` 整除且 divisor 在 1–4095。host 的 7,372,800 Hz / QUP3.9 組合得到 divider 4；這不是本輪實機量測。

完整 active UART 另需 **pin / WCN resource lease**。live DT `fuxi-live-20261116.dtb` 的 SE14 active / shutdown phandles 已解析核對：

| pin | active function / bias / drive | default / shutdown state |
| --- | --- | --- |
| GPIO76 CTS | `qup2_se6_l0`、bias-disable、2 mA | GPIO、bias-disable、2 mA |
| GPIO77 RTS | `qup2_se6_l1`、pull-down、2 mA | GPIO、pull-down、2 mA |
| GPIO78 TX | `qup2_se6_l2`、pull-up、2 mA | GPIO、pull-up、2 mA |
| GPIO79 RX | `qup2_se6_l3`、bias-disable、2 mA | GPIO、pull-down、2 mA |

active phandles 為 `0x26f..0x272`，default / shutdown 為 `0x26b..0x26e`。caller 應透過 pinctrl / GPIO owner 保存並驗證設定，不猜 `ctl` raw bits，不把 GPIO input sample 當 ownership 或 pinmux 證明。GPIO79 還有 wake IRQ / `qcom,wakeup-byte=0xfd`；本 helper 不實作 wake / IBS，caller 不可讓其他 wake handler 同時消耗 FIFO。

`bt_kiwi` 指定 GPIO81 BT reset / enable、GPIO82 SW_CTRL、GPIO80 WLAN reset。GPIO81 的 DT `bt_en_sleep` 是 GPIO output-low / pull-down / 2 mA。active caller 只能控制已獨占並經板級 power sequence 核對的 BT_EN，GPIO80 不屬於本 BT transport；SW_CTRL 不得擅自改成 output。WCN reset / settling 的具體次序與有限 timeout 仍需符合 Fuxi 的 owning power driver，不能照搬 sheng 的成功宣稱或猜一個延遲。

| BT supply 名稱 | live DT resource / phandle | BT request | caller 要求 |
| --- | --- | --- | --- |
| `bt-vdd18-aon` | `ldob15` / `0x2f4` | 1.8 V | 與 WLAN 等 consumer 共用；持引用，不直接改 PMIC |
| `bt-vdd-dig`、`bt-vdd-aon`、`bt-vdd-rfaOp8` | 同一 `smpe4` / `0x2fc` | 各 0.95 V | 同一實體 rail，合併 / 引用計數三個 logical supplies，不能關三次 |
| `bt-vdd-rfa1` | `smpg4` / `0x305` | 1.35 V | 保留 WLAN / RF votes |
| `bt-vdd-rfa2` | `smpg6` / `0x307` | 1.9 V | 保留 WLAN / RF votes |

已知 cmd-db identifiers 的候選 VRM base 為 `ldob15=0x40a00`、`smpe4=0x40200`、`smpg4=0x40500`、`smpg6=0x40600`。caller 必須從本次 runtime cmd-db / regulator owner 查證後才可使用；不能把 DT 的 request、VRM init voltage 或 WLAN power-up 順序混為一談。`smpe4` 的 DT init voltage 是 952 mV，而 BT request 是 950 mV。RSC TCS / RPMh serialization、CX/MX / interconnect 引用及 WCN 共用 rail lifecycle 必須由既有資源管理接點統一處理，本 helper 沒有該能力。

### Shutdown 必須是分層 ownership unwind

1. 先停止新 transaction / callback 使用，保留 SE mapping、clock / power / pin leases，完成有界 `close_poll()`。只有 `OK + quiescent + restored + !modified` 才代表本 helper 修改過的 SE 已可交回 owner。
2. 若 preflight 前完全未修改 SE，可按 acquisition ledger 撤回自己取得的引用。任何 `modified=true` 或 ambiguous MMIO / stop / restore 失敗，回報失敗並保留受影響的 SE ownership；不盲目 unmap、關 bus clock 或斷 WCN rails。獨立、有證據的板級 reset / recovery 由主代理資源 owner 處理，這裡沒有保證成功的自動補救。
3. 在 SE 已安全交回且本 transaction 獨占 BT lifecycle 的前提下，由 board owner 完成已核對的 BT_EN shutdown / pinctrl shutdown，處理 wake / IRQ ownership，再釋放 SE6 source / parent 和 wrapper 自己的 clock refs。不能以整個 register 的舊快照覆蓋其他 lane 新增的 votes。
4. 透過 regulator / WCN owner 釋放自己成功取得的 rail refs，保持 WLAN / RF 及其他使用者的 aggregate votes。GPIO80、未取得的 refs、shared GPLL0、其他 wrapper engines 都不得動。每一步記錄 acquired / released / retained、elapsed / failure；部分 acquire 失敗也遵循同一 ledger，不做全域 power-cycle。

## 已執行驗證與下一趟判準

已在本機 MSVC 14.50.35717、C11 `/W4 /WX /Od` 執行：

```sh
python tools/test-fuxi-bt-geni-fifo.py
```

結果通過：5120 組 TX length / depth（1–1024 bytes，depth 1 / 2 / 16 / 63 / 255）、2056 組 RX length / capacity、packing vector 解碼 / LAST valid=0/1–4 與 invalid 5–7、unaligned buffers、partial TX/RX、CTS block / delayed done / command visibility、preflight 無寫入、error bits、clock 倒退 / elapsed / frozen poll budgets、cancel→abort、ack 不等於 idle、stale TX 拒絕、RX drain、27-register restore / mismatch / late timeout。

獨立 emulator 覆蓋全部 open=73、close=67、TX=10、RX=7 個 callback 故障位置，分別執行 write 前失敗與 write 已生效才回報失敗兩種模式。共 314 組位置 / 模式，驗證 terminal fault 後不重試未知 MMIO、不冒充成功 restore。另直接執行既有 `fuxi_bt_probe_run()` → FIFO callbacks → 恰好 5 個 wire bytes → synthetic QCA Command Complete → production H4 / version parser → clean close，驗證 `tx_completed=5`、QCA 原值與 `quiescent/restored`。

本機沒有可用的 Clang/GCC / WSL Linux toolchain，**ASan/UBSan 尚未在此 worker 執行**。測試已支援 `--sanitize`，由主代理的 CI runner 執行。XNU8796 SDK compile / kernel link、實際 FIFO / CTS / RX_LAST timing、UART errors、cancel / abort / reset、板級 clocks / rails / pin shutdown 均未在此 worker 實機驗證。

下一趟先由主代理完成 clock-owner 接點，仍以 engine 唯讀證據為目標：五條 gates 在整段讀取期間持續安全、`off_mask=0`、`engine_read=1`、零 read fault，取得 actual wrapper version、protocol、IF_DISABLE、DMA/GSI 與 FIFO geometry。若任一條件缺失，不送 FIFO command；IF_DISABLE bit0=1 時拒絕本 helper，但不自動決定或啟動 DMA。

在獨立 opt-in 的板級 active / shutdown 接點都完成後，才考慮 `fuxibt=2`、FIFO config `opt_in=1`、實際 `qup_version/source_hz` 與 `resources_owned=true`。成功判準為實際 QCA completion / nonzero ROM 和 SoC、`tx_accepted=tx_completed=5`、原始 transaction 與 cleanup 均 `OK`、SE `quiescent/restored`，以及板級 acquisition ledger 的安全撤回。host synthetic reply 不可計入此成功判準。

## Primary sources

Linux source pin 為 `ianchb/sm8550-mainline` commit `1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c`，與本地 `work/ref-sheng/QcaBluetooth/tools/source-lock.json` 一致。本輪直接讀取以下原始檔並驗證 SHA-256，沒有使用二手 driver 摘要。

| source | SHA-256 | 核對點 |
| --- | --- | --- |
| [qcom_geni_serial.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/tty/serial/qcom_geni_serial.c) | `5bb9ba5ed694f1329eaf47d2de935bcfd0a405f63d5055a9b0ff1950890a527c` | UART cfg / flow、length→command→FIFO、partial word padding、RX LAST=0、cancel / abort / dummy TX、20 ms poll |
| [qcom-geni-se.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/soc/qcom/qcom-geni-se.c) | `993154d7a1045914bc464cb985518d3e7a7ec06769ff245f20c7435c879a0977` | IO init、FIFO/DMA/GSI 差異、四個 8-bit packing vectors / byte granularity |
| [geni-se.h](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/include/linux/soc/qcom/geni-se.h) | `e4bd79c0b3f21dafa1a6f58db8958b811605bec9cf8b6ca92fcfe076dac21a25` | offsets / masks、IF_DISABLE、active / control / IRQ、QUP-version-dependent FIFO depth |
| [gcc-sm8550.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/clk/qcom/gcc-sm8550.c) | `292630e2c5825ab947c9a649d8c4ec43303f17c5670dbda4062c13c35775b7d4` | QUP2 五條 clock / vote bits、SE6 RCG / 7,372,800 Hz frequency entry |

| register / packing | 來源定義與 helper 使用 |
| --- | --- |
| `IF_DISABLE=0x64` / firmware `0x68` | FIFO disable bit0；protocol bits15:8，UART=2 |
| status `0x40` | master active bit0，secondary active bit12 |
| TX `0x700` / RX `0x780` | 32-bit FIFO accesses |
| TX status `0x800` / RX status `0x804` | TX count bits27:0；RX count bits24:0、LAST bit31、valid bits30:28 |
| TX length `0x270` / M command `0x600` | 設 length 後，UART_START_TX opcode1 放 bits31:27 |
| S command `0x630` | FIFO RX opcode1 / params0；DMA 的 RFR_OPEN bit7 不採用 |
| M/S control `0x604/0x634` | cancel bit2、abort bit1；IRQ retirement done bit0、cancel bit4、abort bit5 |
| HW TX/RX `0xe24/0xe28` | width bits29:24；depth 在 QUP3.10 前為 bits21:16，之後為 bits23:16 |
| packing0 / packing1 / byte granularity | 四個 8-bit little-endian vectors 算得 `0x4380e / 0xc3e0e / 0` |

QCA wire contract 使用同一 pin 的 [btqca.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/bluetooth/btqca.c) / [btqca.h](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/bluetooth/btqca.h)，hash 與既有 checkpoint 相同；request 為 `01 00 fc 01 19`，WCN3991+ completion 為 `04 0e 12 <ncmd> 00 fc 00 19 00 <product4> <patch2> <rom2> <soc4>`。這是 controller version 證據，不是 Apple identity。

板級 pins / supplies 來自本地 Fuxi live DT `work/hw-survey/fuxi-live-20261116.dtb`，本輪重新核對 SHA-256 `2d7e97ea52bf67a79ef7b99487131a41bd87fc0ab774983ce62bfb9fa79fb9fa` 並解析 SE14、GPIO81、regulator phandles。其供應鏈不同於 sheng board reference；沒有從 sheng DT 推導 Fuxi rail / GPIO。
