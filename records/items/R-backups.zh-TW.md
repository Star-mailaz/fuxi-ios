# R 系列：備份與還原點

> `D:\xiaomi13\fuxi_Backup\`（索引 `README.md`）與 `E:\fuxi_Backup-archive\` 裡的每一份備份一項：內容物與大小、完整還原步驟、雜湊與比對結果、現在放在哪裡。早期盤點（D-049～061）記過的備份，把當時另記的做法、雜湊與出處附在對應項目裡（標「早期盤點另記」）。

> 還原前先照該項「復現」核對雜湊；寫入手機分區一律經 `launch-loader-check.ps1` 或 `dualboot/` 的工具，寫前比對、寫後讀回。

### R-001 android-partitions-20261107

- **日期**：2026-11-07（2026-11-14 搬移至 `D:\xiaomi13\fuxi_Backup\`）
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\android-partitions-20261107\`）
- **開關**：無
- **問題／現象**：上機修改手機 Android 分區或寫入 b 槽開機分流器前，需要一份完整的原始分區還原點。
- **根因**：無（預防性備份）。
- **做法**：保存 21 個分區映像與 1 份雜湊清單（`README.md` 寫共 23 個、實測 `checksums.sha256` 列 21 個 `.img`）：`boot_a/b.img`、`init_boot_a/b.img`、`vendor_boot_a/b.img`、`dtbo_a/b.img`、`recovery_a/b.img`（TWRP）、`modem_a/b.img`、`dsp_a/b.img`、`bluetooth_a/b.img`、`persist.img`、`modemst1.img`、`modemst2.img`、`fsg.img`、`fsc.img`（未附單檔位元組大小於文字檔）。
  - 早期盤點（原 D-049「備份 `android-partitions-20261107\`（手機分區原始映像）」）另記的做法：
    透過 ADB root / TWRP 逐磁區提取 21/23 個分區映像（`persist` 64 MB、`modemst1/2` 各 8 MB、`fsg` 8 MB、`fsc` 1 MB、`boot_a/b` 各 192 MB、`init_boot_a/b` 各 8 MB、`vendor_boot_a/b` 各 96 MB、`recovery_a/b` 各 100 MB [TWRP]、`dtbo_a/b` 各 24 MB、`dsp_a/b` 各 64 MB、`modem_a/b` 各 448 MB、`bluetooth_a/b` 各 6 MB），共約 1.95 GB，原位於 `D:\13\backup\`，後搬移至 `D:\xiaomi13\fuxi_Backup\android-partitions-20261107\`。
- **復現**：
  ```powershell
  # 核對雜湊
  cd D:\xiaomi13\fuxi_Backup\android-partitions-20261107
  sha256sum -c checksums.sha256
  # 還原特定分區（例如 recovery_a/b 或 boot_a/b，須經 launch-loader-check.ps1 或 fastboot flash）
  fastboot flash recovery_a recovery_a.img
  ```
  - 早期盤點（原 D-049「備份 `android-partitions-20261107\`（手機分區原始映像）」）另記的復現：
    還原 `recovery_a`（2026-11-14 曾誤寫 loader）或任一分區時以對應 `.img` 寫回並比對 `checksums.sha256`。
- **主機測試**：無
- **驗證紀錄**：搬移至 `D:\xiaomi13\fuxi_Backup\` 後 `sha256sum -c checksums.sha256` 全部通過；`boot_a.img` SHA-256 `3d957296bb0db5596067ff1795ce521070f3dff5f5552834c2622bfeaa42d145`，`recovery_a/b.img` SHA-256 `7d589d3c09553328530bd2c19ba87c0a27a2c77621486ad57efa3f1898a64ac1`。
  - 早期盤點（原 D-049「備份 `android-partitions-20261107\`（手機分區原始映像）」）另記的驗證與數據：
    `checksums.sha256` 搬移後 `sha256sum -c` 21/21（含全部 23 檔）全數通過。
- **參考來源**：無
- **結論／未完成**：為後續所有 Android 分區與 `boot_b` 的基準還原點。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\android-partitions-20261107\checksums.sha256`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L9,L23`; `HANDOVER.md:L15-L34`

### R-002 ios-root-images

- **日期**：2026-11-14（含 0018–0025 各版雜湊；0025 於 2026-11-14 21:23 寫入手機）
- **狀態**：部分仍在 D:（`native-layout0025-root.img` 及各版 `.img.sha256` 仍在 `D:\xiaomi13\fuxi_Backup\ios-root-images\`），0022／0023 qcow2 與 0024 raw 已於 2026-11-16 23:00 移到 `E:\fuxi_Backup-archive\ios-root-images\`
- **開關**：無
- **問題／現象**：需要保存乾淨可還原的 iOS root 基準映像，作為後續所有手機差分備份的共同基底。
- **根因**：無（乾淨系統基底映像）。
- **做法**：
  - 仍在 D:：`native-layout0025-root.img`（20 GiB raw，0024＋bridge LTO／執行緒快取配置器，SHA-256 `9dd1e7a05186de8d5cb0dff1410a59c4e8bf4a859347165d067a7b62011bc0d9`）及 `native-layout0018`～`0025-root.img.sha256`。
  - 已移到 E:：`native-layout0022-root.qcow2`（6,759,710,720 bytes）、`native-layout0023-root.qcow2`（6,759,710,720 bytes）、`native-layout0024-root.img`（21,474,836,480 bytes）。
  - 早期盤點（原 D-050「備份 `ios-root-images\`（0022/0023 qcow2、0024/0025 raw）」）另記的做法：
    原放於 `D:\13\work\fuxi-images\`，移入 `D:\xiaomi13\fuxi_Backup\ios-root-images\`；後為騰出 D: 空間（僅剩 2.6 GiB），於 2026-11-16 23:00 將 `0022`、`0023`（qcow2，各 6,759,710,720 B）與 `0024`（raw，21,474,836,480 B）搬至 `E:\fuxi_Backup-archive\ios-root-images\`，僅留 `native-layout0025-root.img`（20 GiB raw，0024＋bridge LTO／執行緒快取配置器）在 D:。
- **復現**：
  ```powershell
  # 乾淨版還原（配合 delta-stage-hash.py）
  # 若需使用 0024 請至 E:\fuxi_Backup-archive\ios-root-images\native-layout0024-root.img 取用
  sha256sum -c native-layout0025-root.img.sha256
  ```
  - 早期盤點（原 D-050「備份 `ios-root-images\`（0022/0023 qcow2、0024/0025 raw）」）另記的復現：
    配合 `delta-stage-hash.py` 還原乾淨版，或作為 `ios-root-phone-*` 差異鏈之基底。
- **主機測試**：無
- **驗證紀錄**：`0022`／`0023` qcow2 與原 raw 比對相同；`0024` SHA-256 `f128ca55d5ea654e6e950837147bcb7f6f3d5286b95f339432bec6876b9d1641` 與 `.img.sha256` 相符；`0025` SHA-256 `9dd1e7a0...11bc0d9`。
  - 早期盤點（原 D-050「備份 `ios-root-images\`（0022/0023 qcow2、0024/0025 raw）」）另記的驗證與數據：
    SHA-256：`0022.qcow2` `e6b8d23749aec16f0259ed8f53892ddf537526f7c822314e02a4a5182d013f1d`、`0023.qcow2` `6b21c0727891ad415324ab866af3a51d1a98d8d564f58cbc5ee3ea06d51ceb91`、`0024.img` `f128ca55d5ea654e6e950837147bcb7f6f3d5286b95f339432bec6876b9d1641`（各附 `.img.sha256`）。
- **參考來源**：無
- **結論／未完成**：`0025` 持續作為手機差異還原點（`ios-root-phone-20261115q`、`ios-root-hw000-20261116` 等）的基底留在 D:。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\ios-root-images\*.sha256`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L10,L24,L26-L35`; `backups-in-fuxi-backup.md:L13-L19`

### R-003 ios27-root-recovered-20261108

- **日期**：2026-11-08（2026-11-16 23:00 移至 E:）
- **狀態**：已移到 E:（`E:\fuxi_Backup-archive\ios27-root-recovered-20261108\`）
- **開關**：無
- **問題／現象**：保留從手機 `/data/ios27-root.img` 讀回的早期 iOS 27 root 映像與 extents 驗證紀錄，並騰出 D: 空間。
- **根因**：無（歷史系統備份與磁碟空間歸檔）。
- **做法**：整個資料夾含 `ios27-root.img`（8,389,656,576 bytes，約 8 GB）、extents 紀錄與 `verification.json`。
  - 早期盤點（原 D-051「備份 `ios27-root-recovered-20261108\`（`/data/ios27-root.img` 8 GB）」）另記的做法：
    由 `scripts/read_root27_backup.py` 讀回至 `candidates/recovered-root27/`，後搬入 `fuxi_Backup\ios27-root-recovered-20261108\`，並於 2026-11-16 23:00 歸檔至 `E:\fuxi_Backup-archive\ios27-root-recovered-20261108\`。
- **復現**：
  ```powershell
  # 搬移後核對（邊複製邊算 SHA-256，重讀目的檔比對相符後才刪 D: 原檔）
  sha256sum E:\fuxi_Backup-archive\ios27-root-recovered-20261108\ios27-root.img
  ```
  - 早期盤點（原 D-051「備份 `ios27-root-recovered-20261108\`（`/data/ios27-root.img` 8 GB）」）另記的復現：
    依資料夾內 `extents-before.json` 與 `verification.json` 還原或檢視。
- **主機測試**：無
- **驗證紀錄**：`verification.json` 記錄 `bytes: 8389656576`、`sha256: eb19e569e86cc71cec4cf82924c5eefb891591ab396905b6f22fd69de0667c87`；三個分區視窗（`OS` `2abe836e...`、`SystemOS` `9cd738f3...`、`AppOS` `391f2df3...`）`matches: true`，`extents_unchanged: true`。
  - 早期盤點（原 D-051「備份 `ios27-root-recovered-20261108\`（`/data/ios27-root.img` 8 GB）」）另記的驗證與數據：
    `ios27-root.img` 大小 `8,389,656,576` B，SHA-256 `eb19e569e86cc71cec4cf82924c5eefb891591ab396905b6f22fd69de0667c87`（符合 `verification.json` 與 `root_report.json`）。
- **參考來源**：無
- **結論／未完成**：歸檔保存於 E:，不再作為現行差異基底。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`E:\fuxi_Backup-archive\ios27-root-recovered-20261108\verification.json`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L11,L33`; `CONTINUATION_20261108.md:L30`

### R-004 ios-root-phone-20261115q

- **日期**：2026-11-15 22:34
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\ios-root-phone-20261115q\`）
- **開關**：`delta-pull-inplace.py --name phone1115q`
- **問題／現象**：0042 預熱 A/B（tour hyb8／hyb8n 交錯、p1 各一次）之後，保存含使用者資料的手機 iOS root 現況。
- **根因**：無（差分備份）。
- **做法**：內容物：`pull.bin`（731 個 4 MiB 區塊，約 2.86 GiB）、`diff-blocks.txt`、`phone-blocks.txt`、`README.txt`。以 `ios-root-images\native-layout0025-root.img` 為基底，將 `diff-blocks.txt` 所列 731 個 4 MiB 區塊依序替換為 `pull.bin`。
  - 早期盤點（原 D-053「備份 `ios-root-phone-20261115q\`（相對 0025 之 731 區塊差異）」）另記的做法：
    由 `delta-pull-inplace.py` 唯讀拉回，逐塊比對手機回報雜湊；還原時將 `ios-root-images\native-layout0025-root.img` 依 `diff-blocks.txt` 換入 `pull.bin` 之 731 個 4 MiB 區塊。
- **復現**：
  ```powershell
  # 重建整份映像（相對 0025 基底替換 diff-blocks.txt 的 731 個 4 MiB 區塊為 pull.bin）
  # 並核對整份 SHA-256：4cced778b63ec0f820cc5e87686b6b4213930075fa40cf673216669dfd89212a
  ```
  - 早期盤點（原 D-053「備份 `ios-root-phone-20261115q\`（相對 0025 之 731 區塊差異）」）另記的復現：
    詳見資料夾內 `README.txt` 與 `phone-blocks.txt`。
- **主機測試**：無
- **驗證紀錄**：`delta-pull-inplace.py` 唯讀拉回且每塊皆比對手機回報雜湊；基底 `0025` SHA-256 `9dd1e7a05186de8d5cb0dff1410a59c4e8bf4a859347165d067a7b62011bc0d9`，`pull.bin` SHA-256 `ee4e87e8729e28d9bc87161afe872f4c633b954e99026367e00fd6ebfa4fb2e7`，整份重組 SHA-256 `4cced778b63ec0f820cc5e87686b6b4213930075fa40cf673216669dfd89212a`。
  - 早期盤點（原 D-053「備份 `ios-root-phone-20261115q\`（相對 0025 之 731 區塊差異）」）另記的驗證與數據：
    組回整份 SHA-256 `4cced778b63ec0f820cc5e87686b6b4213930075fa40cf673216669dfd89212a`。
- **參考來源**：無
- **結論／未完成**：取代先前的 `ios-root-phone-20261114`～`20261115h`。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\ios-root-phone-20261115q\README.txt`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L12,L49`

### R-005 android-partitions-20261114

- **日期**：2026-11-14 晚間（寫入 b 槽分流器前）
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\android-partitions-20261114\`）
- **開關**：無
- **問題／現象**：寫入 b 槽開機分流器前，補充 `20261107` 備份中未包含的 `vbmeta_a/b` 與當時 `misc` 狀態。
- **根因**：無（補充備份）。
- **做法**：內容物：`misc.img`（4 MiB，備份時指令欄為 `bootonce-bootloader`）、`vbmeta_a.img`、`vbmeta_b.img`、`checksums.sha256`、`NOTES.txt`（未重複複製與 `20261107` 相同的 `boot`/`init_boot`/`vendor_boot`/`dtbo`/`recovery`）。
  - 早期盤點（原 D-052「備份 `android-partitions-20261114\`（`misc`、`vbmeta_a/b`）」）另記的做法：
    存於 `D:\xiaomi13\fuxi_Backup\android-partitions-20261114\`，附 `checksums.sha256`、`NOTES.txt`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\android-partitions-20261114
  sha256sum -c checksums.sha256
  # a/b 槽 boot/init_boot/vendor_boot/dtbo/recovery 若需還原請用 ../android-partitions-20261107/
  ```
  - 早期盤點（原 D-052「備份 `android-partitions-20261114\`（`misc`、`vbmeta_a/b`）」）另記的復現：
    b 槽原廠分區還原點直接取用 `android-partitions-20261107\`。
- **主機測試**：無
- **驗證紀錄**：`checksums.sha256`：`misc.img` `77f646cce4a0e0a7a92125e7eefdfc1cf4ea06b0e76c8331a9fdb7fa2d30d93b`、`vbmeta_a.img` / `vbmeta_b.img` `1ccc676c0f7e7453b1886c120cb5f8d91ab000defbd4cc020d9d2351349ddc76`。備份時手機槽位狀態：a 為 active+successful，b 為 bootable、not successful。
  - 早期盤點（原 D-052「備份 `android-partitions-20261114\`（`misc`、`vbmeta_a/b`）」）另記的驗證與數據：
    通過 `checksums.sha256` 驗證。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\android-partitions-20261114\NOTES.txt`、`checksums.sha256`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L13`

### R-006 android-partitions-hw000-20261116

- **日期**：2026-11-16 00:59
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\android-partitions-hw000-20261116\`）
- **開關**：無
- **問題／現象**：000 線（硬體適配）上機前，核對手機 24 個 Android 分區雜湊並備份隨使用變動的分區。
- **根因**：無（上機前分區快照）。
- **做法**：內容物：`persist.img`、`modemst1.img`、`modemst2.img`、`fsg.img`、`fsc.img`、`misc.img`、`checksums.sha256`、`phone-sha256.txt`（24 分區比對紀錄）。
  - 早期盤點（原 D-054「備份 `android-partitions-hw000-20261116\`（000 線上機前 24 分區比對）」）另記的做法：
    比對手機 24 個分區之 SHA-256 記錄於 `phone-sha256.txt`，並另行拷貝 `persist`、`modemst1/2`、`fsg`、`fsc`、`misc` 至 `D:\xiaomi13\fuxi_Backup\android-partitions-hw000-20261116\`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\android-partitions-hw000-20261116
  sha256sum -c checksums.sha256
  ```
  - 早期盤點（原 D-054「備份 `android-partitions-hw000-20261116\`（000 線上機前 24 分區比對）」）另記的復現：
    對照 `checksums.sha256` 與 `phone-sha256.txt`。
- **主機測試**：無
- **驗證紀錄**：`phone-sha256.txt` 記錄 24 個分區中 20 個與舊備份相同；`boot_b`（`375ba292...`）因已寫入 b 槽分流器而不同；`persist`（`4e0b9344...`）、`modemst1`（`3ccfce26...`）、`modemst2`（`6620909e...`）隨使用變動。
  - 早期盤點（原 D-054「備份 `android-partitions-hw000-20261116\`（000 線上機前 24 分區比對）」）另記的驗證與數據：
    24 個分區中 20 個與舊備份相同、`boot_b` 為分流器、`persist`/`modemst1/2` 隨使用變動。
- **參考來源**：無
- **結論／未完成**：000 線測試全程採 `fastboot boot`，不寫入任何分區。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\android-partitions-hw000-20261116\phone-sha256.txt`、`checksums.sha256`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L14`

### R-007 ios-root-hw000-20261116

- **日期**：2026-11-16 01:07
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\ios-root-hw000-20261116\`）
- **開關**：`hw000-delta-backup.py --name hw000-20261116`
- **問題／現象**：000 線上機前（0043＋使用者資料）保存 iOS root 還原點。
- **根因**：無（差分備份）。
- **做法**：內容物：`pull.bin`（783 個 4 MiB 區塊）、`diff-blocks.txt`、`phone-blocks.txt`、`README.txt`。以 `D:\xiaomi13\fuxi_Backup\ios-root-images\native-layout0025-root.img` 為基底，替換 `diff-blocks.txt` 所列 783 個 4 MiB 區塊為 `pull.bin`。
  - 早期盤點（原 D-055「備份 `ios-root-hw000-20261116\`（相對 0025 之 783 區塊差異）」）另記的做法：
    由 `work\adsp-battery\hw000\hw000-delta-backup.py` 唯讀拉回；將 `ios-root-images\native-layout0025-root.img` 依 `diff-blocks.txt` 替換 783 個 4 MiB 區塊為 `pull.bin` 即得完整映像。
- **復現**：
  ```powershell
  # 以 native-layout0025-root.img 依 diff-blocks.txt 替換 pull.bin，重建後核對整份 SHA-256：
  # d84336b11f93f261d656143a5ec953eb3a6c84a501d8ed40eab2c180f28c8da5
  ```
  - 早期盤點（原 D-055「備份 `ios-root-hw000-20261116\`（相對 0025 之 783 區塊差異）」）另記的復現：
    見資料夾內 `README.txt` 與 `phone-blocks.txt`。
- **主機測試**：無
- **驗證紀錄**：`hw000-delta-backup.py` 唯讀拉回並逐塊比對手機雜湊；`pull.bin` SHA-256 `b38b479e20f053db1898979bc428ba631fe78fb2f0691a1c3638fb866e0414ec`，整份 SHA-256 `d84336b11f93f261d656143a5ec953eb3a6c84a501d8ed40eab2c180f28c8da5`。
  - 早期盤點（原 D-055「備份 `ios-root-hw000-20261116\`（相對 0025 之 783 區塊差異）」）另記的驗證與數據：
    逐塊比對過手機回報雜湊，整份 SHA-256 `d84336b11f93f261d656143a5ec953eb3a6c84a501d8ed40eab2c180f28c8da5`。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\ios-root-hw000-20261116\README.txt`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L15`

### R-008 ios-root-hw000sb-20261116

- **日期**：2026-11-16 02:13（寫入狀態欄前）
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\ios-root-hw000sb-20261116\`）
- **開關**：`hw000-delta-backup.py --name hw000sb-20261116`
- **問題／現象**：修改狀態欄（`UIStatusBarVisualProviderClassName`＝Split1080，寫入 6 個區塊）前保存手機現況與局部 undo 資料。
- **根因**：無（改檔前備份）。
- **做法**：內容物：`pull.bin`（552 個 4 MiB 區塊）、`diff-blocks.txt`、`phone-blocks.txt`、`statusbar-undo.bin`（6 區塊原內容）、`statusbar-undo-list.txt`、`README.txt`。基底為 `D:\xiaomi13\fuxi_ios\work\images-build\native-layout0043-root.img`。
  - 早期盤點（原 D-056「備份 `ios-root-hw000sb-20261116\`（Split1080 狀態欄前 552 區塊差異＋undo）」）另記的做法：
    以 `work\images-build\native-layout0043-root.img` 為基底保存 552 個 4 MiB 差異區塊，另存 `statusbar-undo-list.txt`／`statusbar-undo.bin`。
- **復現**：
  ```powershell
  # 僅還原狀態欄 6 塊改動（mapper 已 map 時）：
  adb push statusbar-undo-list.txt statusbar-undo.bin work\statusbar-fix\sb-blocks-write.sh /data/local/tmp/
  adb shell "su -c 'sh /data/local/tmp/sb-blocks-write.sh /data/local/tmp/statusbar-undo-list.txt /data/local/tmp/statusbar-undo.bin'"
  ```
  - 早期盤點（原 D-056「備份 `ios-root-hw000sb-20261116\`（Split1080 狀態欄前 552 區塊差異＋undo）」）另記的復現：
    組回方式與雜湊見資料夾內 `README.txt` 與 `phone-blocks.txt`。
- **主機測試**：無
- **驗證紀錄**：基底 `0043` SHA-256 `86e55716c6655bf374f7b21706f773d78a3ccea7bfe4bc26fe9ca39311fa71d9`；`pull.bin` SHA-256 `6fb92f3fe9b309cc024915829ac989f92bf47e46e99a0cc11c670a3d85d5e341`；拉回整份 SHA-256 `879e6d748434081419614bd796288461471610debd6bf8c269df89f49cba3e6b`；寫入 6 塊後整份 SHA-256 `e333d83ddc51dd7e91f53fb169c2eb978e5207560e4fe7420a64eafe907d1370`。
  - 早期盤點（原 D-056「備份 `ios-root-hw000sb-20261116\`（Split1080 狀態欄前 552 區塊差異＋undo）」）另記的驗證與數據：
    資料夾內附完整雜湊紀錄（來源未記整檔 SHA 值）。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\ios-root-hw000sb-20261116\README.txt`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L16`

### R-009 ios-root-hw000shape-20261116

- **日期**：2026-11-16 10:18
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\ios-root-hw000shape-20261116\`）
- **開關**：`hw000-delta-backup.py --name hw000shape-20261116`
- **問題／現象**：加入 SpringBoard 形狀函式庫（`libfuxi-sb.dylib`）前保存手機 iOS root 現況。
- **根因**：無（改檔前備份）。
- **做法**：內容物：`pull.bin`（635 個 4 MiB 區塊）、`diff-blocks.txt`、`phone-blocks.txt`、`statusbar-undo.bin`（8 區塊）、`statusbar-undo-list.txt`、`README.txt`。基底為 `D:\xiaomi13\fuxi_ios\work\images-build\native-layout0043-root.img`。
  - 早期盤點（原 D-057「備份 `ios-root-hw000shape-20261116\`（SpringBoard 形狀函式庫前 635 區塊差異＋undo）」）另記的做法：
    以 `work\images-build\native-layout0043-root.img` 為基底保存 635 個 4 MiB 差異區塊，另含 `statusbar-undo-list.txt`。
- **復現**：
  ```powershell
  # 僅還原該次 8 塊修改（mapper 已 map 時）：
  adb push statusbar-undo-list.txt statusbar-undo.bin work\statusbar-fix\sb-blocks-write.sh /data/local/tmp/
  adb shell "su -c 'sh /data/local/tmp/sb-blocks-write.sh /data/local/tmp/statusbar-undo-list.txt /data/local/tmp/statusbar-undo.bin'"
  ```
  - 早期盤點（原 D-057「備份 `ios-root-hw000shape-20261116\`（SpringBoard 形狀函式庫前 635 區塊差異＋undo）」）另記的復現：
    見資料夾內 `README.txt` 與 `phone-blocks.txt`。
- **主機測試**：無
- **驗證紀錄**：`pull.bin` SHA-256 `ee1bb3bad09a940bec1bf239c7ad120f3e3e7e04ee16330e52998acaa7afe674`；拉回整份（逐塊驗證及串流重建）SHA-256 `3fb053ddbc0d78f6a14383fdbd600b71aecfe87ed5747c77cc7f35249da5c092`；寫入 8 塊後整份 SHA-256 `c59c15855fa9879d274385fa870f956ec5c34310587ba04f37688bcff728f24a`。
  - 早期盤點（原 D-057「備份 `ios-root-hw000shape-20261116\`（SpringBoard 形狀函式庫前 635 區塊差異＋undo）」）另記的驗證與數據：
    逐塊驗證及串流重建整份 SHA-256 `3fb053ddbc0d78f6a14383fdbd600b71aecfe87ed5747c77cc7f35249da5c092`。
- **參考來源**：無
- **結論／未完成**：完成，且作為後續 `ios-root-hw000shape2-20261116` 的父還原點。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\ios-root-hw000shape-20261116\README.txt`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L17`

### R-010 boot_b-chain-v1-20261116

- **日期**：2026-11-16 06:33（寫入 chain-v2 前）
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v1-20261116\`）
- **開關**：無
- **問題／現象**：將日常開機分流器從 chain-v1 升級為 chain-v2（電量＋亮度）前，備份當時 `boot_b` 與 KSU 模組。
- **根因**：無（升級前備份）。
- **做法**：內容物：`boot_b-chain-v1.img`（`boot_b` 前 66,326,528 bytes）、`fuxi_ios_boot-chain-v1.zip`、`sha256.txt`、`build.txt`（記錄 `force_linux=False`、`auto_launch_s=5`、payload 來自 `native-auto-cool-loader`、kernel 來自 `android-partitions-20261107\boot_a.img`）。
  - 早期盤點（原 D-058「備份 `boot_b-chain-v1-20261116\`（`boot_b` chain-v1＋KSU v1 zip）」）另記的做法：
    備份 `boot_b-chain-v1.img`（`boot_b` 前 66,326,528 位元組）及 `fuxi_ios_boot-chain-v1.zip`。
- **復現**：
  ```powershell
  # 照 work\adsp-battery\hw000\hw000-deploy-bootb.sh 做法：
  # push boot_b-chain-v1.img -> dd 寫入 boot_b -> 讀回前 66326528 bytes 比對 SHA-256
  # 再將 fuxi_ios_boot-chain-v1.zip 內的 loader.sha256 / loader.size / expected-fiemap.txt 放回 /data/adb/modules/fuxi_ios_boot/
  ```
  - 早期盤點（原 D-058「備份 `boot_b-chain-v1-20261116\`（`boot_b` chain-v1＋KSU v1 zip）」）另記的復現：
    照 `work\adsp-battery\hw000\hw000-deploy-bootb.sh` 流程寫回 `boot_b` 並將 zip 內 `loader.sha256`/`loader.size`/`expected-fiemap.txt` 換回 `/data/adb/modules/fuxi_ios_boot/`。
- **主機測試**：無
- **驗證紀錄**：`boot_b-chain-v1.img` SHA-256 `9924fe1c...3f06`（`README.md` 載明與手機讀回相同）。
  - 早期盤點（原 D-058「備份 `boot_b-chain-v1-20261116\`（`boot_b` chain-v1＋KSU v1 zip）」）另記的驗證與數據：
    SHA-256 `9924fe1c…3f06` 與手機讀回及主機 `work\boot-chain\chain-v1` 相符（附 `sha256.txt`、`build.txt`）。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\boot_b-chain-v1-20261116\build.txt`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L18`

### R-011 boot_b-chain-v2-20261116

- **日期**：2026-11-16 08:47:28（寫入 chain-v3 前）
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v2-20261116\`）
- **開關**：無
- **問題／現象**：寫入 chain-v3 前，備份當時 `boot_b` 裡的 chain-v2 與 KSU 模組。
- **根因**：無（升級前備份）。
- **做法**：內容物：`boot_b-chain-v2.img`（前 66,326,528 bytes）、`fuxi_ios_boot-module.tar`（當時 `/data/adb/modules/fuxi_ios_boot/` 整個資料夾）、`module-list.txt`、`chain-v2-sha256.txt`、`chain-v2-build.txt`、`NOTES.txt`、`SHA256SUMS`。
  - 早期盤點（原 D-059「備份 `boot_b-chain-v2-20261116\`（`boot_b` chain-v2＋KSU v3 tar）」）另記的做法：
    備份 `boot_b-chain-v2.img`（`boot_b` 前 66,326,528 位元組）與 `fuxi_ios_boot-module.tar`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\boot_b-chain-v2-20261116
  sha256sum -c SHA256SUMS
  # 還原：將 boot_b-chain-v2.img 經 dd 寫回 boot_b 並讀回比對；將 fuxi_ios_boot-module.tar 解回 /data/adb/modules/
  ```
  - 早期盤點（原 D-059「備份 `boot_b-chain-v2-20261116\`（`boot_b` chain-v2＋KSU v3 tar）」）另記的復現：
    照 `work\adsp-battery\hw000\hw000-deploy-bootb-v3.sh` 寫回 `boot_b` 並換回 tar 內 4 個模組檔。
- **主機測試**：無
- **驗證紀錄**：`SHA256SUMS`：`boot_b-chain-v2.img` `994c95d6b78118ae625bb5919da2c7e416a5644fb403abc655ec4c6a85bcf25d`（等於主機 `work\boot-chain\chain-v2\boot.img`）、`fuxi_ios_boot-module.tar` `711bac414ab5bb2db6bf2dad773952bb822fe74f0a1557fcf182cc6eb1f49130`。
  - 早期盤點（原 D-059「備份 `boot_b-chain-v2-20261116\`（`boot_b` chain-v2＋KSU v3 tar）」）另記的驗證與數據：
    SHA-256 `994c95d6…f25d` 與手機讀回及主機 `work\boot-chain\chain-v2` 相符（附 `SHA256SUMS`、`NOTES.txt`）。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\boot_b-chain-v2-20261116\NOTES.txt`、`SHA256SUMS`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L19`

### R-012 mtdblk-20261116

- **日期**：2026-11-16 07:46:52
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\mtdblk-20261116\`）
- **開關**：無
- **問題／現象**：啟用核心 `fx_log`（將獨立開機 console 寫入 `mtdblk` 前 2049 個 4 KiB 區塊）前，保存原始 `mtdblk` 分區。
- **根因**：無（蓋章前原始分區備份）。
- **做法**：內容物：`mtdblk.img`（`/dev/block/sda19`，LUN 0，33,554,432 bytes＝32 MiB，全為 0；Android／abl／xbl／uefi 皆未使用）、`SHA256SUMS`、`phone-sha256.txt`。
  - 早期盤點（原 D-060「備份 `mtdblk-20261116\`（`/dev/block/sda19` 蓋章前全零映像）」）另記的做法：
    完整讀回 `mtdblk.img`（32 MiB，全 0）存於 `D:\xiaomi13\fuxi_Backup\mtdblk-20261116\`，附 `SHA256SUMS`、`phone-sha256.txt`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\mtdblk-20261116
  sha256sum -c SHA256SUMS
  # 還原：將 mtdblk.img dd 回 /dev/block/by-name/mtdblk（或整顆寫 0）
  ```
  - 早期盤點（原 D-060「備份 `mtdblk-20261116\`（`/dev/block/sda19` 蓋章前全零映像）」）另記的復現：
    將 `mtdblk.img` `dd` 回 `/dev/block/by-name/mtdblk`（或整分區寫 0）。
- **主機測試**：無
- **驗證紀錄**：`SHA256SUMS`：`mtdblk.img` SHA-256 `83ee47245398adee79bd9c0a8bc57b821e92aba10f5f9ade8a5d1fae4d8c4302`（33,554,432 bytes）。
  - 早期盤點（原 D-060「備份 `mtdblk-20261116\`（`/dev/block/sda19` 蓋章前全零映像）」）另記的驗證與數據：
    確認原分區全為 0。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\mtdblk-20261116\SHA256SUMS`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L20`

### R-013 boot_b-chain-v3-before-chain-v4-20261116-121904

- **日期**：2026-11-16 12:19:04
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-121904\`）
- **開關**：無
- **問題／現象**：部署 `chain-v4` 前備份當時 `boot_b`（`chain-v3`）與 KSU 模組（首次執行）。
- **根因**：無（部署前自動備份）。
- **做法**：內容物：`boot_b.img.gz`（完整 `boot_b` 201,326,592 bytes 壓縮檔）、`fuxi_ios_boot-module.tar`、`host-module-before\`（`loader.sha256`、`loader.size`、`expected-fiemap.txt`、`module.prop`）、`state.txt`、`SHA256SUMS`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-121904
  sha256sum -c SHA256SUMS
  # 解壓 boot_b.img.gz 並經由驗證寫回 boot_b；將 fuxi_ios_boot-module.tar 解回 /data/adb/modules/
  ```
- **主機測試**：無
- **驗證紀錄**：`state.txt`：`previous=chain-v3`、`previous_prefix_sha256=2965b2cce5f9c1aef514a454e3299e3343b8637e7ad3a7e307cf38bf8973c27c`、`boot_b_full_sha256=5e44c4608778c647d626705e69f5e3a24b9c87946514424125192c594c1afc85`、`next=chain-v4`、`next_prefix_sha256=dc9c0158638b319a10cb38b09531eb1e324b433bf287a7a4e33596058b3ec5e2`、`boot_a_sha256=3d957296bb0db5596067ff1795ce521070f3dff5f5552834c2622bfeaa42d145`。`SHA256SUMS`：`fuxi_ios_boot-module.tar` `8a7205efac2fc45facc242b7db41b3b737929d94c5df0efe59f1f83d22a50374`、`boot_b.img.gz` `81f35d0e91b784821c25ca84283ce2f55c90e11607121d143775963ecd0bb7f8`。
- **參考來源**：無
- **結論／未完成**：完成（同次重試另有 `122005`、`122108` 兩份）。
- **出處**：`D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-121904\state.txt`、`SHA256SUMS`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-014 boot_b-chain-v3-before-chain-v4-20261116-122005

- **日期**：2026-11-16 12:20:05
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-122005\`）
- **開關**：無
- **問題／現象**：部署 `chain-v4` 第二次嘗試時自動建立的備份（`boot_b` 尚未改動，故僅存模組與狀態；未重複壓縮 `boot_b.img.gz`）。
- **根因**：無（部署前自動備份）。
- **做法**：內容物：`fuxi_ios_boot-module.tar`、`host-module-before\`（`loader.sha256`、`loader.size`、`expected-fiemap.txt`、`module.prop`）、`state.txt`、`SHA256SUMS`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-122005
  sha256sum -c SHA256SUMS
  # boot_b 映像需取用 R-013 (121904) 的 boot_b.img.gz；將 fuxi_ios_boot-module.tar 解回 /data/adb/modules/
  ```
- **主機測試**：無
- **驗證紀錄**：`state.txt` 與 R-013 完全相同（`previous=chain-v3`、`next=chain-v4`、`boot_b_full_sha256=5e44c460...1afc85`）；`SHA256SUMS`：`fuxi_ios_boot-module.tar` `959c69c0dbefaf2c89bd6b8148bfc43d0bbcfdc94b9098302e14c2b2037b628d`。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-122005\state.txt`、`SHA256SUMS`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-015 boot_b-chain-v3-before-chain-v4-20261116-122108

- **日期**：2026-11-16 12:21:08
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-122108\`）
- **開關**：無
- **問題／現象**：部署 `chain-v4` 第三次嘗試時自動建立的備份。
- **根因**：無（部署前自動備份）。
- **做法**：內容物：`fuxi_ios_boot-module.tar`、`host-module-before\`（`loader.sha256`、`loader.size`、`expected-fiemap.txt`、`module.prop`）、`state.txt`、`SHA256SUMS`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-122108
  sha256sum -c SHA256SUMS
  # boot_b 映像取用 R-013 (121904) 的 boot_b.img.gz；將 fuxi_ios_boot-module.tar 解回 /data/adb/modules/
  ```
- **主機測試**：無
- **驗證紀錄**：`state.txt` 與 R-013 相同；`SHA256SUMS`：`fuxi_ios_boot-module.tar` `2084021eb7c3f5d9ca8b616486dd902712a7feadf4a70911a5d3b95b832c2240`。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\boot_b-chain-v3-before-chain-v4-20261116-122108\state.txt`、`SHA256SUMS`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-016 boot_b-chain-v4-before-chain-v6-ram9g-batfresh-20261116-161041

- **日期**：2026-11-16 16:10:41
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v4-before-chain-v6-ram9g-batfresh-20261116-161041\`）
- **開關**：無
- **問題／現象**：從 5g `chain-v4` 升級為 9g `chain-v6-ram9g-batfresh` 前的還原點。
- **根因**：無（部署前自動備份）。
- **做法**：內容物：`boot_b.img.gz`、`fuxi_ios_boot-module.tar`、`host-module-before\`（`loader.sha256`、`loader.size`、`expected-fiemap.txt`、`module.prop`）、`state.txt`、`SHA256SUMS`（`state.txt` 另有 `boot_b_recovery_source=D:\xiaomi13\fuxi_ios\work\boot-chain\chain-v4\boot.img`，prefix 66,326,528 bytes）。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\boot_b-chain-v4-before-chain-v6-ram9g-batfresh-20261116-161041
  sha256sum -c SHA256SUMS
  # 還原 boot_b 可用 boot_b.img.gz 或 work\boot-chain\chain-v4\boot.img 寫回並讀回核對，並解回 fuxi_ios_boot-module.tar
  ```
- **主機測試**：無
- **驗證紀錄**：`state.txt`：`previous=chain-v4`（`dc9c0158...8b3ec5e2`）、`next=chain-v6-ram9g-batfresh`（`93cb7d5f...4f8d24e`）、`boot_a_sha256=3d957296...aa42d145`。`SHA256SUMS`：`fuxi_ios_boot-module.tar` `b511e6c6bec805446d84b0f389bf268a5a4fea3a707a68e06b75bd6fc02a3849`、`boot_b.img.gz` `364e4c3db807d450efd0a018095d9febaee586a301d17d2a0dee5e5745abf81e`。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\boot_b-chain-v4-before-chain-v6-ram9g-batfresh-20261116-161041\state.txt`、`SHA256SUMS`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-017 boot_b-chain-v6-ram9g-batfresh-before-chain-v7-ram9g-rtctorch-20261117-024231

- **日期**：2026-11-17 02:42:31
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v6-ram9g-batfresh-before-chain-v7-ram9g-rtctorch-20261117-024231\`）
- **開關**：無
- **問題／現象**：從 `chain-v6-ram9g-batfresh` 升級為 `chain-v7-ram9g-rtctorch` 前的還原點。
- **根因**：無（部署前自動備份）。
- **做法**：內容物：`boot_b.img.gz`、`fuxi_ios_boot-module.tar`、`host-module-before\`（含 `loader.sha256`、`loader.size`、`twrp.sha256`、`expected-fiemap.txt`、`module.prop`）、`state.txt`、`SHA256SUMS`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\boot_b-chain-v6-ram9g-batfresh-before-chain-v7-ram9g-rtctorch-20261117-024231
  sha256sum -c SHA256SUMS
  # 還原 boot_b（來源亦見 state.txt 的 work\boot-chain\chain-v6-ram9g-batfresh\boot.img）與 fuxi_ios_boot-module.tar
  ```
- **主機測試**：無
- **驗證紀錄**：`state.txt`：`previous=chain-v6-ram9g-batfresh`（`93cb7d5f...`）、`next=chain-v7-ram9g-rtctorch`（`eb985a344eaa2c57d3ab3005c96f204a5e44fd3df785267eec60875b3bfe3483`）。`SHA256SUMS`：`fuxi_ios_boot-module.tar` `9eededafafb6a083db5d48bd5aad9a898f8f53bc7687836d6af15828f67edb7e`、`boot_b.img.gz` `cf03c53392e1dc762daec1ab80948695743710bdb9e42603250d900c99ac3a00`。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\boot_b-chain-v6-ram9g-batfresh-before-chain-v7-ram9g-rtctorch-20261117-024231\state.txt`、`SHA256SUMS`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-018 boot_b-chain-v7-ram9g-rtctorch-before-chain-v8-dualboot-wifi-20261118-031406

- **日期**：2026-11-18 03:14:06
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v7-ram9g-rtctorch-before-chain-v8-dualboot-wifi-20261118-031406\`）
- **開關**：無
- **問題／現象**：從 `chain-v7-ram9g-rtctorch` 升級為 `chain-v8-dualboot-wifi`（含原生 Wi-Fi 與三按鈕雙系統選單）前的完整還原點。
- **根因**：無（部署前自動備份）。
- **做法**：內容物：`boot_b.img.gz`（完整 `boot_b` 201,326,592 bytes 壓縮檔）、`fuxi_ios_boot-module.tar`、`host-module-before\`（`loader.sha256`、`loader.size`、`twrp.sha256`、`expected-fiemap.txt`、`module.prop`）、`state.txt`、`SHA256SUMS`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\boot_b-chain-v7-ram9g-rtctorch-before-chain-v8-dualboot-wifi-20261118-031406
  sha256sum -c SHA256SUMS
  # 解壓 boot_b.img.gz 寫回 boot_b 並核對整份 SHA-256 94c2e5d9...；解回 fuxi_ios_boot-module.tar
  ```
- **主機測試**：無
- **驗證紀錄**：`state.txt`：`previous=chain-v7-ram9g-rtctorch`（`eb985a34...`）、`boot_b_full_sha256=94c2e5d9c1c00fc3e02d6a4e48d3ba240885d496f8c1f825266a3e0e2d10a395`、`next=chain-v8-dualboot-wifi`（`dc7240d7cfdc37141e0430d742ee83a8cb2a25fed3aa9c65e7e6b5cad792d39e`）、`boot_a_sha256=3d957296...aa42d145`。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\boot_b-chain-v7-ram9g-rtctorch-before-chain-v8-dualboot-wifi-20261118-031406\state.txt`、`SHA256SUMS`、`dualboot\VALIDATION.zh-TW.md`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-019 boot_b-chain-v8-dualboot-wifi-before-chain-v9-dualboot-launching-20261118-042629

- **日期**：2026-11-18 04:26:29
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\boot_b-chain-v8-dualboot-wifi-before-chain-v9-dualboot-launching-20261118-042629\`）
- **開關**：無
- **問題／現象**：將 `boot_b` 更新為 `chain-v9-dualboot-launching`（與 `boot_a` 常駐選單同步為「進入系統中」版本）前的還原點。
- **根因**：無（部署前自動備份）。
- **做法**：內容物：`boot_b.img.gz`（完整 `boot_b` 201,326,592 bytes 壓縮檔）、`fuxi_ios_boot-module.tar`、`host-module-before\`（`loader.sha256`、`loader.size`、`twrp.sha256`、`expected-fiemap.txt`、`module.prop`）、`state.txt`、`SHA256SUMS`。
- **復現**：
  ```powershell
  cd D:\xiaomi13\fuxi_Backup\boot_b-chain-v8-dualboot-wifi-before-chain-v9-dualboot-launching-20261118-042629
  sha256sum -c SHA256SUMS
  # 解壓 boot_b.img.gz 寫回 boot_b 並核對整份 SHA-256 9d967afb...；解回 fuxi_ios_boot-module.tar
  ```
- **主機測試**：無
- **驗證紀錄**：`state.txt`：`previous=chain-v8-dualboot-wifi`（`dc7240d7...`）、`boot_b_full_sha256=9d967afbdad6c5e26b1f8fd3eea7c49851269872868e9cb7a4f173533d500f00`、`next=chain-v9-dualboot-launching`（`7977fbf0c8813ec16d76608bd24b1a930dda769fc1b2a8ed06c690fe013a2773`）、`boot_a_sha256=275dac0fdb0d5beb21e6a26de3126b10c8fbc514b47ce9c24fcdf66c1112b4b1`（已常駐選單）。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\boot_b-chain-v8-dualboot-wifi-before-chain-v9-dualboot-launching-20261118-042629\state.txt`、`SHA256SUMS`、`dualboot\VALIDATION.zh-TW.md`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-020 dualboot-before-validation-20261118-014941

- **日期**：2026-11-18 01:49:41（iOS root 差分完成核對於 02:31:04）
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\dualboot-before-validation-20261118-014941\`）
- **開關**：`hw000-delta-backup.py --name dualboot1118`
- **問題／現象**：進行雙系統選單實機驗證與安裝常駐引導前，保存工作區原始碼、14 個手機分區、KSU 模組與 iOS root 現況的完整還原點。
- **根因**：無（驗證與常駐寫入前完整還原點）。
- **做法**：內容物：`workspace\`（當時工作區備份與 `menu-stacked-buttons-20261117`）、`phone\`（14 個手機分區備份、mtd log、KSU 模組、`manifest.json`、`RESTORE.txt`）、`ios-root\`（相對 `D:\xiaomi13\fuxi_ios\work\images-build\native-layout0043-root.img` 的 1,229 個 4 MiB 差異區塊 `pull.bin`、`diff-blocks.txt`、`phone-blocks.txt`、`README.txt`）、`manifest.json`、`RESTORE_POINT_READY.json`、`README.txt`、`README_READY.zh-TW.txt`、`HEAD.txt`、`git-status.txt`。
- **復現**：
  ```powershell
  # 還原工作區檔案：依 manifest.json 將 workspace/ 下對應路徑複製回工作區
  # 還原手機分區：經 launch-loader-check.ps1 依 phone/manifest.json 核對前像與寫後讀回
  # 還原 iOS root：以 native-layout0043-root.img 為基底套用 ios-root/ 1229 個 4 MiB 區塊，核對整份 SHA-256：
  # aad481888dea14cf829b40bbb32ba3118f6469971b6c0f9b1f8534bdfb91d519
  ```
- **主機測試**：無
- **驗證紀錄**：`RESTORE_POINT_READY.json` 記載 `boot_partition_writes: 0`、`slot_changes: 0`、`boot_manifest_sha256: d1dd75ea2658ba7a2a6c412aa9f9b59a2701d19c08b2b20af47afdcf8c40ea12`、`pull_sha256: c5ccf0e83598530000e9ed3178ec2396231e667f6e96f3cff7d6a86e53e55897`、`whole_sha256: aad481888dea14cf829b40bbb32ba3118f6469971b6c0f9b1f8534bdfb91d519`；狀態 `READY`。
- **參考來源**：無
- **結論／未完成**：完成；基底檔 `native-layout0043-root.img` 須保留不可刪除。
- **出處**：`D:\xiaomi13\fuxi_Backup\dualboot-before-validation-20261118-014941\RESTORE_POINT_READY.json`、`README.txt`、`ios-root\README.txt`、`phone\RESTORE.txt`、`dualboot\VALIDATION.zh-TW.md`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-021 ios-root-hw000provider-20261116

- **日期**：2026-11-16
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\ios-root-hw000provider-20261116\`）
- **開關**：`hw000-delta-backup.py --name hw000provider-20261116`
- **問題／現象**：部署狀態欄 UIKit 偏好鍵（provider `3edcfe8`）前的增量還原點，並含 5 個寫入區塊的 undo 資料。
- **根因**：無（改檔前增量備份）。
- **做法**：內容物：`pull.bin`（259 個 4 MiB 區塊）、`diff-blocks.txt`、`phone-blocks.txt`、`parent.json`（指向父還原點 `D:\xiaomi13\fuxi_Backup\ios-root-hw000shape2-20261116`）、`statusbar-undo.bin`（5 區塊）、`statusbar-undo-list.txt`、`README.txt`。基底為 `native-layout0043-root.img`。
- **復現**：
  ```powershell
  # 重建整份映像：以 native-layout0043-root.img 為基底，先依序套用 hw000shape -> hw000shape2，再套用本層 259 塊
  # 僅還原該次 5 塊狀態欄修改（mapper 已 map 時）：
  adb push statusbar-undo-list.txt statusbar-undo.bin work\statusbar-fix\sb-blocks-write.sh /data/local/tmp/
  adb shell "su -c 'sh /data/local/tmp/sb-blocks-write.sh /data/local/tmp/statusbar-undo-list.txt /data/local/tmp/statusbar-undo.bin'"
  ```
- **主機測試**：無
- **驗證紀錄**：`pull.bin` SHA-256 `91513c9d154f2aaa761cca6b26793443e68baeff41d8b0d2a1556f68b0dcba48`；拉回整份 SHA-256 `9f2e9e8fae4dba7ddc8edce29779505cacfae23964c0774a9a8a5d9cbac7026c`；寫入 5 塊後整份 SHA-256 `2685508ccd2ddec7f1d92504e1edc8f2ab00a04674d14f5da48927bd2390f807`。
- **參考來源**：無
- **結論／未完成**：完成；為 `ios-root-hw000torch-runtime-20261116` 的父還原點。
- **出處**：`D:\xiaomi13\fuxi_Backup\ios-root-hw000provider-20261116\README.txt`、`parent.json`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-022 ios-root-hw000shape2-20261116

- **日期**：2026-11-16
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\ios-root-hw000shape2-20261116\`）
- **開關**：`hw000-delta-backup.py --name hw000shape2-20261116`
- **問題／現象**：第二次狀態欄／形狀函式庫修改（寫入 6 個區塊）前的增量還原點。
- **根因**：無（改檔前增量備份）。
- **做法**：內容物：`pull.bin`（233 個 4 MiB 區塊）、`diff-blocks.txt`、`phone-blocks.txt`、`parent.json`（指向父還原點 `D:\xiaomi13\fuxi_Backup\ios-root-hw000shape-20261116`）、`statusbar-undo.bin`（6 區塊）、`statusbar-undo-list.txt`、`README.txt`。基底為 `native-layout0043-root.img`。
- **復現**：
  ```powershell
  # 重建整份映像：以 native-layout0043-root.img 為基底，先套用 hw000shape，再套用本層 233 塊
  # 僅還原該次 6 塊修改（mapper 已 map 時）：
  adb push statusbar-undo-list.txt statusbar-undo.bin work\statusbar-fix\sb-blocks-write.sh /data/local/tmp/
  adb shell "su -c 'sh /data/local/tmp/sb-blocks-write.sh /data/local/tmp/statusbar-undo-list.txt /data/local/tmp/statusbar-undo.bin'"
  ```
- **主機測試**：無
- **驗證紀錄**：`pull.bin` SHA-256 `d7f2195e49b60e40634ea069ea4d0263032b8a172e07c29cfc083b3d36015386`；拉回整份 SHA-256 `45e4f114880d567f93bb578dc0042b60ca2db6511de89d40284eda8655aac683`；寫入 6 塊後整份 SHA-256 `772839baa7a94813047be21dcb0e269504c6c041552d2379a8369ad123a473cf`。
- **參考來源**：無
- **結論／未完成**：完成；為 `ios-root-hw000provider-20261116` 的父還原點。
- **出處**：`D:\xiaomi13\fuxi_Backup\ios-root-hw000shape2-20261116\README.txt`、`parent.json`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-023 ios-root-hw000torch-cap-20261116

- **日期**：2026-11-16 13:34:35 開始，13:37:56 中止
- **狀態**：已中止／不存在於 D:（資料夾未建立完成）
- **開關**：無
- **問題／現象**：原計畫在安裝控制中心手電筒能力 hook（`0806a94`）前建立此現況還原點。
- **根因**：13:37 使用者要求「不用花太多時間備份做還原點了，每輪次提交就行了」、「進度流程加快」，遂於 13:37:56 中止完整逐塊備份，改用 `phone-readthrough.py` 按需讀取與只保存本輪改動原區塊。
- **做法**：當時手機尚未寫入，既有 `hw000torch-runtime` 還原點保留；`D:\xiaomi13\fuxi_Backup\ios-root-hw000torch-cap-20261116` 資料夾不存在。
- **復現**：無（此還原點未產出；改用 `phone-readthrough.py`）。
- **主機測試**：無
- **驗證紀錄**：無（13:37:56 中止前未寫手機）。
- **參考來源**：無
- **結論／未完成**：已中止；由 `ios-root-hw000torch-runtime-20261116` 作為實際最後一個增量完整還原點，之後改用 `phone-readthrough.py`。
- **出處**：`work/hw000-adaptation-status.zh-TW.md` L202、L206（「13:08–13:36 接續證據」「13:37 起加速方式與13:47上機」）。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-024 ios-root-hw000torch-runtime-20261116

- **日期**：2026-11-16 13:08:24 完成（12:45 首次下載中斷後由 `--resume-download` 續驗完成）
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\ios-root-hw000torch-runtime-20261116\`）
- **開關**：`hw000-delta-backup.py --name hw000torch-runtime-20261116`（中斷後用 `--resume-download`）
- **問題／現象**：安裝手電筒控制 `c51f5bd` 函式庫前的完整還原點；12:45 曾因主機 `pull.bin` 僅收到 497,090,560 bytes 中斷，後經 `--resume-download` 重讀全 5120 塊核對並重拉完成。
- **根因**：無（改檔前增量備份）。
- **做法**：內容物：`pull.bin`（1,530,920,960 bytes，365 個 4 MiB 區塊）、`diff-blocks.txt`、`phone-blocks.txt`、`parent.json`（指向父還原點 `D:\xiaomi13\fuxi_Backup\ios-root-hw000provider-20261116`）、`statusbar-undo.bin`（6 區塊：0, 1169, 1721, 1722, 3012, 3020）、`statusbar-undo-list.txt`、`README.txt`。基底為 `native-layout0043-root.img`。
- **復現**：
  ```powershell
  # 重建整份映像：以 native-layout0043-root.img 為基底，依序套用 hw000shape -> hw000shape2 -> hw000provider -> 本層 365 塊
  # 僅還原 c51f5bd 寫入的 6 塊（mapper 已 map 時）：
  adb push statusbar-undo-list.txt statusbar-undo.bin work\statusbar-fix\sb-blocks-write.sh /data/local/tmp/
  adb shell "su -c 'sh /data/local/tmp/sb-blocks-write.sh /data/local/tmp/statusbar-undo-list.txt /data/local/tmp/statusbar-undo.bin'"
  ```
- **主機測試**：無
- **驗證紀錄**：`pull.bin` SHA-256 `bc32dd6e8ed27de9ea3857837cadafec4d76bfdd611b0f5a382f5a2fa1194a9f`；拉回整份 SHA-256 `fedad8323dcd5541a657ad9eb90ce3467689547f5ab5b7880c9aeb4d03221447`；寫入 6 塊（`PRE_OK 6`／`WRITE_OK 6`）後整份 SHA-256 `4d2805a57114813369d81e2c0cbcffab6a6abf6f6f5da0d33b9d8dc47001368f`。
- **參考來源**：無
- **結論／未完成**：完成。
- **出處**：`D:\xiaomi13\fuxi_Backup\ios-root-hw000torch-runtime-20261116\README.txt`、`parent.json`、`work/hw000-adaptation-status.zh-TW.md` L188–L197。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-025 ksu-module-remove-ksu-module-20261118

- **日期**：2026-11-18 04:44:54
- **狀態**：仍在 D:（`D:\xiaomi13\fuxi_Backup\ksu-module-remove-ksu-module-20261118\`）
- **開關**：無
- **問題／現象**：`boot_a` 常駐 dualboot 選單後，一般重開即可選 iOS，KSU 模組 `fuxi_ios_boot`（v9）只剩重開按鈕而依使用者要求移除，移除前先做完整封存。
- **根因**：無（移除前封存）。
- **做法**：內容物：`fuxi_ios_boot-module.tar`、`README.txt`（未列額外尺寸檔）。
  - 早期盤點（原 D-061「備份 `ksu-module-remove-ksu-module-20261118\` 與 `workspace-20261118\`」）另記的做法：
    1. 保存 `fuxi_ios_boot-module.tar` 至 `D:\xiaomi13\fuxi_Backup\ksu-module-remove-ksu-module-20261118\`（附 `README.txt`）；
      2. 經使用者同意，將 65 檔（23.98 GiB，含 `candidates\vm-tools\ios16-root-build.img`、`work\Codex-Xiaomi13-GPU-20261109\dyld-cache\` 44 檔、根目錄 11-07/08 的 `fuxi-xnu-boot.img*`/`payload*.bin`/`twrp_trimmed.img`/`apple_boot_screen.bgra`/`zadig.exe` 20 檔）邊算 SHA-256 邊複製並重讀比對後搬至 `E:\fuxi_Backup-archive\workspace-20261118\`（附 `SHA256SUMS` 與 `MANIFEST.tsv`），另留 `work\cleanup-20261118-prune.tsv` 總清單。
- **復現**：
  ```powershell
  # 還原方式 1：經 launch-loader-check.ps1 把 fuxi_ios_boot-module.tar 解到 /data/adb/modules 後重開
  # 還原方式 2：在 KSU 安裝 work/ksu-ios-entry 的模組 zip
  ```
  - 早期盤點（原 D-061「備份 `ksu-module-remove-ksu-module-20261118\` 與 `workspace-20261118\`」）另記的復現：
    見 `D:\xiaomi13\fuxi_Backup\ksu-module-remove-ksu-module-20261118\README.txt`；若需用 `stream_ios16_candidate.py` 須加 `--image` 指至 E: 歸檔路徑。
- **主機測試**：無
- **驗證紀錄**：`fuxi_ios_boot-module.tar` SHA-256 `4cb1cb090cb6a55f4b255c84fd366b5a7d040805713fa2c3a1ef0cd5b3882b79`，逐檔與手機核對過。
  - 早期盤點（原 D-061「備份 `ksu-module-remove-ksu-module-20261118\` 與 `workspace-20261118\`」）另記的驗證與數據：
    `fuxi_ios_boot-module.tar` SHA-256 `4cb1cb090cb6a55f4b255c84fd366b5a7d040805713fa2c3a1ef0cd5b3882b79`（逐檔與手機核對）；`workspace-20261118\SHA256SUMS` `sha256sum -c` 全數通過。
- **參考來源**：無
- **結論／未完成**：完成；原模組做的 iOS 根映像檢查改由電腦端 `dualboot/phone-check.py` 執行。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`D:\xiaomi13\fuxi_Backup\ksu-module-remove-ksu-module-20261118\README.txt`、`dualboot\VALIDATION.zh-TW.md`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）；早期盤點出處：`D:\xiaomi13\fuxi_Backup\README.md:L37-L47`; `xiaomi13-standalone-boot.md:L11`

### R-026 E:\fuxi_Backup-archive\workspace-20261118

- **日期**：2026-11-18
- **狀態**：已移到 E:（`E:\fuxi_Backup-archive\workspace-20261118\`）
- **開關**：無
- **問題／現象**：整理工作區時 D: 僅剩 3.7 GiB，經使用者同意將不再使用的舊大型檔案搬離 D: 並保留相對路徑與校驗。
- **根因**：無（磁碟空間清理歸檔）。
- **做法**：共 65 檔、合計 23.98 GiB，依原工作區相對路徑存放，附 `SHA256SUMS` 與 `MANIFEST.tsv`：
  1. `candidates/vm-tools/ios16-root-build.img`（21,474,836,480 bytes，11-08 建置映像；`stream_ios16_candidate.py`/`verify_ios16_candidate.py` 預設仍指 D:，使用須加 `--image`）。
  2. `work/Codex-Xiaomi13-GPU-20261109/dyld-cache/`（11-13 擷取，44 檔，合計 3,330,359,296 bytes）。
  3. 工作區根目錄 11-07／08 舊檔：`fuxi-xnu-boot.img*`（3 檔）、`payload*.bin`（8 檔）、`twrp_trimmed.img`、各 `.zip`（6 檔：`scratch.zip`、`python.zip`、`fuxi-ios-handover.zip`、`UniXNU.zip`、`unixnu-fuxi.zip`、`pylib.zip`）、`apple_boot_screen.bgra`、`zadig.exe`，共 20 檔，合計 942,521,576 bytes。
- **復現**：
  ```powershell
  cd E:\fuxi_Backup-archive\workspace-20261118
  sha256sum -c SHA256SUMS
  # 若需使用 ios16-root-build.img，於指令加上 --image E:\fuxi_Backup-archive\workspace-20261118\candidates\vm-tools\ios16-root-build.img
  ```
- **主機測試**：無
- **驗證紀錄**：邊複製邊算 SHA-256、重讀目的檔比對相符後才刪 D: 原檔；搬完 `sha256sum -c SHA256SUMS` 全數通過。`ios16-root-build.img` SHA-256 `5fc67460bcbdc1de0a6a076daa8cfb01c47ecfc71c2a5760cb8ab5a7acaa2864`。
- **參考來源**：無
- **結論／未完成**：完成；同日另有早於 11-17 12:00 的舊核心／loader／暫存瘦身紀錄於 `D:\xiaomi13\fuxi_ios\work\cleanup-20261118-prune.tsv`。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md`、`E:\fuxi_Backup-archive\workspace-20261118\MANIFEST.tsv`。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-027 已刪除的舊手機差異 ios-root-phone-20261114～20261115h

- **日期**：2026-11-15（經使用者同意後刪除）
- **狀態**：已刪除
- **開關**：無
- **問題／現象**：舊的手機差分備份已被較新差異完整取代，為節省空間予以清理。
- **根因**：無（已由新差異取代）。
- **做法**：刪除 `ios-root-phone-20261114`、`20261114b`、`20261115`、`20261115b`～`20261115h`（合計約 17 GB）。
- **復現**：無（已刪除；現行同系列最新保留版為 `ios-root-phone-20261115q`）。
- **主機測試**：無
- **驗證紀錄**：`README.md` 註明每次拉回新差異後，舊的一份都已被新的完整取代。
- **參考來源**：無
- **結論／未完成**：已刪除清理。
- **出處**：`D:\xiaomi13\fuxi_Backup\README.md` L49。（2026-11-18 主代理分配範圍與來源，Gemini 依原始檔撰寫，主代理核對欄位、提交時間與路徑）

### R-028 a 槽倒數版升級前的整分區回退映像

- **日期**：2026-11-18 13:54:44–13:56:05（台北時間）
- **狀態**：回退映像在工作區，201,326,592 bytes，已核對 SHA-256。
- **開關**：由 launch-loader-check.ps1 的 -UpgradePersistent 流程產生。
- **問題／現象**：升級 Android 自動倒數版前，需保存可回到上一版常駐選單的完整 boot_a。
- **根因**：a 槽常駐選單與內嵌核心共用同一 boot 分區。回退以完整分區比對，需保留分區尾段。
- **做法**：安裝器核對上一版 boot_a，保存 boot-a-previous-menu.img；升級完成後讀回整分區並比對 expected_full_boot_a_sha256。目錄內另保留原廠 boot-a-original.img 與上一趟 mtd。
- **復現**：在工作區以 Get-FileHash -Algorithm SHA256 對 work/dualboot/persistent-slot-a-upgrade-countdown-20261118/boot-a-previous-menu.img 計算，對照 report.json 的 rollback_sha256。需要還原時依 B-004 與 dualboot/VALIDATION.zh-TW.md 的分區保護流程選擇映像。
- **主機測試**：2026-11-18 整檔 SHA-256 重算為 275dac0fdb0d5beb21e6a26de3126b10c8fbc514b47ce9c24fcdf66c1112b4b1，等於報告和上一版預期分區雜湊。
- **驗證紀錄**：安裝報告為 INSTALLED_ANDROID_VERIFIED。升級後 boot_a 的預期整分區 SHA-256 為 9b3b1bb14c085972620d93d3d2c1508c9b8d19a5adb463dd532371883b011cdd。
- **參考來源**：B-011 與 R-020。
- **結論／未完成**：保留回退映像、原廠映像和報告供復核；這次驗證讀回及 Android 自動交接。
- **出處**：work/dualboot/persistent-slot-a-upgrade-countdown-20261118/report.json、dualboot/install-persistent.py。
