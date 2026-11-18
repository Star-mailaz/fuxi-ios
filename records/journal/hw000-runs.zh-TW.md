# 000 線趟次

每趟記時間、loader、唯一變更、結果與原始證據目錄。完整建置與復現指令在對應條目。11 月 18 日以前的試驗與當天較早的詳細時間線見日誌索引。 [原始紀錄與附件](README.zh-TW.md)

| 時間（台北） | 項目 | Loader／映像 | 變更 | 結果 | 原始紀錄 |
| --- | --- | --- | --- | --- | --- |
| 2026-11-18 12:26–12:32 | K-073 | native-wifi-power-ux1023-1118-1225-loader | 關閉優先＋接收批次 | 關閉 67–71 ms，重連曾暫停接收，恢復後使用者確認約 220 Mbps | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-power-ux1023-1118-1225/ |
| 2026-11-18 12:32–12:39 | K-073 | native-wifi-power-ux767-1118-1225-loader | 同核心停用接收批次 | 首次關閉 65 ms，第一次重連四個取樣區間無接收，使用者回報約 100 Mbps | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-power-ux767-1118-1225/ |
| 2026-11-18 12:53–12:59 | K-074 | native-wifi-peer-zero-1118-1252-loader | 換修正 peer ID 0 的 ath12k 物件 | 首次重連即收到資料，峰值五秒平均 228.45 Mbps，安全回 Android | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-peer-zero-1118-1252/ |
| 2026-11-18 13:13–13:19 | K-075 | native-wifi-scan-trace-1118-loader | 增加掃描與韌體事件的量測 | 首輪三頻道 7,395 ms，設定頁掃描完成 9,380 ms | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-scan-trace-1118/ |
| 2026-11-18 13:27–13:33 | K-075 | native-wifi-scan-priority-1118-loader | WMI 送出選定的掃描優先級 | 首輪三趟 408–414 ms，設定頁掃描完成 1,629–1,723 ms，三趟首次加入皆有接收 | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-scan-priority-1118/ |
| 2026-11-18 13:38–13:44 | U-018 | Wi-Fi 密碼頁取樣版 | 取樣設定頁主執行緒 | 8,926／30,000 筆在密碼分享服務等待，輸入後一筆加入為 217 ms | work/localbuild/wifi-password-profile-1118-symbols/guest.log |
| 2026-11-18 13:52–13:56 | B-011 | menu-android-countdown-current-20261118 | 顯示 10 秒倒數，逾時進 Android | RAM 試開、a 槽寫入讀回、Android 自動交接皆通過 | work/dualboot/countdown-ram-validation-20261118/、work/dualboot/persistent-slot-a-upgrade-countdown-20261118/ |
| 2026-11-18 14:06–14:13 | U-018 | native-wifi-password-prompt-1118-loader | 讓 Settings 直接走手動密碼框 | 使用者確認卡頓消失，5200／5745 MHz 加入成功，回 Android | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-password-prompt-1118/ |
| 2026-11-18 14:32–14:39 | U-019、G-049 | native-wifi-hotspot-refresh-1118-loader | 背景 RSSI 更新時補查目前網路 | 第二次切熱點顯示鏈結圖示。之後捕捉一次 Metal DeviceLost 與桌面重啟，回 Android | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-hotspot-refresh-1118/、work/adsp-battery/fuxilog/20261118-144054/ |
| 2026-11-18 14:53–15:02 | U-019、G-049 | native-wifi-hotspot-refresh-control-1118-loader | 保留狀態觀測，停用關聯補查 | 第二次接入 5745 MHz 時收到 −48 dBm，SpringBoard 由 3 格降到 0 格，使用者也看到 0 格。無 DeviceLost，已回 Android | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-gpu-control-1118/、work/adsp-battery/fuxilog/20261118-150313/ |
| 2026-11-18 15:03–15:12 | G-049 | native-wifi-hotspot-refresh-repeat-1118-loader | 恢復關聯補查，同樣錄 390 秒 | 初始家庭網路補查成功，沒有再切熱點。USB 紀錄未見 DeviceLost，已回 Android | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-gpu-repeat-1118/ |
| 2026-11-18 15:24–15:27 | U-001 | native-dualboot-sb103-1118-loader | 將狀態欄中心上移 24 px | 時間與圖示中心為 63.5 px，使用者確認實體鏡頭對齊 | work/Codex-Xiaomi13-GPU-20261109/native-hw000sb103-camera-1118/ |
| 2026-11-18 15:34–15:39 | B-012 | native-daily-wifi-sb103-1118-loader | 合併已對齊的高度與 Wi-Fi 修正 | 5200／5745 MHz 加入，載入手動密碼框及熱點補查，使用者確認正常 | work/Codex-Xiaomi13-GPU-20261109/native-hw000wifi-sb103-daily-1118/ |
| 2026-11-18 15:39–15:42 | B-012 | menu-daily-wifi-sb103-20261118 | 將驗證過的 iOS payload 放入日常 10 秒選單 | RAM 試開、a 槽整區讀回與 Android 自動交接通過 | work/dualboot/daily-wifi-sb103-ram-android-20261118/、work/dualboot/persistent-slot-a-upgrade-wifi-sb103-20261118/ |
