# 第三方元件與授權

## 本專案的授權

- 本專案自己撰寫的程式碼、腳本、測試與文件以 [MIT](LICENSE) 授權。
- 對 Apple XNU 原始檔的修改（核心補丁中改動 Apple 檔案的部分）依 APSL 2.0。
- 收錄或改編的第三方程式碼維持原本的授權。原有的 LICENSE、NOTICE 與檔頭都保留，MIT 不取代這些條款。

## 收錄的上游原始碼樹

| 路徑 | 上游與版本 | 授權 |
| --- | --- | --- |
| `work/adsp-battery/ksrc/` | [zgl97/ios-fuxi](https://github.com/zgl97/ios-fuxi) `979e2f08c704677bb75934ae96d4686ba9d1692b`（fork 自 bangprovn/ios-fuxi） | **上游沒有宣告授權** |
| `ios-fuxi/` | [bangprovn/ios-fuxi](https://github.com/bangprovn/ios-fuxi) `27f6a31c8b27c6f9127f9cf27092968422579ccf` | **上游沒有宣告授權** |
| `uefi-fuxi/Resources/Scripts/mkbootimg.py` | AOSP `mkbootimg.py`，取自 ljhhkx529/uefi-fuxi `57969ab77d36a982261daef16592741ed4a1d811` | Apache-2.0，原檔頭保留、未修改 |

兩份 ios-fuxi 上游沒有附授權檔，其作者保有原有權利。本倉庫收錄它們是為了讓建置可重現，並清楚標示來源；MIT 只涵蓋本專案新增的部分，不及於上游原有程式碼。權利人如要求移除，請在本倉庫開 issue，會照辦。

ios-fuxi fork 自 [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)（MIT）。

## 上游樹內的元件授權

兩棵樹內帶著相同的元件授權檔（`ksrc/` 另多一份 `xnu/fuxi-adsp/LICENSE.UniXNU-sheng`）。各元件改編了什麼、取自哪個 commit，詳見 `ios-fuxi/README.md` 的 Credits 一節與 `ios-fuxi/xnu27/NOTICE`。

| 檔案（相對於 `ios-fuxi/` 或 `work/adsp-battery/ksrc/`） | 授權 | 來源 |
| --- | --- | --- |
| `shim/fuxi-probe/LICENSE.AdrenoFirmware` | BSD-2-Clause-Patent | ArmVirtPlatform contributors（AdrenoFirmware） |
| `tools/fuxi-metal/LICENSE.NativeMetal` | MIT | NativeMetal contributors |
| `tools/fuxi-thermald/LICENSE.HackiOS` | MIT | OOSEX GANG（hackios-xnu-userland） |
| `tools/xnuprelink/LICENSE` | BSD-2-Clause-Patent | UniXNU contributors（XnuPrelink） |
| `xnu/fuxi-adreno/LICENSE.ArmCpu` | BSD-2-Clause-Patent | ArmCpu contributors |
| `xnu/fuxi-adreno/LICENSE.GopFramebuffer` | BSD-2-Clause-Patent | ArmVirtPlatform contributors |
| `xnu/fuxi-adreno/LICENSE.NativeAdreno` | MIT | NativeAdreno contributors |
| `xnu/fuxi-adreno/LICENSE.NativeMetal` | MIT | NativeMetal contributors |
| `xnu/fuxi-adreno/LICENSE.ShengUfs` | BSD-2-Clause | blu-sharky |
| `xnu/fuxi-adreno/LICENSE.UniXNU-sheng` | BSD-2-Clause-Patent | UniXNU contributors |
| `xnu/fuxi-adsp/LICENSE.UniXNU-sheng`（僅 `ksrc/`） | BSD-2-Clause-Patent | UniXNU contributors |
| `xnu/fuxi-h1/LICENSE.NativeHidInput` | BSD-2-Clause-Patent | NativeHidInput contributors |
| `xnu/fuxi-unixnu/LICENSE.NativeMobileDisplay` | BSD-2-Clause-Patent | ArmVirtPlatform contributors |
| `xnu/fuxi-unixnu/LICENSE.NativeUfs` | BSD-2-Clause | blu-sharky |
| `xnu/fuxi-unixnu/LICENSE.UniXNU` | BSD-2-Clause-Patent | UniXNU contributors |
| `xnu/fuxi-wifi-ios/LICENSE.HackiOS` | APSL 2.0 | OOSEX GANG（hackios-xnu-kernel） |
| `xnu27/NOTICE`、`xnu27/components/{ArmCpu,ArmDTPlatform}/LICENSE` | BSD-2-Clause-Patent；補丁套用的 Apple xnu-12377.121.6 為 APSL 2.0 | UniXNU、UniXNU-sheng、UniXNU-sm8550-common、ArmCpu、ArmDTPlatform |

檔頭帶 GPL 標記的檔案：

- `shim/fuxi-probe/gpu-a740.h`，以及 `xnu/patches/0096-fuxi-adreno.patch` 新增的同名標頭：`GPL-2.0-only`。內容是取自 Linux msm `a6xx_catalog.c`／`a6xx.xml` 的 A740 暫存器值。
- `xnu27/patches/fuxi/0008-dada-apfs.patch` 新增的檔案：`GPL-2.0+ OR MIT`，此處依 MIT 使用。

## `patches/` 中修改外部專案的補丁

這些補丁改的是外部專案的檔案，補丁內容依該專案的授權：

- `metal2vulkan-fuxi-*.patch`：[steelbrain/metal2vulkan](https://github.com/steelbrain/metal2vulkan)，GPL-2.0-or-later OR LGPL-3.0-or-later。
- `nativemetal-fuxi-*.patch`：NativeMetal，MIT。

其餘補丁修改的是 `ios-fuxi/` 樹或本專案自己的檔案。

## 其他

- `dualboot/`：選單、繪圖與板級轉接程式碼為 MIT；參考與改編來源見 [`dualboot/THIRD_PARTY.md`](dualboot/THIRD_PARTY.md)。選單字型取自 Noto Sans TC（SIL Open Font License 1.1，授權全文在 `dualboot/licenses/NotoSansTC-OFL.txt`）；字型檔本身不收進本倉庫。
- `work/ksu-ios-entry/fuxi_ios_boot/bin/check-pin`、`inspect-fiemap`：本專案用 Android NDK r26b 建置的 Android 工具。`check-pin` 的原始碼是 `work/xiaomi13-ios-gpu-20261108/check-pin-readonly.c`；`inspect-fiemap` 的原始碼不在本倉庫。
- 建置或執行時需要、但**不收進本倉庫**的外部元件：Apple XNU 與 iOS userland（IPSW、RootFS 等 Apple 專有檔案）、iOS SDK、高通韌體、Mesa Turnip、metal2vulkan、UniXNU Linux 工具鏈、QEMU。`tools/build-ath12k-objects.sh` 在建置時才從 UniXNU 的 Ath12kWifi、UniXNU-sheng、UniXNU 倉庫抓釘選版本。這些元件請依各自的授權自行取得。
- 上面的 GPL 清單是依檔頭 SPDX 標記整理的。若發現沒有標示來源的改編內容，請開 issue。
