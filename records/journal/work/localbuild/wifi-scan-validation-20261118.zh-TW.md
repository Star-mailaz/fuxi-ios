# Wi-Fi 掃描實驗與回退（2026-11-18）

本輪實驗失敗，使用者要求立即回退；不再測下一個候選。日常 boot_a／boot_b 與 iOS root 未寫入。

## 失敗與限制

`native-hw000wifi-scanscope-boot-1`：01:05:32 暫時開機，新增 ux=127，把未指定頻道限制到 iOS 公布清單，並使用既有模組的 dwell extension 按主動／被動／雷達頻道分組。第一輪 15 頻道分五批，30,001 ms 逾時（error 60），隨後 native worker 退出；使用者回報 Wi-Fi 關不了、掃描沒有結果。這組設定已拒用，不能當成掃描加速。

兩份既有 Wi-Fi ASan／UBSan 主機測試、loader self-test、38 項 workflow 命令及本機核心建置雖通過，未涵蓋本次真實韌體的分批耗時／逾時行為。國家碼只在 iOS 層保存；底層是否使用 world 法規域、舊全頻掃描是否實際包含 6 GHz，仍未證實。

USB console：`work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-scanscope-boot-1/boot.log`，6,692,920 bytes，SHA256 `447410a777ec6d3598d5fa67dc6c38f4915802e9ed7e00c1266020613728eb18`。主機最高 TSENS 61.1°C；01:12:29 launcher 確認 Android boot_completed=1、root unmapped 並釋鎖。下一趟前已保存 mtd：`work/adsp-battery/fuxilog/20261118-011232`。

## 回退方式

- ksrc `a23e701` 由 `490764d` 撤銷，`git diff 497a117 HEAD` 為空，來源樹與接手時一致。
- harness `patches/kernel-adsp-battery.patch` 還原到 `05880e1` 的版本；loader 產生器回到主倉庫 `dbbb912` 的版本。未推送實驗。
- 手機先回 Android；再經同一 launcher 暫時啟動上一趟成功的 `native-v7wifi-1118-0030-ram9g-srgb-loader`，核心 `kernel-local-wifiux2-9g-artifact`、ux=31，boot SHA256 `7a66e622c513473d2426827b95b837943c79dbd229f49676a3c49e0f0d84da27`。沿用原來的 chain-v7、dylib 與使用者資料。
- 01:12:56 已送出舊版暫時開機，趟次 `native-hw000wifi-rollback-boot-1`；900 秒監看、16 分鐘 reset，供使用者檢查。已進 SpringBoard；POWER off 2ms／on 18ms 完成，掃描 7,427ms、39 BSS。首筆 join 在四向握手階段失敗（error 80），不宣稱網路完全恢復，留給使用者檢查。
- 為提早回 Android，短暫在 launcher 增加限定原鎖擁有者／趟次的 reset 路徑，釋放本趟 WinUSB monitor 後呼叫既有 reset-soon.py；此臨時程式也已移除，原先 InspectCrash 等其他人的改動保留。

## 11:16 起續修

- ksrc `a41069f`、harness `522e94b`。`fuxi,wifi-ux` 的 bit 5 讓驅動保留已受理掃描中止／逾時後的電源控制。掃描未回完成事件時，先擋下一筆掃描與加入，等原事件抵達或切換電源更新 generation。沿用既有 ath12k 模組的 SCAN_DONE 與電源確認契約。
- bit 6 參考 UniXNU Ath12kWifi `src/nw_sta.c`，把未帶頻道的掃描交給 iOS 已公布的 2.4／5 GHz 清單。指定的頻道和停留時間照傳，預設停留時間的掃描維持單批。兩個開關預設皆關閉。
- 本機 `kernel-local-wifi-recover-1118-9g-artifact` 建置 101 秒，38 項 workflow 主機命令及 86 項產物雜湊通過。ASan／UBSan 測試包含先後到達的 reply／SCAN_DONE、批次逾時、切換電源時中止、晚到的完成事件與後續重掃。兩個自測 loader 使用同核心、同 RTC 校時與同一份命令列，payload 只差 ADT 的掃描範圍位元。
- `native-hw000wifi-scan-ux63-1118`／`native-scan-ux63-1118-ram9g-loader`，11:16:16 RAM 開機。兩輪關閉／開啟自測通過，各有一次 join finished 0。兩次全頻掃描分別為 15,784 與 15,769 ms（各一批）。USB 紀錄 SHA256 `4b68768dcd506ba2adb71c398ac54716b785d97e6bcbe806b8c00aea3592b673`，最高 TSENS 65.5°C。第二趟 `native-scan-ux127-1118-ram9g-loader` 已打包，待 Android 回程。
- 11:18:29 監看完成。11:26:27 啟動器等不到 Android ADB，自動釋放本趟鎖。常駐雙系統選單需要按鍵確認 Android，目前無畫面證據。第二趟尚未啟動。

## 11:39 的 40 頻道對照

- `native-hw000wifi-scan-ux127-1118` 於 11:39:51 暫時開機。第一輪關閉／開啟成功，隨後使用已公布的 40 頻道單批掃描，耗時 11,295 ms、回傳 27 筆 BSS。對照兩次全頻掃描平均 15,776.5 ms，少 4,481.5 ms（28.4%）。兩趟分別在電池 30.7°C／37.1°C 開始，40 頻道的關開後測量只有一次。
- 第二輪的關閉已在 104 ms 內完成（USB log 第 4718–4721 行）。`wifid` 在自測讀取電源狀態前重新打開 Wi-Fi（第 4851、4926–4928 行），自測因此回 EIO 5 並提前結束（第 5034 行）。本趟兩次在 5200 MHz 加入成功。連線後 `wifid` 的另一筆未指定頻道掃描也走 40 頻道，耗時 5,475 ms，屬已連線條件。
- 前趟持久紀錄 boot #94 已在本次啟動前保存到 `work/adsp-battery/fuxilog/20261118-113927`。本趟 USB console 576,162 bytes，SHA256 `d480190d19ba8be0a39a8280a7e59ea9cb072147b4141ebca4cb9e4d47cb981e`，最高 TSENS 79.3°C。下載吞吐與長時連線仍待實測。
- 11:45:10 啟動器確認 Android `sys.boot_completed=1` 並釋鎖。兩趟均用 RAM 暫時開機。
