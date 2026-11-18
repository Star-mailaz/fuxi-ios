# 日常 v8 合併比較（2026-11-18）

基底為手機日常 `chain-v7-ram9g-rtctorch`，合併候選為 `chain-v8-dualboot-wifi`。候選逐位元沿用最新三按鈕 `menu-direct-launch-20261118`，內含先前可用的本機 `kernel-local-wifiux2-9g-artifact`；沒有重新啟用已撤銷的 ux=127 掃描實驗。完整值與雜湊見 `comparison.json`。

| 項目 | 舊日常 v7 | 合併 v8 |
| --- | --- | --- |
| 引導 | 一般進 iOS，Recovery 轉 Linux | dualboot／for fuxi 三按鈕；音量選擇、電源直接確認，Recovery 保留繞過選單 |
| 選單預設 | 無選單 | Android，無倒數自動啟動 |
| 無電腦時 iOS 啟動等待 | 5 秒 | 沿用已測候選的 30 秒；不是進度卡住 |
| iOS 核心 | CI `kernel-adsp-rtcadt-ram9g-artifact` | 本機 `kernel-local-wifiux2-9g-artifact`，已在前幾趟使用 |
| RAM／GPU／效能 | 9184 MiB、GPU scratch 0xafe000000、chain-v7 七項調校 | 相同 |
| 電量／亮度／手電筒／狀態欄 | ADSP3、PMIC3、backlight4、sbshape300127 | 保留 |
| Wi-Fi | 日常引導未啟用 | ath12k＋原生 iOS，RSSI_BOUNDS、自動加入、ux=31；慢掃描與速率問題擱置 |
| 充電震動 | 未接入新路徑 | ADSP/SPF、mediaserverd 注入、振幅128、Envelope；交互震動未驗收 |
| 色域 | P3 | sRGB，沿用先前 Safari 測試設定 |
| 開機文字 | sweetfb_noconsole=1 | =2，安靜開機；USB／mtd 紀錄保留 |
| 函式庫注入 | SpringBoard（inject=2） | SpringBoard＋mediaserverd＋wifid（inject=14） |
| 除錯參數 | debug=12；peakpowermanagerd stderr | 移除 debug；wifid stderr 診斷 |
| RTC | offset 1794782948 | 相同，候選使用 02:30 的校時紀錄 |
| iOS root、App、設定 | 手機現有同一份20GiB映像、39 extents | 相同映像；酷安及已裝的 libfuxi-sb.dylib 保留，不覆寫 root |
| Android 核心 | 現行原廠核心 | 內嵌核心 SHA256 相同 |

候選 boot.img：66,326,528 bytes，SHA256 `dc7240d7cfdc37141e0430d742ee83a8cb2a25fed3aa9c65e7e6b5cad792d39e`。舊日常 prefix SHA256 `eb985a344eaa2c57d3ab3005c96f204a5e44fd3df785267eec60875b3bfe3483`，已與02:00前後實機備份比對相符；部署時再次核對手機現況。

主機：最新選單原有380項 ASan／UBSan 斷言、物件重連結／映像核對；本次核對編譯用 C／header 未變、payload／Android 核心原樣保存。新增 launcher 日常部署入口，沿用 `deploy-verified.py` 的寫前核對、寫後讀回、完整 boot_b／KSU 備份及失敗還原；更新後32項恢復測試通過。

本次暫時開機 `daily-v8-ios-validation-20261118`：03:10:44載入，已出現 exec SpringBoard、ux=0x1f、掃描43／50 BSS及 join finished 0。最終回程與部署結果寫在 `deployment.json`。

預定部署只寫 boot_b 與 KSU 模組，保留 boot_a、Recovery及iOS root。此版從 b 槽選 Android、常駐冷啟動、Recovery／其他選項仍需使用者實測；RAM 開機成功不能代替這些驗收。原始還原點：`D:/xiaomi13/fuxi_Backup/dualboot-before-validation-20261118-014941`，部署另存當下 boot_b／KSU 還原點。
