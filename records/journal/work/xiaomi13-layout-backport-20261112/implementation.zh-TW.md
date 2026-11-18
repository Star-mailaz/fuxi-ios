**小米 13 ASTC layout 最小回移植，2026-11-12**

候選分支：[codex/astc-layout-backport](https://github.com/scyx2611/fuxi-metal-frontend-check-20261108/tree/codex/astc-layout-backport)。原有 CI harness 的 main 與手機映像均未改動。

程式碼以 NativeMetal `a96feceda55e8fed1e20c0a2998736cef7aab006` 及既有 Fuxi 0001–0010 補丁為基礎。新增 0011，回移植上游 layout producer／普通 texture upload 的配對思路，保留既有 ABI、copy-span 與故障回退機制。

本候選支援 ASTC 4×4 LDR／sRGB、2D／array／cube、mip chain，以及 ShaderRead 消費端。它採用普通 texture upload 的快照語義；實機框架是否要求來源後續寫入可見，仍需驗證。3D、其他壓縮格式及 heap/buffer-backed layout 查詢目前維持拒絕。

資料的進入條件如下：

1. `initializeTextureMemory:` 登記 layout、format、尺寸與配置範圍，建立新的寫入代次。
2. `copyFromLinearBytes:...` 先計算完整、已檢查邊界的 copy plan，再複製並記錄各 ASTC block 的覆蓋情形；重寫同一個 block 不增加覆蓋數。
3. 匯入入口只接受同一 allocation、相符 descriptor、所有 block 都已寫入及足夠 length 的來源。來源不明的記憶體仍走既有診斷與拒絕路徑。
4. 在來源追蹤鎖內，以有界的 self-memory read 建立暫存快照，檢查每個 mip／slice 的 bridge 上傳結果後才回傳 texture。
5. `finalizeTextureMemory:` 取消來源登記；有 deallocator 的 texture 透過 owner 物件保留回呼，釋放時取消登記並執行一次回呼。

watermark 使用 `Fuxi ASTC pair 1`。這與 Apple／上游 DVM 的身分不同，讓框架有機會重建舊快取。沒有通過本 producer 的已序列化資料不會因 length 相符而獲准匯入；實際快取重建路徑仍需實機觀察。

成功事件使用普通 NSLog，避開 Fuxi 的 `NBLOG → noteProblem → fuxiFailure` 故障路徑。真正的拒絕仍保留 fault 與 CPU fallback。`FUXI_NATIVE_LINEAR_LAYOUT=0` 可停用兩個新入口。

本機 Windows MSVC AddressSanitizer 已通過九組 portable layout 測試。Linux AddressSanitizer／UBSan、既有 metadata 控制，以及完整前端的 macOS／iOS 16 syntax checks 亦已通過。iOS 完整編譯／封裝已通過（43056837931），下載 ZIP 與 GitHub digest 相符，19 個 manifest 檔案及三份關鍵 source byte-for-byte 相符。完整 ARM64 主機整合測試 43060844001 已通過：新 layout producer／importer 的完整覆蓋、快照、停用、失敗與 owner 生命週期、既有前端／gate／completion 測試，以及兩項 ffi_span_tests 全數成功。

前端整合測試使用實際 patched frontend 的 producer、來源登記及匯入流程；以 byte oracle 替代 texture 配置與 GPU 上傳，覆蓋實際尺寸、部分邊界 block、padding、mip／slice、未知來源、長度不足、不可讀頁、上傳失敗、rollback 與 owner 釋放。這些結果不等於實機 GPU 像素或桌面驗收。

後續實機驗收需取得 `FUXI LINEAR: initialize / producer complete / imported`，並確認持續 GPU frames、refusal 與 CPU respawn、像素、實體螢幕及觸控。若失敗資料來自未經 producer 的 cache decode，候選仍會拒絕，需再處理該動態來源。

本次 portable arithmetic 與測試由 Magpie 的 `antigravity/gemini-3.8-flash` 產生，主代理核對、補上最後讀取範圍檢查並執行測試。整合審查兩次請求（第二次縮小範圍）均逾時，未取得審查結果；主代理自行核對整合並負責 CI 驗收。

目前 ADB device list 為空；本輪未做實機啟動或映像寫入。

Intel 完整主機 run 43056830679 在原有 CensusTests.mm 的大型結構回傳轉送中 SIGILL。獨立 diagnostic run 43061440186 在未套用新 layout 的原始 4b8fade fixture 重現 exit 132；CoreFoundation 報告 object/selector 不符並觸發 ud2。現有 makeDeviceClass 使用單一 _objc_msgForward，對 x86_64 的間接結構回傳入口不適用。這是原有 ARM64 fixture 的執行限制。正式 host workflow 已固定 ARM64，iOS cross-build 與 syntax checks 仍可使用 Intel。臨時 diagnostic job 已移除，完整紀錄保留於 ci-intel-census-isolation.log。

目前 branch HEAD bec762e；其 patches/ 與 tests/ 和已產生 iOS artifact 的 9801b2d 完全相同，差異是 host runner 的 ARM64 限制。下載產物在 ios-artifact/，原始 ZIP 為 paired-layout-ios-artifact.zip；詳細雜湊見 artifact-verification.json。

ARM64 host run 在 2026-11-12 00:58 台北時間完成；真實新前端測試的 PASS 可在 ci-43060844001-arm64-host.log 搜尋。手機仍未連線，未做實機啟動。
