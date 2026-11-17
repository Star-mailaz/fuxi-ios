# 來源與目錄說明（2026-11-18）

本倉庫由私人開發工作區匯出，收錄核心、loader、引導鏈、userland 與工具的原始碼。三個上游樹已收進倉庫，本機建置不必再向上游下載。各上游的釘選版本、tree id、本機修改清單與去識別化紀錄都在 [`upstream/EXPORT-SOURCES.txt`](../upstream/EXPORT-SOURCES.txt)。

## 上游樹

| 路徑 | 上游 | 釘選 commit | 上游 tree |
| --- | --- | --- | --- |
| `work/adsp-battery/ksrc/` | zgl97/ios-fuxi | `979e2f08c704677bb75934ae96d4686ba9d1692b` | `73399c0c833e17e8a3f86f921e9f473a76cd7999` |
| `ios-fuxi/` | bangprovn/ios-fuxi | `27f6a31c8b27c6f9127f9cf27092968422579ccf` | `c05b0ff0d5b4d9747ef1b9e4cc9f2a0eda963d98` |
| `uefi-fuxi/Resources/Scripts/mkbootimg.py` | ljhhkx529/uefi-fuxi（AOSP 原檔） | `57969ab77d36a982261daef16592741ed4a1d811` | 只收這一個檔案，未修改 |

每個上游樹先用一個提交原樣放進來，再用後續提交加上本機修改，所以 `git log -- ios-fuxi/` 或 `git diff <匯入提交> -- ios-fuxi/` 可以看出本機改了什麼。ios-fuxi 的本機修改有 14 個檔案（loader、GPU probe、monitor 與 ADT 產生器）；ksrc 相對基底改了 209 個檔案。

## 核心怎麼建

核心不是直接從 `ksrc/` 編，而是「基底＋補丁」：

1. `work/localbuild/fuxi-kernel-build.sh` 讀 `upstream/EXPORT-SOURCES.txt` 的 `kernel-base` 列，從本倉庫歷史取出 tree `73399c0c…`（zgl97/ios-fuxi `979e2f08` 的原樣內容）。
2. 依 `.github/workflows/kernel-adsp-battery.yml` 的清單與順序，把 `patches/` 裡的 18 份補丁套上去；`-Tests` 時照 workflow 的順序穿插主機測試。
3. 用 Darwin 交叉工具鏈編出 `kernel.development.fuxi`、`fuxi.adt` 等產物。

`ksrc/` 是編輯用的樹。基底套完 18 份補丁後，只有 `tools/sync-abi-backend.py` 和 `ksrc/` 不同（不在 `xnu/`、`xnu27/`、`shim/` 底下），其他檔案一致。

改了 `ksrc/` 的驅動原始碼後：

- 用 `ksrc/tools/sync-fuxi-*.py` 把改動同步進 `ksrc/xnu/patches/` 的補丁。要在 WSL 執行，Windows 的 Python 會把補丁寫成 CRLF。
- `patches/kernel-adsp-battery.patch` 在工作區是拿 ksrc 自己的 git 歷史 diff 出來的。本倉庫沒有收那段歷史，所以還沒有現成的重產腳本。

`build-kernel.ps1`、`build-sb-shape.ps1` 的 `-Harness` 預設：工作區有 `work\adsp-battery\harness` 就用它，否則用本倉庫根目錄。從本倉庫執行時不必給 `-Harness`。

## 本機建置需要的外部環境

| 項目 | 說明 |
| --- | --- |
| WSL | 發行版名稱 `Ubuntu-26.04`；建置樹在 WSL 內的 `/root/fuxi-build`（ext4），不要放在 `/mnt/d`，會慢很多 |
| 交叉工具鏈 | UniXNU 的 Linux 工具鏈，裝在 `/opt/unixnu-linux`（可用 `UNIXNU_TOOLCHAIN` 改）。安裝腳本 `setup-unixnu-toolchain.sh` 不在本倉庫 |
| iOS SDK | 建 `libfuxi-sb.dylib` 用 `/opt/unixnu-linux/sdks/iPhoneOS16.5.sdk`，來源 Theos `sdks` release `master-146e41f`，封存 SHA256 `5e0fd3f01266cce4ce012d4a99b38eb56578fca40d09edc81cd83dee958202fb`。SDK 不收進本倉庫 |
| Linker | userland 用 `/usr/bin/ld64.lld-21`（LLVM 21）；核心工具鏈的 ld64 讀不了 SDK 的 `.tbd` |
| ath12k 物件 | `-Ath12k` 用的是 CI 在 macOS 上編的 `fuxi-ath12k-objects` artifact，不收進本倉庫 |

本機產物和 CI 產物不會逐位元相同：本機用上游 clang，CI 用 Apple clang，本機也沒有 CTF 和 dSYM。

## 已知限制

- **絕對路徑**：部分腳本仍寫死 `D:\xiaomi13\fuxi_ios`（WSL 內為 `/mnt/d/xiaomi13/fuxi_ios`），包括建置產物的輸出目錄 `work\Codex-Xiaomi13-GPU-20261109\<Name>`。在 WSL 直接執行 `fuxi-kernel-build.sh` 時可用 `OUT_ROOT` 改輸出位置；`build-kernel.ps1` 不會轉傳這個變數，`fuxi-sb-build.sh`、loader 產生器與手機工具也還沒有對應開關。目前最省事的做法是把倉庫放在 `D:\xiaomi13\fuxi_ios`。
- **手機序號**：手機工具從環境變數 `FUXI_ANDROID_SERIAL` 讀 adb 序號（`adb devices` 顯示的值）。沒設時，`launch-loader-check.ps1` 會直接停下；Python 工具的 adb／fastboot 指令會找不到裝置而失敗。
- **Android NDK**：引導鏈與 loader 產生器從 `%LOCALAPPDATA%\Android\Sdk\ndk\26.1.10909125\toolchains\llvm\prebuilt\windows-x86_64\bin` 找 NDK r26b 的工具。
- **QEMU**：`work/statusbar-fix/` 的 iOS 根映像整備與 `test-root-layers.py` 需要 Windows 版 QEMU，工作區放在 `candidates/vm-tools/qemu`，不收進本倉庫。
- **舊版核心原始碼**：`verify-loader-safety.py`、`verify-args-on-loader-payload.py`、`work/ksu-ios-entry/build-module.py` 會讀工作區的 `kernel-source-979`。這是舊流程，本倉庫沒有收這個目錄。
- **預建 Android 工具**：`work/ksu-ios-entry/fuxi_ios_boot/bin/` 的 `check-pin`、`inspect-fiemap` 用 NDK r26b 建置。`check-pin` 的原始碼是 `work/xiaomi13-ios-gpu-20261108/check-pin-readonly.c`；`inspect-fiemap` 的原始碼不在本倉庫。

## 不收的內容

Apple IPSW、DMG、RootFS 與其他專有系統二進位；高通韌體、DTB 與從手機抽出的資產；iOS SDK；個人手機備份、分區映像、金鑰與 Wi-Fi 憑證；執行紀錄、console／mtd 紀錄與量測 JSON；雙系統選單使用的 Noto Sans TC 字型檔（只收 OFL 授權文字，字型請依 `dualboot/THIRD_PARTY.md` 的來源與 SHA256 自行下載）。

<a id="ci"></a>

## CI

`.github/workflows/` 是從開發用的 harness 倉庫原樣複製來的，觸發條件沒改：

- 都是 `workflow_dispatch`（手動執行），部分另外在推送到 `codex/adsp-battery`、`codex/backlight-dsi`、`codex/kernel-bo-slots` 分支時觸發。
- 沒有任何 workflow 在推送到 `main` 或開 pull request 時執行。
- workflow 仍然從 zgl97/ios-fuxi 的釘選 commit 抓核心原始碼，不讀本倉庫收錄的樹。
- 平常的 CI 仍在原本的 harness 倉庫執行。要在本倉庫跑，需在 Actions 頁面手動觸發。

## 匯出流程

本倉庫的程式碼由工作區的匯出腳本產生：

- 只讀工作區**已提交**的內容，未提交的修改不會進來。
- 把 adb 序號、Wi-Fi 名稱、使用者目錄與區網 IP 換掉，紀錄在 `upstream/EXPORT-SOURCES.txt` 的「去識別化」段。
- 工作區的 `.json`、`.log`、`.txt` 預設不匯出；少數腳本必讀的參考檔與授權文字例外。
- 匯出後掃描整個倉庫的二進位檔、過大檔案與敏感字串。找到任何一項就以錯誤結束，不提交。

`README.md`、`THIRD_PARTY.md` 與 `docs/` 是手寫的，不由匯出腳本管理。
