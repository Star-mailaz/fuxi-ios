# 第十八／十九趟實機紀錄核對

日期：2026-11-16。初稿由 `auto/gemini-3.8-flash`、high 推理整理主代理提供的日誌片段；主代理依完整本機日誌核對後收錄。原始回覆保留在本輪 visualization 目錄的 `gemini-log-summary.txt`。本檔不把日誌整理視為新的硬體驗收。

| 趟次 | 主機流程開始 | fastboot boot | Android 回程及釋鎖 | Host TSENS 最高值 |
| --- | --- | --- | --- | --- |
| 18：torchraw | 16:14:14 | 16:14:34 | 16:21:22 | 48.5°C |
| 19：W18 no-MLO | 16:23:53 | 16:24:13 | 16:31:04 | 51.7°C |

時間／溫度來源：`D:/xiaomi13/fuxi_ios/work/statusbar-fix/hw000torchraw-120s-20261116.log` 及 `hw000w18-oem-nomlo-20261116.log`，兩檔的第6、21、33、34、35行。主機流程開始不等於核心啟動時間。

## Torch：有嘗試，持續亮光尚未通過

- `boot.log:3684` 有 `request=4 current=80mA lease=2000ms`；`3686` 記錄 `stopped rc=-5; reboot required`。`pulses=0` 是成功完成脈衝的計數，不能據此說沒有實際嘗試。
- `3738` 的 audit 共49筆、dropped=0。全部49筆的 I/O `rc=0`；這不等於脈衝或故障條件成功。
- `3727` 的 audit 38 為 post-disable `op=R offset=0x9 value=0x10 rc=0`；前兩次同 offset 的讀值為0（`3699`、`3716`）。
- 兩組 off 讀回都為 `0x4e=0`、`0x46=0`，rc=0（`3717`至`3724`）；restore 後 `0x3e=0x93`、`0x42=0`、`0x49=0`、`0x4a=1` 均讀回相符，最後再確認輸出關閉（`3728`至`3737`）。
- 上述只證明本趟控制／關閉／還原與拒絕紀錄。可見亮光、持續輸出及自主硬體截止未由這些紀錄證明。

上述 `boot.log` 的完整路徑：`D:/xiaomi13/fuxi_ios/work/Codex-Xiaomi13-GPU-20261109/native-hw000torchraw-120s-boot-1/boot.log`。

## WLAN：no-MLO 仍停在 FW_READY

- `1007` 記錄 `REQUEST_MEM stage 2 queued before HOST_CAP reply`。這是有被排隊處理的時序觀察，尚無證據證明它造成後續 timeout。
- `2642`、`2643` 記錄等待 W14 `FW_READY` indication 10000ms 後 failure、contain、no retry。未觀察到 MODE 成功、掃描或網路連線。
- `2689` 開始 undo；`2690` 的 host entries pending=0、WLAN power contained result=done。
- `2691` 的 CB6 SCTLR 寫0讀回0、faults=0；`2693` 記錄 SMR invalid、S2CR restored、CB disabled、TLBI synced；`2694` 記錄 RC bypass restored first、256 owned entries zeroed。
- 原廠 REGDB／BDF／M3 路徑走通與 undo 紀錄，不能把 no-MLO 當修復或 Wi-Fi 可用驗收。

上述 `boot.log` 的完整路徑：`D:/xiaomi13/fuxi_ios/work/Codex-Xiaomi13-GPU-20261109/native-hw000w18-oem-nomlo-boot-1/boot.log`。

下一次 WLAN 比較固定同一 baseline，只改有原廠模組證據的 HOST_CAP SECONDARY opt-in；不混入 MLO、DDR IOVA、MSI 或 readiness 規則變更。Torch 保留非零 status 拒絕、限流及 failed latch，另查 matched register／timer 契約，不以原始讀值猜測故障語義。
