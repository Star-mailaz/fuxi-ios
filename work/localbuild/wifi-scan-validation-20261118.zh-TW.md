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
