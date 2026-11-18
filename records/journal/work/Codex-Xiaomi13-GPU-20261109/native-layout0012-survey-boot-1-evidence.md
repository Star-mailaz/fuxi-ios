# Patch 0012 啟動日誌分析與證據報告 (Evidence Extraction Report)

本報告針對 Xiaomi 13 (Fuxi) 於 Patch 0012 啟動過程之日誌 (`native-layout0012-survey-boot-1\boot.log`) 進行唯讀證據擷取，並與 Patch 0011 (`native-layout0011-survey-boot-1\boot.log`) 進行對照分析。

---

## 1. Gate (Metal 閘門狀態)

### 完整相符日誌行（`backboardd gate`）
- `boot.log:813`: `|backboardd| FUXI MTL: backboardd gate new-boot reset`
- `boot.log:816`: `|backboardd| FUXI MTL: backboardd gate allow armed strikes=0 uid=501 good_frames=120`
- `boot.log:3381`: `|backboardd| FUXI MTL: backboardd gate good frames=120`

### 相關閘門日誌行
- `boot.log:820`: `|backboardd| FUXI MTL: gate allow backboardd`
- `boot.log:841`: `|backboardd| FUXI MTL: constants observe mode=allow ctor_us=47053655 gate_us=47075090 install_us=47214067 hooks=15`
- `boot.log:1630`: `|SpringBoard| FUXI MTL: gate deny SpringBoard`
- `boot.log:1631`: `|SpringBoard| FUXI MTL: constants observe mode=deny ctor_us=53359874 gate_us=53359918 install_us=0 hooks=0`

### 判定與說明
- **backboardd 是否准入 (admitted)？**
  是。backboardd 於 `boot.log:816` 成功布防准入（`armed strikes=0 uid=501 good_frames=120`），並於 `boot.log:820` 正式准入（`gate allow backboardd`）。
- **後續是否有任何 deny 或 runtime-failure？**
  完全沒有。日誌中完全沒有出現 `gate deny backboardd` 或 `gate runtime-failure`。相反地，backboardd 持續成功渲染，並在 `boot.log:3381` 達到 `good frames=120` 的健康門檻，閘門保持穩定允許。

---

## 2. Import (線性快照紋理匯入)

### 完整相符日誌行（所有包含 `FUXI LINEAR` 之行）
- `boot.log:3197`: `|backboardd| FUXI LINEAR: foreign snapshot imported format=204 width=1125 height=2436 bytes=2747808 length=2752512 deallocator=0`
- `boot.log:3200`: `|backboardd| FUXI LINEAR: foreign snapshot imported format=204 width=1125 height=2436 bytes=2747808 length=2752512 deallocator=0`
- `boot.log:3711`: `|backboardd| FUXI LINEAR: foreign snapshot imported format=204 width=1125 height=2436 bytes=2747808 length=2752512 deallocator=0`

### 數據統計
- **`foreign snapshot imported` 行數**：共 3 次（分別於 `boot.log:3197`、`boot.log:3200`、`boot.log:3711`）。
- **紋理參數**：
  - `format`: 204 (ASTC 4x4)
  - `width`: 1125
  - `height`: 2436
  - `bytes`: 2747808
  - `length`: 2752512
  - `deallocator`: 0
- **是否有其他 `FUXI LINEAR` 訊息？**
  無（全日誌僅有上述 3 行）。

---

## 3. Refusals (拒絕與未實作項)

搜尋目標模式：`is not implemented`、`native refusal`、`command buffer refused`、`texture reject`、`IOSurface refused`、`FUXI NOCOPY`、`survey summary`、`registered linear texture`。

- **搜尋結果**：**none found**（全日誌 0 處相符）。
- 在 Patch 0011 中出現的 `newTextureWithBytesNoCopy... is not implemented`、`command buffer refused: setRenderPipelineState: null handle`、`survey summary distinct=3 refusals=33` 等拒絕在 Patch 0012 中完全絕跡。

---

## 4. Frames (影格統計)

### 首次影格時間 (`first_frame_ms`)
- `boot.log:1559`: `|backboardd| FUXI MTL: backboardd first_frame_ms=5957.134 gpu_ms=3.034`

### 完整影格記錄表 (`FUXI MTL: backboardd frames=`)
全日誌共有 28 次定期報告，各欄位彙整如下：

| 行號 (`boot.log`) | `frames` (累積) | `gpu_ms` (平均) | `late` (累積) | `failures` (累積) | `hz` (當期頻率) | `window_frames` (當期影格) |
|---|---|---|---|---|---|---|
| 1458 | 0 | 0.000 | 0 | 0 | 0.00 | 0 |
| 1996 | 3 | 2.538 | 0 | 0 | 0.60 | 3 |
| 2870 | 30 | 5.462 | 12 | 0 | 2.70 | 27 |
| 2875 | 30 | 0.000 | 12 | 0 | 0.00 | 0 |
| 2918 | 30 | 0.000 | 12 | 0 | 0.00 | 0 |
| 2939 | 30 | 0.000 | 12 | 0 | 0.00 | 0 |
| 2960 | 30 | 0.000 | 12 | 0 | 0.00 | 0 |
| 2963 | 30 | 0.000 | 12 | 0 | 0.00 | 0 |
| 2984 | 30 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3007 | 30 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3029 | 31 | 12.890 | 12 | 0 | 0.10 | 1 |
| 3032 | 31 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3053 | 31 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3074 | 31 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3095 | 31 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3116 | 31 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3117 | 31 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3138 | 31 | 0.000 | 12 | 0 | 0.00 | 0 |
| 3161 | 32 | 6.610 | 12 | 0 | 0.10 | 1 |
| 3363 | 107 | 10.295 | 62 | 0 | 7.50 | 75 |
| 3516 | 208 | 15.019 | 160 | 0 | 20.19 | 101 |
| 3763 | 277 | 30.025 | 224 | 0 | 6.90 | 69 |
| 4340 | 486 | 13.494 | 392 | 0 | 20.87 | 209 |
| 4560 | 565 | 28.540 | 466 | 0 | 15.74 | 79 |
| 4701 | 612 | 21.906 | 508 | 0 | 4.72 | 47 |
| 4703 | 613 | 16.200 | 509 | 0 | 0.20 | 1 |
| 4724 | 613 | 0.000 | 509 | 0 | 0.00 | 0 |
| 4725 | 613 | 0.000 | 509 | 0 | 0.00 | 0 |

### 分析結論
- **`frames` 是否嚴格遞增 (strictly increasing)？**
  否。`frames` 呈現單調不減（monotonically non-decreasing）。在沒有新畫面的閒置區間（`window_frames=0, hz=0.00`），數值維持不變；在有觸控動畫時迅速增加，總計從 0 增長至 613。
- **最終數值**：`613`（`boot.log:4703`, `4724`, `4725`）。
- **`failures` 最大值**：`0`（全程零失敗）。
- **`late` 最大值**：`509`（累積 509 幀超過 16.67 ms 牆上時脈門檻）。

---

## 5. Process Health (程序健康狀態)

### 關鍵程序啟動與生命週期
- **backboardd (PID 56)**：
  - `boot.log:642`: `exec backboardd`
  - 全程未發生 exit、crash、abort 或 respawn，持續運行至日誌結束。
- **SpringBoard (PID 26)**：
  - `boot.log:542`: `exec SpringBoard`
  - `boot.log:1630`: `|SpringBoard| FUXI MTL: gate deny SpringBoard`（如預期維持 CPU 模式）
  - `boot.log:3372`: `SWEET SURF: SpringBoard create id 49 1125x2436 fmt 0x62336138 bpe 4 bpr 4544 planes 2 size 13877248 keys 6 -> 0x0`
  - `boot.log:3707`: `|SpringBoard| 1969-12-31 16:03:27.-686 SpringBoard[26:239]`
  - `boot.log:3708`: `|SpringBoard| Unbalanced calls to begin/end appearance transitions for <SBSwitcherViewController: 0x100743e00>.`
  - `boot.log:4567-4594`: 持續輸出 `|SpringBoard| trying to set state of nil layer.`
  - 全程無 crash、無 exit，正常執行。
- **PosterBoard**：
  - `boot.log:1857`: `exec PosterBoard`
  - `boot.log:1979`: `SWEET AKS: PosterBoard sel 0 arg0 0 in 0/0 out 0/0 -> 0x0`
  - `boot.log:1980`: `SWEET AKS: PosterBoard sel 7 arg0 0 in 1/0 out 1/0 -> 0x0`
  - `boot.log:2065-2066`: `SWEET AKS: PosterBoard sel 17 ...`
  - 正常運行，無 crash。

### 核心崩潰與資源警告（Panic / Jetsam / EXC_）
- **Kernel Panic**：無（0 筆）。
- **Jetsam**：無殺進程事件，僅有初始化時 launchd 警告：
  - `boot.log:285`: `com.apple.xpc.launchd|1969-12-31 16:00:44.618252 <Error>: Could not opt into 50 MB Jetsam high watermark: 22: Invalid argument`
- **EXC_RESOURCE**（僅為背景守護進程達到執行緒上限抑制通知，非 crash）：
  - `boot.log:1301`: `process duetexpertd[158] crossed thread count high watermark (32), EXC_RESOURCE supressed...`
  - `boot.log:1898`: `process contextstored[55] crossed thread count high watermark (32), EXC_RESOURCE supressed...`
  - `boot.log:1977`: `process suggestd[140] crossed thread count high watermark (32), EXC_RESOURCE supressed...`

### 其他背景崩潰進程說明
日誌中所有的 `CRASH` 均來自非渲染後台服務（如 `bluetoothd`、`fairplayd.H2`、`driverkitd`、`assetsd`、`mediaserverd`），完全不影響 backboardd 與 SpringBoard 之運行。

### 總結
backboardd **未曾重啟**（PID 56 自第 642 行起存活至結尾），SpringBoard **正常運行且活躍響應觸控事件**。

---

## 6. Touch / Display (面板與觸控狀態)

精選代表性日誌行（上限 20 行）：
1. `boot.log:70`: `SWEET HID: touch registered`
2. `boot.log:76`: `SWEET FB: present up to 60 Hz (every 1 ticks, tick 16666979 ns)`
3. `boot.log:78`: `SWEET FB: AppleCLCD 1080x2400 stride 4320 at 0xb8000000, default surface 1, presented as 1125x2436`
4. `boot.log:1476`: `SWEET FB: display on`
5. `boot.log:1559`: `|backboardd| FUXI MTL: backboardd first_frame_ms=5957.134 gpu_ms=3.034`
6. `boot.log:1560`: `SWEET FB: swap 1 layer 0 surface 2 1125x2436 fmt 0x42475241 bpr 4608 a 0,0 1125x2436 b 0,0 1125x2436`
7. `boot.log:1570`: `SWEET HID: touch detection mode 0xff`
8. `boot.log:1615`: `SWEET FB: display off`
9. `boot.log:2055`: `SWEET FB: display on`
10. `boot.log:2057`: `SWEET HID: touch detection mode 0x1`
11. `boot.log:2876`: `FUXI TOUCH: GPI up, DMA page 0x8c5230000`
12. `boot.log:2877`: `FUXI TOUCH: reset err=0 event 03 00 00 00; chip id err=0 3640`
13. `boot.log:2879`: `FUXI TOUCH: IRQ line asserted`
14. `boot.log:3162`: `FUXI TOUCH SCRIPT: loop 1 start`
15. `boot.log:3163`: `SWEET HID: touch 0 down at 540,2390 edge`
16. `boot.log:3377`: `SWEET HID: touch 0 down at 900,1300`
17. `boot.log:3386`: `SWEET HID: touch 0 up at 180,1300`
18. `boot.log:3764`: `FUXI TOUCH SCRIPT: loop 1 done`
19. `boot.log:3765`: `FUXI TOUCH SCRIPT: loop 2 start`
20. `boot.log:4539`: `SWEET FB: stats 600 frames in 212724 ms, copy avg 5270 us max 17694 us, 601 swaps, 0 not shown queued_pending=0 fifo_overflow=0 ready_skips=0 ownership_defers=0 reuse_before_show=0 wait_mode0=1844`

---

## 7. Comparison (Patch 0012 與 Patch 0011 對照)

| 評估項目 | OLD Boot (Patch 0011) | NEW Boot (Patch 0012) |
|---|---|---|
| **Gate 狀態** | `0011:792` armed allow -> `0011:2708` runtime-failure next-respawn=CPU persisted=1 -> `0011:3138` deny strikes=1 -> `0011:3139` gate deny backboardd | `0012:816` armed allow -> `0012:820` gate allow -> `0012:3381` gate good frames=120；**無任何 failure 或 deny** |
| **Import 快照** | `0011` 中完全無 `FUXI LINEAR` 行（匯入未實作，觸發未實作拒絕） | `0012:3197, 3200, 3711` 共 3 次成功匯入 ASTC 4x4 (format=204, 1125x2436, bytes=2747808) |
| **Refusals** | `0011:3076` 統計 `distinct=3 refusals=33`（包含 `0011:2706` unimplemented、`0011:2713` command buffer refused 等） | `0012` 中 **0 次拒絕**（none found） |
| **Frames 數量** | `0011:2990` 停滯於 `frames=26`（因 failure latch 中斷渲染），`failures=33`，`late=3` | `0012:4703` 達到 `frames=613`，`failures=0`，`late=509`，持續合成直至重置 |
| **首影格延遲** | `0011:1578` first_frame_ms=6026.471 gpu_ms=3.035 | `0012:1559` first_frame_ms=5957.134 gpu_ms=3.034 |

---

## 8. Monitor Log (監控日誌檢驗)

監控檔案：`E:\Codex-Xiaomi13-GPU-20261109\native-layout0012-survey-monitor-1.log`

### 前 10 行（每行截斷至 300 字元）
```text
1: [MONITOR] Waiting for Fuxi USB probe (VID 0x1209, PID 0x0001)...
2: [MONITOR] Found probe device in 0.0s!
3: USB monitor active on cpu@100
4: monitor reset deadline: +4 min
5: touch power ['0x6', '0x0', '0x0', '0x0', '0x0', '0x0', '0x0', '0x10', '0x0', '0x3', '0x0', '0x0', '0x3640', '0x0', '0x0', '0x0', '0xb606', '0xa307', '0x4', '0x4', '0x443c0200', '0x80004000', '0x0', '0x80000002', '0x4000', '0x4000', '0x0', '0x443c0200', '0x4000', '0x0', '0x80000002', '0x4000', '0x4000', 
6: {'stage': 4}
7: {'stage': 5}
8: {'stage': 8, 'kernel_stage': 4, 'kernel_label': 'kprintf startup complete', 'console_total': 5478}
9: {'stage': 8, 'kernel_stage': 4, 'kernel_label': 'kprintf startup complete', 'console_total': 5762}
10: {'stage': 8, 'kernel_stage': 4, 'kernel_label': 'kprintf startup complete', 'console_total': 6918}
```

### 後 15 行（行 240 至 254，每行截斷至 300 字元）
```text
240:     (args.out/'display-after.bin').write_bytes(request(0x42,432))
241:                                                ^^^^^^^^^^^^^^^^^
242:   File "D:\xiaomi13\fuxi_ios\ios-fuxi\tools\fuxi-xnu-monitor.py", line 258, in request
243:     data = bytes(dev.ctrl_transfer(0xc0, number, value, index, length, timeout=timeout))
244:                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
245:   File "%USERPROFILE%\AppData\Roaming\Python\Python312\site-packages\usb\core.py", line 1093, in ctrl_transfer
246:     ret = self._ctx.backend.ctrl_transfer(
247:           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
248:   File "%USERPROFILE%\AppData\Roaming\Python\Python312\site-packages\usb\backend\libusb1.py", line 897, in ctrl_transfer
249:     ret = _check(self.lib.libusb_control_transfer(
250:           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
251:   File "%USERPROFILE%\AppData\Roaming\Python\Python312\site-packages\usb\backend\libusb1.py", line 604, in _check
252:     raise USBError(_strerror(ret), ret, _libusb_errno[ret])
253: usb.core.USBError: [Errno 2] Entity not found
254: monitor_exit=0 
```

### 監控是否因有界重置 (bounded reset) 結束？
**是**。
日誌第 4 行設定 `monitor reset deadline: +4 min`，監控指令稿之取樣主迴圈執行了整整 4 分鐘（240 秒）。在 240 秒倒數計時屆滿時主迴圈正常結束，指令稿隨後嘗試執行第 520 行之結尾讀取 `(args.out/'display-after.bin').write_bytes(...)`。此時設備端預設之 4 分鐘硬體重置期限已到，目標手機觸發了重置重啟，導致 USB probe 離線斷開，引發 `usb.core.USBError: [Errno 2] Entity not found`，監控程序以此有界安全退出（`monitor_exit=0`）。

---

## 9. Frame Pacing (影格節奏與延遲分析)

### 9.1 相鄰影格報告之增量與延遲比例 (Delta Table)

由 `BackboardGate.hpp:98` 定義：`if(wallMS > 1000.0/60.0) ++late;`，凡影格耗時超過 16.667 ms 即計入 `late`。

| 區間 (`boot.log` 行號) | $\Delta \text{frames}$ | $\Delta \text{late}$ | 該區間延遲比例 ($\Delta \text{late} / \Delta \text{frames}$) | 備註 |
|---|---|---|---|---|
| 1458 $\rightarrow$ 1996 | 3 | 0 | 0.0% (0/3) | 早期畫面，未逾時 |
| 1996 $\rightarrow$ 2870 | 27 | 12 | 44.44% (12/27) | 開始出現介面更新 |
| 2870 $\rightarrow$ 2875 | 0 | 0 | N/A | 閒置 |
| 2875 $\rightarrow$ 2918 | 0 | 0 | N/A | 閒置 |
| 2918 $\rightarrow$ 2939 | 0 | 0 | N/A | 閒置 |
| 2939 $\rightarrow$ 2960 | 0 | 0 | N/A | 閒置 |
| 2960 $\rightarrow$ 2963 | 0 | 0 | N/A | 閒置 |
| 2963 $\rightarrow$ 2984 | 0 | 0 | N/A | 閒置 |
| 2984 $\rightarrow$ 3007 | 0 | 0 | N/A | 閒置 |
| 3007 $\rightarrow$ 3029 | 1 | 0 | 0.0% (0/1) | 單幀更新 |
| 3029 $\rightarrow$ 3032 | 0 | 0 | N/A | 閒置 |
| 3032 $\rightarrow$ 3053 | 0 | 0 | N/A | 閒置 |
| 3053 $\rightarrow$ 3074 | 0 | 0 | N/A | 閒置 |
| 3074 $\rightarrow$ 3095 | 0 | 0 | N/A | 閒置 |
| 3095 $\rightarrow$ 3116 | 0 | 0 | N/A | 閒置 |
| 3116 $\rightarrow$ 3117 | 0 | 0 | N/A | 閒置 |
| 3117 $\rightarrow$ 3138 | 0 | 0 | N/A | 閒置 |
| 3138 $\rightarrow$ 3161 | 1 | 0 | 0.0% (0/1) | 單幀更新 |
| 3161 $\rightarrow$ 3363 | 75 | 50 | 66.67% (50/75) | 觸控滑動開始 |
| 3363 $\rightarrow$ 3516 | 101 | 98 | 97.03% (98/101) | 高速連續觸控動畫 |
| 3516 $\rightarrow$ 3763 | 69 | 64 | 92.75% (64/69) | 密集繪製與快照匯入 |
| 3763 $\rightarrow$ 4340 | 209 | 168 | 80.38% (168/209) | 觸控測試循環 2 |
| 4340 $\rightarrow$ 4560 | 79 | 74 | 93.67% (74/79) | 密集渲染區間 |
| 4560 $\rightarrow$ 4701 | 47 | 42 | 89.36% (42/47) | 觸控測試尾聲 |
| 4701 $\rightarrow$ 4703 | 1 | 1 | 100.0% (1/1) | 最後提交幀 |
| 4703 $\rightarrow$ 4724 | 0 | 0 | N/A | 閒置 |
| 4724 $\rightarrow$ 4725 | 0 | 0 | N/A | 閒置 |

- **全期累計統計**：總影格數 $613$，累積延遲影格 $509$，整體延遲率為 $509 / 613 = 83.03\%$。

### 9.2 完整影格報告字串引用 (Line 4703)
以下完整引用包含全部計數器名稱之單行記錄（對應源碼 `BackboardGate.hpp:118`）：
```text
|backboardd| FUXI MTL: backboardd frames=613 gpu_ms=16.200 late=509 failures=0 sampling_skipped=0 hz=0.20 window_frames=1 gpu_busy_est_pct=0.3 tex_pool_hits=0 tex_pool_misses=0 tex_pool_trims=0 tex_pool_bytes=0 tex_pool_wasted=0 tex_pool_idle_trims=0 tex_pool_pressure_trims=0 tex_pool_reject_full=0 tex_pool_reject_budget=0 tex_pool_class_hits=- tex_pool_class_misses=- tex_pool_miss_causes=- slab_hits=0 slab_grows=0 slab_grow_cold=0 slab_grow_frag=0 slab_grow_full=0 slab_grow_refused=0 slab_frees=0 slab_trims=0 slab_bytes=0 slab_free_bytes=0 buf_pool_hits=0 buf_pool_misses=0 buf_pool_trims=0 buf_pool_bytes=0 surface_import_hits=0 surface_import_misses=0
```

### 9.3 最後報告行之非零計數器列表
- 於 `boot.log:4703`（最後有渲染活動之統計區間）：
  - `frames`: `613`
  - `gpu_ms`: `16.200`
  - `late`: `509`
  - `hz`: `0.20`
  - `window_frames`: `1`
  - `gpu_busy_est_pct`: `0.3`
- 於 `boot.log:4725`（日誌結尾純閒置行）：
  - `frames`: `613`
  - `late`: `509`
  - （其餘計數器皆為 0 或 `-`）

### 9.4 延遲原因日誌線索檢索（分組代表性日誌行）
搜尋 backboardd 與核心顯示路徑輸出之 `SWEET FB`、`FUXI GPU`、`FUXI GPU ABI`、`FUXI KMD` 等相關紀錄：

1. **Vsync 與顯示設定**：
   - `boot.log:76`: `SWEET FB: present up to 60 Hz (every 1 ticks, tick 16666979 ns)`
   - `boot.log:4537`: `SWEET FB: stages+ samples=600/600/600/600/600/599 callbacks_vsync=12762 poll=0 wake=0 callbacks_per_shown_x1000=21270/0/0`
2. **GPU 核心執行與引退時間 (GPU Retire Latency)**：
   - `boot.log:4542`: `FUXI GPU: presents GPU 137 CPU 459, GPU retire avg 15870 us CPU avg 1703 us, split pin 2 lookup 0 map+TLB 1 clean 140 submit 6 wait 3659 unmap 0 us, GPU CPU-time 174 us, cache hit 591 miss 3, sleeps`
   - *分析*：平均 GPU retire 耗時高達 15.870 ms (`15870 us`)，單是硬體引退就幾乎吃滿整個 16.667 ms 預算。
3. **GPU ABI 調用延遲 (Submit / Wait Overhead)**：
   - `boot.log:4544`: `FUXI GPU ABI: calls n/avg/max us lock 6675/2.0/2089 query 3/34.8/37 alloc 772/186.3/20714 map 989/21.9/1931 free 676/54.7/4286 submit 570/8393.0/31927 wait 2075/5216.4/58069 status 573/27.6/716 cpu-token 771/1.2/98 cpu-unmap 27/0.8/4 device-info 2/55.8/73FUXI GPU ABI: calls n/avg/max us import 217/152.7/2235`
   - *分析*：`submit` 平均耗時 8.393 ms（最大 31.927 ms）；`wait` 平均耗時 5.216 ms（最大 58.069 ms）。
4. **顯示管線階段統計 (Pipeline Stage Latency)**：
   - `boot.log:4536`: `SWEET FB: stages 600 shown swap_ready_us=0/0 ready_present_us=19066/4165669 present_submit_us=1646/9591 submit_fence_us=3622/17080 fence_start_us=24/5799 start_start_us=290406/60016727`
   - *分析*：`ready_present_us` 平均為 19.066 ms (`19066 us`)，`submit_fence_us` 平均 3.622 ms。
5. **Framebuffer 複製耗時 (FB Copy)**：
   - `boot.log:4539`: `SWEET FB: stats 600 frames in 212724 ms, copy avg 5270 us max 17694 us, 601 swaps, 0 not shown queued_pending=0 fifo_overflow=0 ready_skips=0 ownership_defers=0 reuse_before_show=0 wait_mode0=1844`
   - *分析*：Framebuffer copy 平均 5.270 ms（最大 17.694 ms）。
6. **Swapwait 與佇列狀況**：
   - `boot.log:4541`: `SWEET FB: swapwait busy_mode0=891 busy_mode1=140 timeouts=0 busy_per_swap_x1000=1715 busy_swap_max=21 intervals_1=271 busy_before_1=203 intervals_2plus=263 busy_before_2plus=100`
   - `boot.log:4547`: `SWEET FB: unshown paths stale=0 not_ready=0 superseded=0 failed_copy=0 fifo=0 refused_full=0 replaced=0 lost=0 sum=0 of 0 not shown; outside it stop=0 rejected=0; counted shown spin_started=0`
   - *分析*：無任何未顯示幀（`0 not shown`），無 FIFO 溢位。
7. **快取維護與命令提交**：
   - `boot.log:4546`: `FUXI GPU ABI: submits 570 ibs 13392 max 123 over16 257 peak_bos 849 wptr writes 707 dropped 0 repeated 0 stuck 0 stall kicks 0 drains 0 acks 0/0 kick_ok 0 drain_ok 0 snaps 0`
   - `boot.log:3388, 3390, 4338`: `FUXI GPU: copy source wb_skip 0 pre_cleaned 0 cleaned_after_coh 0`（共出現 157 次）
   - `boot.log:3190, 3370, 4702`: `|backboardd| TU: info: FUXI KMD: submit IBs ... fence ...`（共出現 618 次提交，最後 fence 為 618）

### 9.5 數值範圍與開放問題 (Open Questions)
- **數值範圍**：
  - `gpu_ms`：活躍渲染區間介於 **2.538 ms**（`boot.log:1996`）至 **30.025 ms**（`boot.log:3763`）；閒置時為 `0.000 ms`。
  - `hz`：活躍渲染區間介於 **0.10 Hz**（`boot.log:3029`）至 **20.87 Hz**（`boot.log:4340`）；閒置時為 `0.00 Hz`。
- **日誌所揭露之延遲原因**：
  影格耗時超過 16.67 ms（產生 `late`）並非由架構拒絕或管線重啟所造成，而是**多階段耗時疊加**的物理限制：GPU 著色器與引退時間平均達 15.87 ms，加上 KMD 提交（均值 8.39 ms）、同步柵欄等待（均值 5.22 ms）與 Framebuffer 複製（均值 5.27 ms），導致觸控滑動期間的總牆上週期多數落在 25~45 ms 區間。
- **待確認開放問題 (Open Questions)**：
  1. 當前 Adreno GPU 之時脈頻率是否被鎖定在較低的省電檔位（低效能 P-state）導致繪製時間拉長？
  2. Framebuffer copy 是否可透過零複製 (Zero-Copy) 或硬體 Direct Scanout 取代目前的內核緩衝區複製？
  3. KMD submit 與 wait 的 CPU-GPU 同步調度是否有簡化批次 (batching) 的調優空間？

---

## Verdict (最終判定)

**GPU_COMPOSITION_SUSTAINED**

### 判定依據與說明
1. backboardd 於啟動時成功獲准進入 Metal GPU 合成閘門（`boot.log:816`, `820`），且在成功渲染 120 幀後正式達成健康標記（`boot.log:3381`），全程未發生任何閘門拒絕或執行期崩潰。
2. Patch 0012 成功實作線性紋理匯入，3 次順利導入先前導致拒絕的 format=204 快照紋理（`boot.log:3197`, `3200`, `3711`），使舊版 33 次拒絕全部歸零。
3. backboardd 全程零失敗（`failures=0`）穩定運行至 613 影格與 618 次 GPU 柵欄提交（`boot.log:4702`, `4703`），完整支撐 SpringBoard 觸控互動，直至 4 分鐘有界監控到期重置。

### 明確未能自日誌判定之事項
本分析係基於純日誌證據提取；雖然 `SWEET FB` 統計記錄顯示 600 個影格皆成功呈現且無掉幀（`boot.log:4539`: `0 not shown`），但在缺乏實體高速攝影機拍攝之情況下，無法僅憑日誌百分之百驗證實體 OLED 面板發光輸出的視覺無瑕度。
