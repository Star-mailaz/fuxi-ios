# 本機核心開發流程驗證（2026-11-16）

已完成主機端驗證：5g／9g 編譯、workflow 測試順序、增量建置、同版 CI 輸入與產物結構比對、離線 loader 封裝。2026-11-17 已完成普通9g本機核心首次上機；5g與ath12k配置仍須分別驗證。

## 實測

Windows／WSL Ubuntu-26.04；32 jobs，WSL 約 15.6 GiB RAM。完整重編使用 `-Clean`；來源與工具鏈已在本機快取，不含首次下載、工具鏈安裝或實機時間。

| 測試 | 全流程 | 核心 make | 結果 |
|---|---:|---:|---|
| 5g `full` 完整重編 | 70 秒 | 39 秒 | 成功 |
| 9g 完整重編 | 70 秒 | 38 秒 | 成功 |
| 9g 無修改增量，Windows PowerShell 5.1 啟動 | 21 秒 | 2 秒 | 成功；stripped／unstripped 核心均與完整重編逐位元相同 |
| workflow 主機測試＋9g 完整重編（修正 IIG 後處理前的同份補丁） | 96 秒 | 40 秒 | 33 個命令全通過，含 ASan／UBSan 測試 |

時間來源：兩個保留 artifact 的 `BUILD.txt`、本目錄 `timing-incremental-9g.txt`、`timing-clean-9g-with-tests.txt`。較早 17 秒樣本尚未加入完整 IIG 後處理，最終增量數字採 21 秒。

## 修正的流程問題

- compiler-rt profiling library 補上 XNU EXTERNAL_HEADERS；只在該 library 處理舊 Availability.h 缺少的 SPI 註記。
- 上游 clang 在既有 idle 程式產生 `__udivti3` 呼叫；從已釘選 LLVM compiler-rt 加入 `udivti3`／`udivmodti4`，以 freestanding 標頭編譯並連結，沒有修改驅動行為。
- `-Tests` 改成按 workflow 原順序穿插補丁與測試，避免舊階段測試被後續補丁改變；使用 Ubuntu clang，補裝 `libclang-rt-21-dev`，保留 sanitizer。
- IIG replay 提前至 `installhdrs`，清掉先前使用另一版 IIG 的標頭建置快取；最終準備、驗證 17 組 header／implementation 及 manifest，與固定快取一致。
- Windows 啟動器用 WSL `--exec` 與每次獨立腳本副本，避免 shell 提前展開變數或覆寫執行中的腳本。
- 同 RAM 配置加互斥鎖；任何準備失敗都撤銷舊成功標記與 checksum manifest；ISA 檢查必須確實解出指令，不能空跑或略過。
- 錯誤摘要只擷取編譯／linker 診斷，避免被原始程式字串裡的 `error:` 擠滿。

## CI 對照與產物

來源：ios-fuxi `979e2f08c704677bb75934ae96d4686ba9d1692b`＋harness `c0d0d2dccb1b01515d43d044d0d698ce841802c4` 的 18 份補丁；逐份重新以 `git show` 驗證與本機 INPUTS 一致。

對照 [9g CI 43896202141](https://github.com/scyx2611/fuxi-metal-frontend-check-20261108/actions/runs/43896202141) 成功，整個 CI job 16 分 36 秒。下載 ZIP 的 GitHub artifact digest 及解壓後 40 項 SHA256SUMS 均通過。

- 命令列與 35 份 IIG 檔案逐位元相同。
- ADT 逐屬性比對只差 `/chosen/random-seed`（各自生成的 64 bytes）；其餘屬性相同。
- 本機及 CI 都是 plain arm64 Mach-O executable，入口位於 `__TEXT_EXEC`；本機 ISA 檢查解出 2,270,074 條指令，禁止指令 0。
- 本機使用上游 clang、沒有 CTF／dSYM，核心二進位與 Apple clang CI 不同。這些比對不能取代實際開機。

以下資料夾均在 `work\Codex-Xiaomi13-GPU-20261109\`：

| 產物 | 核心 SHA-256 |
|---|---|
| `kernel-local-validated-full-artifact` | `717a5eda902b106cea27f4f0df540687290f1054898a65895d533509c846076e` |
| `kernel-local-validated-9g-artifact` | `f30bc339cdfef7ca6984d515995c4395905240b2202eedc93664ebd9e59dc31c` |
| `kernel-ci-reference-43896202141-9g-artifact` | `adb0351217f860c8da139cf74ab49a4254f3b777e4f94838602d189923cf61dc` |

機器可讀證據在 `artifact-verification.json`；本機 full／9g manifest 分別驗證 48／81 個檔案（9g 包含主機測試紀錄）。

`native-localbuild-9g-validation-loader` 已由現有 `prepare-ram9g-loader.py` 離線封裝成功：沿用既有 loader 的 root mapping、12GB SKU、9g usable、GPU scratch `0xafe000000`，移除 tour／tap。boot.img SHA-256 `ff739aa45a7169614a238332e4ab2fd1287d7f8584bb869375237cc4e150b89c`。沒有做即時手機 mapping 檢查或開機；下次使用仍須經 `launch-loader-check.ps1` 重新驗證手機現況。

## 邊界

2026-11-17 00:03:58–00:08:50，以 `native-local-torchlevels-sb127-user-loader` 暫時開機、`launch-loader-check.ps1 -Seconds 180 -Reset 4` 完成回Android與釋鎖。本機核心SHA-256為上表 `f30bc339…dc31c`，同補丁CI核心 `adb03512…61dc` 已在前一趟 `native-hw000torchdim-user-boot-1` 成功開機。本趟進入SpringBoard、GPU工作、ADSP電量發佈；手電筒修正版dylib收到113次level transition，涵蓋0／1／2／3／4，使用者回報「手電筒可以了 沒問題」。USB console 13862行、SHA-256 `9ae6203132a02b26e9699214ef05309f827add0a5ccb93200937ac46ffb91ebb`，主機TSENS最高63.1°C。紀錄在 `work/Codex-Xiaomi13-GPU-20261109/native-hw000local-torchlevels-user-boot-1/`；未改日常boot_b。含dylib小差分stage的整條流程00:01:34–00:08:50，共7分16秒；純暫時開機及回程4分52秒。這是一趟普通9g開機驗證，不是所有外設或長期穩定性驗收。

已實測：同配置鎖拒絕、Windows PowerShell 5.1 參數及錯誤碼、準備失敗撤銷舊成功標記。原本中斷、重複與防護測試用的 7 個 artifact 及下載 ZIP 移到 `E:\wsl\fuxi-localbuild-validation-20261116\` 保存；D: 保留上述兩顆本機核心、CI 對照及離線 loader。

2026-11-17亦測通 `-Ath12k`：原先本機14.0建置標記與固定模組15.5不符，post-link gate正確拒絕；改從模組gate的 `KERNEL_TARGET` 讀取target／SDK版本，不略過檢查。Linux改用 `llvm-nm`，修正Darwin BSD nm不接受 `--defined-only`；重建前撤銷舊ath12k-link紀錄。本機 `kernel-local-wlancontrol-9g-artifact` 最終增量23秒（make3秒），47項manifest與13個entry通過。核心 `9f5c49ee4b55d946e3652450848d90330f951a2013e7d419f54db2fda154aa53` 在 `native-hw000ath12k-control-boot-1` 於00:26:28–00:30:18開機並回Android，完成PCI辨識、韌體下載及AMSS/M0，原start -16已消失；接著因DMA釋放契約缺接而鎖停。這證明本機連結與初始化可執行，**沒有通過Wi-Fi掃描**；同補丁正式CI `43907693114`仍在進行。普通本機14.0配置先前已上機；ath12k的15.5是既有核心／模組建置profile，不改iOS16執行環境。

2026-11-17 00:34:12–00:37:02，`kernel-local-wlandma-9g-artifact`（核心SHA-256 `2daafc813badcb8d1052eb8f030ac9ee26f9dc72a9815fc5b14e1ed64e99e03c`）於`native-hw000ath12k-dma-boot-1`通過真實radio scan：34個BSS、2.4／5GHz、start error0／DMA error0／faults0。90秒監看、2分鐘reset，Android boot_completed=1並釋鎖；USB console3710行、SHA-256 `1dfbda7652bd223dc058e8b605d7468a2e76f4eceea8db27a051d8fb09e6e78a`，主機TSENS最高61.1°C。收尾bus master off／PERST asserted，MHI reset仍unconfirmed；沒有設定頁、association／DHCP／traffic證據。

接續native iOS bridge候選 `kernel-local-wlanios-9g-artifact`（ksrc4b52021／harness1d53fc3）：27秒（make6秒）、47項manifest、14個entry通過，核心SHA-256 `95cd3d93796322064cbda1230dbad00a2aec3159af3b3a9aa6d1c4108a5024c9`。新ASan／UBSan測試直接執行production bridge，包含電源applied event、重複generation、64頻率directed scan、reply／event反序、stale拒絕及逾時；既有iOS station／WPA／ifnet／mounted-root fixture及原模組ABI／codec回歸通過。496-byte loader包含native mode2與station selftest，沿用39 extents、12GB SKU、既有statusbar及GPU設定；新增wlan DT以觸發wifid既有gate，沒有修改root plist。01:03:11實機測試兩輪power off／on result0、station scan BSS30並回Android；正式CI `43914132655`成功。

加入流程候選 `kernel-local-wifijoin-9g-artifact`（ksrc d020ece，33項主機測試通過）於`native-hw000wlan-join-boot-1`（02:02:52–02:05:22）以假密碼完成auth／assoc／EAPOL M1回覆，AP拒絕金鑰（EAUTH，符合預期），scan BSS36、家用網路2.4／5.2GHz皆在。同日 `kernel-local-rtcadt-9g-artifact`（ksrc 406f096，ADT `fuxi,rtc-offset`備援）60秒、`kernel-local-wifirtc-9g-artifact`（同源＋ath12k）62秒建置成功；`build-kernel.ps1`改為只看wsl結束碼，轉向stderr（`*>`）時不再因「Failed to mount T:」警告而在建置前中止。

2026-11-17 06:50 起已有真密碼連線／DHCP 實機證據：`native-hw000wlan-uijoin2-boot-1` 對家用 AP 完成 WPA2 四向握手，configd 為 en0 配置區網位址；07:20、07:38 再成功。這是較舊「仍未驗真密碼」紀錄的更新；5GHz 加入、上網、跨重啟自動加入及5g本機核心實際開機仍未驗證。手機鎖、寫前比對／寫後讀回及首次CI對照規則均沿用AGENTS.md。
