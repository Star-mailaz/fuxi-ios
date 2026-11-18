# native-layout0013-queue1536-boot-1 證據報告（2026-11-13）

- 擷取者：Gemini 3.8（`antigravity/gemini-3.8-flash`，經 Magpie，唯讀：Read/Grep/Glob，59 turns、58 次工具呼叫、約 375 秒）。
  原始回應：同目錄 `native-layout0013-queue1536-boot-1-evidence-response.json`。
- 主代理驗收（獨立 Grep／PowerShell 重算，結果與下文一致）：
  第 3 項 swap wait 五行、第 5 項當機次數（NEW 無 backboardd／SpringBoard；BASE 4752–4755）、第 6 項 stats 與 hz、
  第 8 項 presents、第 9 項 queue、第 10 項 submit_split（NEW 第一個視窗）、第 11 項 fence waits（NEW）、
  第 13 項觸控筆數（97／14）、第 14 項 fence 編號（NEW 2851 筆、BASE 1385 筆，皆無倒退、無跳號）、
  第 15 項 NEW 溫度、第 16 項行數（9986／6552）。
  未逐項重查：第 1 項開機參數全文、第 4 項 gate、第 7 項 BASE stages、第 10–11 項 BASE 數值、第 12 項 panic 行、第 15 項 BASE 溫度。
- 使用者目視結果（日誌量不到）：「無閃爍了 流暢有待提升」。
- NEW boot.log sha256 `aeb7026471b67b71b68b29fdf17a1f882759963cdedde90db24ba1b84e3dde34`。

以下為 Gemini 報告原文。

---

兩次執行的觸控輸入不同，數字不是受控比較。

---

# Patch 0013（swap wait）開機日誌證據擷取報告

- **NEW**：`E:\Codex-Xiaomi13-GPU-20261109\native-layout0013-queue1536-boot-1\boot.log`
  監看紀錄：`E:\Codex-Xiaomi13-GPU-20261109\native-layout0013-queue1536-monitor-1.log`
- **BASE**：`E:\Codex-Xiaomi13-GPU-20261109\native-queue1536-boot-1\boot.log`
  監看紀錄：`E:\Codex-Xiaomi13-GPU-20261109\native-queue1536-monitor-1.log`

---

## 1. 開機參數

### NEW
- **檔名:行號**：`native-layout0013-queue1536-boot-1\boot.log:287`
- **原文**：
  ```
  com.apple.xpc.launchd|1969-12-31 16:00:44.278224 <Notice>: boot-args = debug=0xc serial=3 cpus=7 keepsyms=1 rd=ufsroot0 fuxi_ufs_probe=1 ufsroot=userdata ufsrw=1 rootrw=1 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 sweetlog=0 sweetfb_noconsole=1 sweetnoexec=bluetoothd,fairplayd.H2 fuxigpu=1 fuxigpuabi=1 fuximetal=native sweetnull=backboardd,SpringBoard,peakpowermanagerd,fuxi-ca-smoke fuxigpuncimport=1536 fuxibbgpu=2 fuxitouchscript=150 fuxitouchscriptn=2
  ```

### BASE
- **檔名:行號**：`native-queue1536-boot-1\boot.log:289`
- **原文**：
  ```
  com.apple.xpc.launchd|1969-12-31 16:00:42.986191 <Notice>: boot-args = debug=0xc serial=3 cpus=7 keepsyms=1 rd=ufsroot0 fuxi_ufs_probe=1 ufsroot=userdata ufsrw=1 rootrw=1 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 sweetlog=0 sweetfb_noconsole=1 sweetnoexec=bluetoothd,fairplayd.H2 fuxigpu=1 fuxigpuabi=1 fuximetal=native sweetnull=backboardd,SpringBoard,peakpowermanagerd,fuxi-ca-smoke fuxigpuncimport=1536 fuxibbgpu=2 fuxitouchscript=150 fuxitouchscriptn=2
  ```

- **兩份的參數字串是否完全相同**：是（`boot-args = ` 後續 token 完全相同）。

---

## 2. GPU 時脈

### NEW
- **檔名:行號**：`native-layout0013-queue1536-boot-1\boot.log:136`
- **原文**：
  ```
  FUXI GPU CLOCK: level=0 gpu_index=1 requested_khz=220000 gx_arc=0x340201 bw_index=0 ddr_kBps=0 ddr_requested=0 ddr_clamped=0 hfi_ack=1
  ```

### BASE
- **檔名:行號**：`native-queue1536-boot-1\boot.log:136`
- **原文**：
  ```
  FUXI GPU CLOCK: level=0 gpu_index=1 requested_khz=220000 gx_arc=0x340201 bw_index=0 ddr_kBps=0 ddr_requested=0 ddr_clamped=0 hfi_ack=1
  ```

---

## 3. Swap wait

### NEW
- `native swap wait` 行：共 5 筆
  - `native-layout0013-queue1536-boot-1\boot.log:1574`: `|backboardd| FUXI MTL: native swap wait n=1 avg_us=3663 max_us=3663 refused=0`
  - `native-layout0013-queue1536-boot-1\boot.log:4586`: `|backboardd| FUXI MTL: native swap wait n=600 avg_us=14565 max_us=47201 refused=0`
  - `native-layout0013-queue1536-boot-1\boot.log:5939`: `|backboardd| FUXI MTL: native swap wait n=1200 avg_us=14544 max_us=79001 refused=0`
  - `native-layout0013-queue1536-boot-1\boot.log:7299`: `|backboardd| FUXI MTL: native swap wait n=1800 avg_us=12480 max_us=79001 refused=0`
  - `native-layout0013-queue1536-boot-1\boot.log:8798`: `|backboardd| FUXI MTL: native swap wait n=2400 avg_us=13693 max_us=79001 refused=0`
- `swap wait refused` 行：none found（各行內 `refused=0`）

| 來源 (行號) | n | avg_us | max_us | refused |
| :--- | :--- | :--- | :--- | :--- |
| NEW (1574) | 1 | 3663 | 3663 | 0 |
| NEW (4586) | 600 | 14565 | 47201 | 0 |
| NEW (5939) | 1200 | 14544 | 79001 | 0 |
| NEW (7299) | 1800 | 12480 | 79001 | 0 |
| NEW (8798) | 2400 | 13693 | 79001 | 0 |

### BASE
- 實際筆數：0 筆（none found）

---

## 4. Gate

### NEW
- `native-layout0013-queue1536-boot-1\boot.log:813`: `|backboardd| FUXI MTL: backboardd gate new-boot reset`
- `native-layout0013-queue1536-boot-1\boot.log:814`: `|backboardd| FUXI MTL: backboardd gate allow armed strikes=0 uid=501 good_frames=120`
- `native-layout0013-queue1536-boot-1\boot.log:818`: `|backboardd| FUXI MTL: gate allow backboardd`
- `native-layout0013-queue1536-boot-1\boot.log:3181`: `|backboardd| FUXI MTL: backboardd gate good frames=120`

### BASE
- `native-queue1536-boot-1\boot.log:804`: `|backboardd| FUXI MTL: backboardd gate new-boot reset`
- `native-queue1536-boot-1\boot.log:808`: `|backboardd| FUXI MTL: backboardd gate allow armed strikes=0 uid=501 good_frames=120`
- `native-queue1536-boot-1\boot.log:814`: `|backboardd| FUXI MTL: gate allow backboardd`
- `native-queue1536-boot-1\boot.log:3051`: `|backboardd| FUXI MTL: backboardd gate good frames=120`
- `native-queue1536-boot-1\boot.log:4822`: `|backboardd| FUXI MTL: backboardd gate allow armed strikes=0 uid=501 good_frames=120`
- `native-queue1536-boot-1\boot.log:4826`: `|backboardd| FUXI MTL: gate allow backboardd`
- `native-queue1536-boot-1\boot.log:5731`: `|backboardd| FUXI MTL: backboardd gate good frames=120`

---

## 5. 當機

### NEW
- `CRASH backboardd`: none found
- `CRASH SpringBoard`: none found
- 是否有任何 `CRASH backboardd ... pc` 的 pc 值以 `ecfb4` 結尾：否
- 其他行程 CRASH 次數：
  - `fairplayd.H2`: 21 次
  - `bluetoothd`: 21 次
  - `assetsd`: 2 次
  - `driverkitd`: 1 次
  - `mediaserverd`: 1 次

### BASE
- `CRASH backboardd`：共 1 組（4 行）
  - `native-queue1536-boot-1\boot.log:4752`: `CRASH backboardd[56] sig 11 code 0x100000001 sub 0x0 slide 0x65f8000 mh 0x1040f4000`
  - `native-queue1536-boot-1\boot.log:4753`: `CRASH backboardd pc 0x10e9ecfb4 lr 0x10e9ecfa0 sp 0x16c377860 fp 0x16c3778c0 far 0x0`
  - `native-queue1536-boot-1\boot.log:4754`: `CRASH backboardd bt 0x10e9ec650 0x10d3cc604 0x10d3c8cb8 0x10d51c860 0x10d4f4144 0x10d3ab76c 0x10d3ae148 0x10d3ad968 0x10d1f2c6c 0x10af05aac`
  - `native-queue1536-boot-1\boot.log:4755`: `CRASH backboardd reason ns 2 code 0xb: (none)`
- `CRASH SpringBoard`: none found
- 是否有任何 `CRASH backboardd ... pc` 的 pc 值以 `ecfb4` 結尾：是（`native-queue1536-boot-1\boot.log:4753`，pc 值為 `0x10e9ecfb4`）
- 其他行程 CRASH 次數：
  - `fairplayd.H2`: 21 次
  - `bluetoothd`: 21 次
  - `assetsd`: 4 次
  - `driverkitd`: 1 次

---

## 6. 影格統計

### 原文行
- **NEW**:
  - `native-layout0013-queue1536-boot-1\boot.log:4491`: `SWEET FB: stats 600 frames in 99620 ms, copy avg 12371 us max 17696 us, 599 swaps, 0 not shown queued_pending=0 fifo_overflow=0 ready_skips=0 ownership_defers=0 reuse_before_show=0 wait_mode0=1470`
  - `native-layout0013-queue1536-boot-1\boot.log:6019`: `SWEET FB: stats 600 frames in 32300 ms, copy avg 11574 us max 17680 us, 600 swaps, 0 not shown queued_pending=0 fifo_overflow=0 ready_skips=0 ownership_defers=0 reuse_before_show=0 wait_mode0=2936`
  - `native-layout0013-queue1536-boot-1\boot.log:7391`: `SWEET FB: stats 600 frames in 20568 ms, copy avg 10716 us max 17640 us, 601 swaps, 0 not shown queued_pending=0 fifo_overflow=0 ready_skips=0 ownership_defers=0 reuse_before_show=0 wait_mode0=4963`
  - `native-layout0013-queue1536-boot-1\boot.log:8891`: `SWEET FB: stats 600 frames in 55103 ms, copy avg 11820 us max 17703 us, 599 swaps, 0 not shown queued_pending=0 fifo_overflow=0 ready_skips=0 ownership_defers=0 reuse_before_show=0 wait_mode0=6328`
- **BASE**:
  - `native-queue1536-boot-1\boot.log:3890`: `SWEET FB: stats 600 frames in 77169 ms, copy avg 4668 us max 17742 us, 602 swaps, 0 not shown queued_pending=0 fifo_overflow=0 ready_skips=0 ownership_defers=0 reuse_before_show=0 wait_mode0=2257`
  - `native-queue1536-boot-1\boot.log:5899`: `SWEET FB: stats 600 frames in 128372 ms, copy avg 5889 us max 17567 us, 598 swaps, 0 not shown queued_pending=0 fifo_overflow=0 ready_skips=0 ownership_defers=0 reuse_before_show=0 wait_mode0=4463`

### 整理表

| 來源 (行號) | frames | ms | copy avg | swaps | not shown | 算式 | hz |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| NEW (4491) | 600 | 99620 | 12371 us | 599 | 0 | 600 × 1000 ÷ 99620 | 6.02 Hz |
| NEW (6019) | 600 | 32300 | 11574 us | 600 | 0 | 600 × 1000 ÷ 32300 | 18.58 Hz |
| NEW (7391) | 600 | 20568 | 10716 us | 601 | 0 | 600 × 1000 ÷ 20568 | 29.17 Hz |
| NEW (8891) | 600 | 55103 | 11820 us | 599 | 0 | 600 × 1000 ÷ 55103 | 10.89 Hz |
| BASE (3890) | 600 | 77169 | 4668 us | 602 | 0 | 600 × 1000 ÷ 77169 | 7.78 Hz |
| BASE (5899) | 600 | 128372 | 5889 us | 598 | 0 | 600 × 1000 ÷ 128372 | 4.67 Hz |

---

## 7. 階段時間

### NEW
- `native-layout0013-queue1536-boot-1\boot.log:4488`: `SWEET FB: stages 600 shown swap_ready_us=0/0 ready_present_us=16301/4213403 present_submit_us=1024/5610 submit_fence_us=11343/17153 fence_start_us=28/4256 start_start_us=101672/22470544`
  - `swap_ready_us`: 0/0
  - `ready_present_us`: 16301/4213403
  - `present_submit_us`: 1024/5610
  - `submit_fence_us`: 11343/17153
- `native-layout0013-queue1536-boot-1\boot.log:6016`: `SWEET FB: stages 600 shown swap_ready_us=0/0 ready_present_us=8753/32922 present_submit_us=1139/8110 submit_fence_us=10430/17083 fence_start_us=74/7692 start_start_us=53834/2616693`
  - `swap_ready_us`: 0/0
  - `ready_present_us`: 8753/32922
  - `present_submit_us`: 1139/8110
  - `submit_fence_us`: 10430/17083
- `native-layout0013-queue1536-boot-1\boot.log:7388`: `SWEET FB: stages 600 shown swap_ready_us=0/0 ready_present_us=10323/30594 present_submit_us=1412/10054 submit_fence_us=9300/17146 fence_start_us=171/6751 start_start_us=34280/1016631`
  - `swap_ready_us`: 0/0
  - `ready_present_us`: 10323/30594
  - `present_submit_us`: 1412/10054
  - `submit_fence_us`: 9300/17146
- `native-layout0013-queue1536-boot-1\boot.log:8888`: `SWEET FB: stages 600 shown swap_ready_us=0/0 ready_present_us=9304/34576 present_submit_us=1167/8498 submit_fence_us=10649/17117 fence_start_us=113/7079 start_start_us=91838/13083611`
  - `swap_ready_us`: 0/0
  - `ready_present_us`: 9304/34576
  - `present_submit_us`: 1167/8498
  - `submit_fence_us`: 10649/17117

### BASE
- `native-queue1536-boot-1\boot.log:3887`: `SWEET FB: stages 600 shown swap_ready_us=0/0 ready_present_us=13764/35828 present_submit_us=1589/8241 submit_fence_us=3078/17124 fence_start_us=25/6748 start_start_us=63800/12603496`
  - `swap_ready_us`: 0/0
  - `ready_present_us`: 13764/35828
  - `present_submit_us`: 1589/8241
  - `submit_fence_us`: 3078/17124
- `native-queue1536-boot-1\boot.log:5896`: `SWEET FB: stages 600 shown swap_ready_us=0/0 ready_present_us=17278/1098432 present_submit_us=1603/8445 submit_fence_us=4284/17067 fence_start_us=23/5410 start_start_us=213954/60001158`
  - `swap_ready_us`: 0/0
  - `ready_present_us`: 17278/1098432
  - `present_submit_us`: 1603/8445
  - `submit_fence_us`: 4284/17067

---

## 8. Present 路徑

### NEW
- `native-layout0013-queue1536-boot-1\boot.log:4494`: `FUXI GPU: presents GPU 426 CPU 171, GPU retire avg 15982 us CPU avg 1657 us, split pin 2 lookup 0 map+TLB 0 clean 456 submit 22 wait 11439 unmap 0 us, GPU CPU-time 512 us, cache hit 592 miss 3, sleeps`
  - GPU 次數: 426，CPU 次數: 171，GPU retire avg: 15982 us
- `native-layout0013-queue1536-boot-1\boot.log:6022`: `FUXI GPU: presents GPU 392 CPU 208, GPU retire avg 15971 us CPU avg 1474 us, split pin 1 lookup 0 map+TLB 0 clean 401 submit 20 wait 10431 unmap 0 us, GPU CPU-time 454 us, cache hit 600 miss 0, sleeps`
  - GPU 次數: 392，CPU 次數: 208，GPU retire avg: 15971 us
- `native-layout0013-queue1536-boot-1\boot.log:7394`: `FUXI GPU: presents GPU 350 CPU 250, GPU retire avg 15949 us CPU avg 1629 us, split pin 1 lookup 0 map+TLB 0 clean 339 submit 17 wait 9300 unmap 0 us, GPU CPU-time 385 us, cache hit 600 miss 0, sleeps`
  - GPU 次數: 350，CPU 次數: 250，GPU retire avg: 15949 us
- `native-layout0013-queue1536-boot-1\boot.log:8894`: `FUXI GPU: presents GPU 400 CPU 200, GPU retire avg 15980 us CPU avg 1792 us, split pin 2 lookup 0 map+TLB 0 clean 421 submit 20 wait 10649 unmap 0 us, GPU CPU-time 474 us, cache hit 600 miss 0, sleeps`
  - GPU 次數: 400，CPU 次數: 200，GPU retire avg: 15980 us

### BASE
- `native-queue1536-boot-1\boot.log:3893`: `FUXI GPU: presents GPU 116 CPU 481, GPU retire avg 15928 us CPU avg 1575 us, split pin 2 lookup 0 map+TLB 2 clean 110 submit 5 wait 3104 unmap 0 us, GPU CPU-time 138 us, cache hit 592 miss 3, sleeps`
  - GPU 次數: 116，CPU 次數: 481，GPU retire avg: 15928 us
- `native-queue1536-boot-1\boot.log:5902`: `FUXI GPU: presents GPU 161 CPU 435, GPU retire avg 15971 us CPU avg 1708 us, split pin 2 lookup 0 map+TLB 1 clean 163 submit 7 wait 4327 unmap 0 us, GPU CPU-time 198 us, cache hit 591 miss 3, sleeps`
  - GPU 次數: 161，CPU 次數: 435，GPU retire avg: 15971 us

---

## 9. Queue

### NEW
- `native-layout0013-queue1536-boot-1\boot.log:6026`: `FUXI GPU ABI: queue queued 47 deepest 2 refused present 483 full 0 held 0 hold_expired 0`
- `native-layout0013-queue1536-boot-1\boot.log:7398`: `FUXI GPU ABI: queue queued 50 deepest 2 refused present 483 full 0 held 0 hold_expired 0`
- `native-layout0013-queue1536-boot-1\boot.log:8898`: `FUXI GPU ABI: queue queued 54 deepest 2 refused present 483 full 0 held 0 hold_expired 0`

### BASE
- `native-queue1536-boot-1\boot.log:3897`: `FUXI GPU ABI: queue queued 93 deepest 4 refused present 8922 full 0 held 0 hold_expired 0`
- `native-queue1536-boot-1\boot.log:5907`: `FUXI GPU ABI: queue queued 193 deepest 4 refused present 15660 full 0 held 0 hold_expired 0`

---

## 10. Submit

### NEW
- `native-layout0013-queue1536-boot-1\boot.log:4570`: `FUXI GPU ABI: submit_split n 600 us/submit total 6938.3 args 0.1 fence_wait 0.0 lookup 3.5 backend 2539.7 retry_sleep 4389.5 rest 5.2 attempts 5.0 waits 4.0 events 0.3 ibs 17.6 live_bos 341 lookup_ns_per_ib 202`
- `native-layout0013-queue1536-boot-1\boot.log:4571`: `FUXI GPU ABI: submit_split backend att 3023 ok 600 ref 2423 (busy/hold/noq/pw/full 2423/0/0/0/0) us/ok idle 23.1 frame 1.0 tlb 10.5 cache 2483.3 ring 9.2 bell 2.5 lockwait 0.4 max 0.4 refused_us 0.2`
- `native-layout0013-queue1536-boot-1\boot.log:5885`: `FUXI GPU ABI: submit_split n 600 us/submit total 7401.9 args 0.2 fence_wait 0.0 lookup 3.9 backend 3241.6 retry_sleep 4150.1 rest 5.9 attempts 5.5 waits 4.5 events 0.3 ibs 19.8 live_bos 594 lookup_ns_per_ib 199`
- `native-layout0013-queue1536-boot-1\boot.log:5886`: `FUXI GPU ABI: submit_split backend att 3317 ok 600 ref 2717 (busy/hold/noq/pw/full 2234/0/0/483/0) us/ok idle 33.6 frame 0.9 tlb 9.2 cache 3145.7 ring 9.6 bell 2.6 lockwait 3.6 max 2.5 refused_us 2.7`
- `native-layout0013-queue1536-boot-1\boot.log:7249`: `FUXI GPU ABI: submit_split n 600 us/submit total 8657.8 args 0.2 fence_wait 0.0 lookup 2.6 backend 2884.4 retry_sleep 5764.6 rest 5.8 attempts 6.3 waits 5.3 events 0.4 ibs 11.8 live_bos 659 lookup_ns_per_ib 220`
- `native-layout0013-queue1536-boot-1\boot.log:7250`: `FUXI GPU ABI: submit_split backend att 3786 ok 600 ref 3186 (busy/hold/noq/pw/full 3186/0/0/0/0) us/ok idle 22.3 frame 0.8 tlb 9.7 cache 2806.1 ring 7.7 bell 2.5 lockwait 4.1 max 1.0 refused_us 0.2`
- `native-layout0013-queue1536-boot-1\boot.log:8752`: `FUXI GPU ABI: submit_split n 600 us/submit total 7581.1 args 0.2 fence_wait 0.0 lookup 4.3 backend 3092.8 retry_sleep 4478.0 rest 5.7 attempts 5.1 waits 4.1 events 0.3 ibs 19.6 live_bos 654 lookup_ns_per_ib 219`
- `native-layout0013-queue1536-boot-1\boot.log:8753`: `FUXI GPU ABI: submit_split backend att 3078 ok 600 ref 2478 (busy/hold/noq/pw/full 2478/0/0/0/0) us/ok idle 23.1 frame 1.1 tlb 10.2 cache 3031.8 ring 10.4 bell 2.3 lockwait 1.0 max 0.5 refused_us 0.2`

### BASE
- `native-queue1536-boot-1\boot.log:3843`: `FUXI GPU ABI: submit_split n 600 us/submit total 6291.2 args 0.2 fence_wait 0.0 lookup 3.7 backend 3143.5 retry_sleep 3127.2 rest 16.5 attempts 16.1 waits 15.1 events 0.1 ibs 17.3 live_bos 446 lookup_ns_per_ib 214`
- `native-queue1536-boot-1\boot.log:3844`: `FUXI GPU ABI: submit_split backend att 9687 ok 600 ref 9087 (busy/hold/noq/pw/full 771/0/0/8316/0) us/ok idle 194.2 frame 1.0 tlb 6.7 cache 2453.4 ring 9.8 bell 2.6 lockwait 16.1 max 4.1 refused_us 13.4`
- `native-queue1536-boot-1\boot.log:5953`: `FUXI GPU ABI: submit_split n 600 us/submit total 6174.3 args 0.2 fence_wait 0.0 lookup 3.9 backend 3112.8 retry_sleep 3042.2 rest 15.0 attempts 15.2 waits 14.2 events 0.1 ibs 16.3 live_bos 547 lookup_ns_per_ib 242`
- `native-queue1536-boot-1\boot.log:5954`: `FUXI GPU ABI: submit_split backend att 9148 ok 600 ref 8548 (busy/hold/noq/pw/full 784/0/0/7764/0) us/ok idle 173.5 frame 1.0 tlb 6.5 cache 2504.4 ring 10.5 bell 2.6 lockwait 13.6 max 4.2 refused_us 13.6`

---

## 11. Fence

### NEW
- `native-layout0013-queue1536-boot-1\boot.log:4592`: `FUXI ABI: fence waits per 600 sleeping poll_us=100 avg_us=14049 max_us=44965 polls_avg=88`
- `native-layout0013-queue1536-boot-1\boot.log:5948`: `FUXI ABI: fence waits per 600 sleeping poll_us=100 avg_us=13525 max_us=77915 polls_avg=78`
- `native-layout0013-queue1536-boot-1\boot.log:7309`: `FUXI ABI: fence waits per 600 sleeping poll_us=100 avg_us=7909 max_us=45067 polls_avg=42`
- `native-layout0013-queue1536-boot-1\boot.log:8867`: `FUXI ABI: fence waits per 600 sleeping poll_us=100 avg_us=16952 max_us=54388 polls_avg=104`

### BASE
- `native-queue1536-boot-1\boot.log:3877`: `FUXI ABI: fence waits per 600 sleeping poll_us=100 avg_us=14556 max_us=47131 polls_avg=88`
- `native-queue1536-boot-1\boot.log:5985`: `FUXI ABI: fence waits per 600 sleeping poll_us=100 avg_us=15796 max_us=44065 polls_avg=96`

---

## 12. 錯誤

### NEW
- `FUXI GPU HANG`：0 筆（none found）
- `FUXI GPU: fail`：0 筆（none found）
- `0x90a`：0 筆（none found）
- `panic`（不分大小寫）：3 筆
  - `native-layout0013-queue1536-boot-1\boot.log:50`: `debug_log_init: Error!! gPanicBase is still not initialized`
  - `native-layout0013-queue1536-boot-1\boot.log:51`: `debug_log_init: Error!! gPanicBase is still not initialized`
  - `native-layout0013-queue1536-boot-1\boot.log:617`: `exec DumpPanic`
- `fence timeout`：0 筆（none found）

### BASE
- `FUXI GPU HANG`：0 筆（none found）
- `FUXI GPU: fail`：0 筆（none found）
- `0x90a`：0 筆（none found）
- `panic`（不分大小寫）：3 筆
  - `native-queue1536-boot-1\boot.log:50`: `debug_log_init: Error!! gPanicBase is still not initialized`
  - `native-queue1536-boot-1\boot.log:51`: `debug_log_init: Error!! gPanicBase is still not initialized`
  - `native-queue1536-boot-1\boot.log:618`: `exec DumpPanic`
- `fence timeout`：0 筆（none found）

---

## 13. 觸控

### NEW
- `FUXI TOUCH: contact` 筆數：97 筆（行號 2946 至 9980，contact 1 至 contact 97）
- `FUXI TOUCH:` 各訊息種類與各自筆數：
  - `FUXI TOUCH: starting in 30 s (poll 4000 us active, 8000 us idle)`: 1 筆（行號 172）
  - `FUXI TOUCH: GPI up, DMA page 0x8c51c0000`: 1 筆（行號 2861）
  - `FUXI TOUCH: reset err=0 event 03 00 00 00; chip id err=0 3640`: 1 筆（行號 2862）
  - `FUXI TOUCH: sensing, polling GPIO25`: 1 筆（行號 2863）
  - `FUXI TOUCH: IRQ line asserted`: 1 筆（行號 2864）
  - `FUXI TOUCH: contact <N>: ...`: 97 筆（行號 2946 至 9980）
  - 總計：102 筆

### BASE
- `FUXI TOUCH: contact` 筆數：14 筆（行號 3000 至 4051，contact 1 至 contact 14）
- `FUXI TOUCH:` 各訊息種類與各自筆數：
  - `FUXI TOUCH: starting in 30 s (poll 4000 us active, 8000 us idle)`: 1 筆（行號 172）
  - `FUXI TOUCH: GPI up, DMA page 0x8c51fc000`: 1 筆（行號 2937）
  - `FUXI TOUCH: reset err=0 event 03 00 00 00; chip id err=0 3640`: 1 筆（行號 2938）
  - `FUXI TOUCH: sensing, polling GPIO25`: 1 筆（行號 2939）
  - `FUXI TOUCH: IRQ line asserted`: 1 筆（行號 2940）
  - `FUXI TOUCH: contact <N>: ...`: 14 筆（行號 3000 至 4051）
  - 總計：19 筆

---

## 14. backboardd 重啟跡象

### NEW
- none found（`FUXI KMD: submit IBs <N> fence <M>` 共 2851 筆，fence 編號 M 從 1 嚴格連續遞增至 2851，無任何一筆小於前一筆）。

### BASE
- none found（`FUXI KMD: submit IBs <N> fence <M>` 共 1385 筆，fence 編號 M 從 1 嚴格連續遞增至 1385；在第 4752 行 backboardd 崩潰重啟後，fence 由第 4751 行的 946 延續至第 4858 行的 947，無任何一筆小於前一筆）。

---

## 15. 溫度

### NEW (`native-layout0013-queue1536-monitor-1.log`)
- 最高溫：
  - **檔名:行號**：`native-layout0013-queue1536-monitor-1.log:132`
  - **原文**：`thermal +80s max cpu-1-5 67.8C, silver 59.8, gold/prime 67.8, cpuss 59.6, gpu 52.5, ddr 53.1, MHz 1670.4/2707.2/2956.8`
- 最後一筆 `thermal +` 行：
  - **檔名:行號**：`native-layout0013-queue1536-monitor-1.log:595`
  - **原文**：`thermal +230s max cpu-1-8 59.9C, silver 55.1, gold/prime 59.9, cpuss 55.6, gpu 52.1, ddr 51.5, MHz 1670.4/2707.2/2956.8`

### BASE (`native-queue1536-monitor-1.log`)
- 最高溫：
  - **檔名:行號**：`native-queue1536-monitor-1.log:260`
  - **原文**：`thermal +200s max cpu-1-1 61.5C, silver 53.9, gold/prime 61.5, cpuss 54.4, gpu 47.7, ddr 48.3, MHz 1670.4/2707.2/2956.8`
- 最後一筆 `thermal +` 行：
  - **檔名:行號**：`native-queue1536-monitor-1.log:332`
  - **原文**：`thermal +230s max cpuss-0 47.3C, silver 46.7, gold/prime 47.3, cpuss 47.3, gpu 46.1, ddr 45.5, MHz 1670.4/2707.2/2956.8`

---

## 16. 總行數與監看紀錄結尾

### NEW
- `boot.log` 總行數：9986 行
- `native-layout0013-queue1536-monitor-1.log` 最後 3 行：
  - `native-layout0013-queue1536-monitor-1.log:640`: `    raise USBError(_strerror(ret), ret, _libusb_errno[ret])`
  - `native-layout0013-queue1536-monitor-1.log:641`: `usb.core.USBError: [Errno 2] Entity not found`
  - `native-layout0013-queue1536-monitor-1.log:642`: `monitor_exit=0`

### BASE
- `boot.log` 總行數：6552 行
- `native-queue1536-monitor-1.log` 最後 3 行：
  - `native-queue1536-monitor-1.log:354`: `    raise USBError(_strerror(ret), ret, _libusb_errno[ret])`
  - `native-queue1536-monitor-1.log:355`: `usb.core.USBError: [Errno 2] Entity not found`
  - `native-queue1536-monitor-1.log:356`: `monitor_exit=0`

---

實際工具呼叫次數：58 次。