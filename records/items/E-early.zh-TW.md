# E 系列：早期開機與環境（2026-11-07～11-14）

> 由 2026-11-18 的逐項盤點整合（原始紀錄：工作區根目錄 `boot_failure_and_fix_log.md`、`HANDOVER.md`、`CONTINUATION_20261108.md`、`README*.md`、`diagnostics/`、`scripts/`、`work/hardware-reference-survey-20261114.zh-TW.md` 等，逐項見「出處」）。這一時期大多沒有獨立的 commit，日期多半只到日；「來源未記」表示原始紀錄沒有寫。

## 開機嘗試 1–29（xnu-12377／iOS 27 路線，2026-11-07～08）

### E-001 Boot 1：`bootseed_init` 256 位元組隨機種子不足

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：改用 `tools/mkadt-fuxi27.py` 產生 256 位元組隨機種子，通過 `bootseed_init`
- **開關**：`fuxi`
- **問題／現象**：在小米 13（`fuxi`）上以 `fastboot boot` 透過 RAM 啟動 `xnu-12377`，於 `bootseed_init` 階段發生 panic：`panic: Expected 256 seed bytes from bootloader, but got 64`。
- **根因**：`xnu-12377` 需要 4 個 SHA-512 長度之隨機種子字組（共 256 位元組）；舊版 ADT 產生器僅提供 64 位元組。
- **做法**：改用 `tools/mkadt-fuxi27.py` 產生 256 位元組熵種子寫入 ADT。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：通過 `bootseed_init` 階段，推進至下一階段（Boot 2）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L11`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-002 Boot 2：`kern_trustcache` 缺少 `AppleImage4` 介面

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：編寫 `tools/ios27-prelink.py` 預連結 39 個官方 kext，通過 `kern_trustcache`
- **開關**：無
- **問題／現象**：核心在 `kern_trustcache` 階段 panic：`panic: image4 interface not available @kern_trustcache.c:592`。
- **根因**：TrustCache 初始化依賴蘋果閉源 `AppleImage4` kext 提供的 Image4 解析介面，但當時未預連結進核心。
- **做法**：編寫 `tools/ios27-prelink.py` 從官方 release kernelcache 提取並預連結 39 個官方 Apple kext。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：通過 `kern_trustcache` 初始化階段，推進至 `FuxiRoot27`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L12`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-003 Boot 3：`FuxiRoot27` 遭 Android `dm-default-key` 加密

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：改用 `FIEMAP` 實體 extent 寫入工具 `scratch/stream_extents_dev` 寫入明文
- **開關**：無
- **問題／現象**：`FuxiRoot27` 驗證 UFS 儲存裝置前 4,096 位元組的 manifest 雜湊時失敗：`FUXI ROOT27: manifest hash mismatch`（讀到看似隨機的雜湊）。
- **根因**：小米 13 的 `fstab` 啟用 `metadata_encryption=aes-256-xts:wrappedkey_v0`，經 Android `/data/` 邏輯卷（`dm-8`）寫入會經過高通 Inline Crypto Engine（ICE）硬體加密；XNU 的 UFS SCSI 驅動直接對實體磁區發起 DMA 讀取，讀到未解密的密文。
- **做法**：查詢 `/dev/block/sda32` 上目標檔案的 F2FS 實體 extent（`FIEMAP`），並建立原生寫入工具 `scratch/stream_extents_dev` 直接對映射後的實體 UFS 磁區寫入明文。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 4–5 發現寫入時若 Android/TWRP 仍掛載，快取／加密仍會干擾。
- **參考來源**：TWRP（出現在本項內文，細節見出處）
- **結論／未完成**：被 E-004（TCP 9999 原始串流與逐塊驗證）取代。
- **出處**：`boot_failure_and_fix_log.md:L13,L42-L48`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-004 Boot 4–5：TWRP 區塊快取／內聯加密導致磁區雜湊不符

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：改用 TCP 9999 原始 extent 串流寫入與逐塊 SHA-256 驗證，extent 0 100% 吻合
- **開關**：無
- **問題／現象**：Boot 4–5 仍出現 `FUXI ROOT27: manifest hash mismatch`。
- **根因**：Android 或 TWRP 活動期間寫入時，區塊快取或內聯加密干擾導致實體磁區未完整刷出明文。
- **做法**：改用 TCP port 9999 原始 extent 串流寫入器，並搭配逐塊 SHA-256 驗證（在 `userdata` 卸載狀態下直接寫 `/dev/block/sda32`）。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：確認 extent 0 雜湊（`efd0e91a...`）與主機映像 100% 吻合，通過 `FuxiRoot27` 驗證。
- **參考來源**：TWRP（出現在本項內文，細節見出處）
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L14,L42-L48`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-005 Boot 6：`bsd_init` 根卷未認證 panic

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：加入開機參數 `fuxi_root27_norootauth=1` 略過根卷認證
- **開關**：`fuxi_root27_norootauth=1`
- **問題／現象**：掛載 APFS 根卷 `disk0s1` 後於 `bsd_init` 階段 panic：`panic: rootvp not authenticated after mounting @bsd_init.c:972`。
- **根因**：從 IPSW 解包重組的 root 映像缺乏 Apple seal 簽章，無法通過 `FSIOC_KERNEL_ROOTAUTH`。
- **做法**：於核心開機參數加入 `fuxi_root27_norootauth=1` 略過根卷認證。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：通過 `bsd_init` 根卷認證檢查，進入 `load_init_program`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L15`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-006 Boot 7：閉源 APFS kext `struct upl` ABI 不相容

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：以 `--drop-apfs` 移除閉源 APFS，改用內建唯讀 Dada-APFS（Patch 0008）
- **開關**：無
- **問題／現象**：執行 `/sbin/launchd` 之 `load_init_program` 時 panic：`panic: Kernel data abort. at pc 0xfffffff00afbc080`（`upl_page_present(pl, 0x7fff)`），`lr 0xfffffff00afbc070`、`far: 0x0fffffff00055f9a`。
- **根因**：來自 iOS 16/17 kernelcache 的預編譯閉源 `com.apple.filesystems.apfs` kext 在 `vnop_read` 呼叫 `upl_page_present(pl, page)` 時，`struct upl` 欄位偏移與開源 `xnu-12377` 不一致，導致解參考無效位址 `0x0fffffff00055f9a`。
- **做法**：於 `tools/ios27-prelink.py` 傳入 `--drop-apfs` 排除閉源 APFS kext，並啟用 XNU 內建唯讀 APFS 模組（Patch 0008、`hakios-arm64e-dada` / Dada-APFS）提供 `apfs_vfsops`／`apfs_vnops`。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：消除 UPL ABI 衝突，無 `Kernel data abort`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L16,L51-L64`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-007 Boot 8：`IOFindBSDRoot` 根裝置 UUID 不匹配

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`fuxi27-root.adt` 改用 `--root-uuid 2ABE836E-EB6D-4C24-B639-FDEDDD5154B2`
- **開關**：無
- **問題／現象**：`IOFindBSDRoot` 無限等待超時：`Waiting on <dict ID="0"><key>IOProviderClass</key><string ID="1">IOMedia</string><key>IOPropertyMatch</key><dict ID="2"><key>UUID</key><string ID="3">DADD93F8-DBBF-4B17-A1DF-0F11E64172F7</string></dict></dict>`。
- **根因**：移除閉源 APFS kext 後，不再合成帶有卷 UUID `DADD93F8...` 的 APFS 子卷 `IOMedia` 節點；在 Dada-APFS 下，`FuxiRoot27` 直接以 OS 視窗的 SHA-256 衍生 UUID `2ABE836E-EB6D-4C24-B639-FDEDDD5154B2` 暴露 `disk0`，而 ADT 的 `/chosen/root-matching` 仍指定 `DADD93F8...`。
- **做法**：產生 `fuxi27-root.adt` 時傳入 `--root-uuid 2ABE836E-EB6D-4C24-B639-FDEDDD5154B2`，使 `IOFindBSDRoot` 直接匹配 `disk0`。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：成功匹配根裝置並掛載 APFS 與 Cryptex 卷。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L17,L67-L79`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-008 Boot 9：AMFI CoreTrust 拒絕未註冊之 `/sbin/launchd`

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：合併 3 個官方 TrustCache（2,851 筆）至 `ios27.tc` 並以 `--trustcache` 打包
- **開關**：無
- **問題／現象**：Dada-APFS 成功掛載 OS（`142313 files`）、`SystemOS` (`disk2s1`) 與 `AppOS` (`disk1s1`) 並載入頁面後，AMFI 拒絕簽章並殺死 PID 1：`AMFI: '/sbin/launchd': unsuitable CT policy 0 for this platform/device, rejecting signature.`、`AMFI: '/usr/lib/dyld': unsuitable CT policy 0...`、`panic(cpu 0 caller ...): unexpected SIGKILL of launchd`。
- **根因**：Boot 9 執行 `mkpayload.py` 時未傳入 `--trustcache`，導致 `no external trust caches found`，核心執行檔未註冊於外部或靜態 TrustCache。
- **做法**：從韌體提取 3 份官方 TrustCache（`087-86698-044.dmg.trustcache` 2,760 筆、`087-86593-047.dmg.trustcache` 61 筆、`087-86715-047.dmg.trustcache` 30 筆），以 `tools/ios27-root.py trust-bundle` 合併共 2,851 筆為 `resources/ios27.tc`，打包 `payload27-dada.bin` 時傳入 `--trustcache <WORKSPACE>/resources/ios27.tc`。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：成功通過 AMFI 簽章檢查並啟動 `/sbin/launchd`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L18,L82-L104`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-009 Boot 10：進入 `launchd` 使用者態後因無 `rd=md0` 觸發 `EXC_GUARD`

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：加入 `fuxi_launchd_ramdisk=1` 與 `fuxi_proc_log=1`
- **開關**：`rd=md0`、`fuxi_launchd_ramdisk=1`、`fuxi_proc_log=1`
- **問題／現象**：首次進入 iOS 17 `/sbin/launchd` 並印出 `"hello"` 與 `Darwin Bootstrapper Version 7.0.0`，但隨即遭強制終止：`ERROR: [launchd:1] EXC_GUARD AST: type=0x1 flavor=0x43 target=0x800407 code=0x2000004300800407 subcode=0x300000000000011` -> `FATAL exception: type=0xc reason=0x17` -> `pid 1 exited -- exit reason namespace 23 subcode 0x2000004300800407`。
- **根因**：`launchd` 查詢 `sysctlbyname("kern.bootargs")` 未見 `rd=md0`，因而嘗試執行完整硬體開機流程（`fsck`/SEP/container 檢查），碰到缺失的 IOKit container 物件並觸發 `EXC_GUARD`。
- **做法**：於核心命令列加入 `fuxi_launchd_ramdisk=1`（Patch 0018，在使用者態查詢 `kern.bootargs` 時附加 ` rd=md0`）與 `fuxi_proc_log=1` 記錄進程退出堆疊。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 11 順利載入全部 43 個 `dyld_shared_cache` 分片並印出 `Restore environment starting.`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L19,L107-L125`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-010 Boot 11：43 個 dyld 快取掛載完成後遇嚴格回覆埠例外

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：加入 `task_exc_guard_default=0`
- **開關**：無
- **問題／現象**：全部 43 個 `dyld_shared_cache` 分片透過 `fcntl(cmd 97)` 註冊成功且 `launchd` 印出 `Restore environment starting.` 後，仍被 `EXC_GUARD AST: type=0x1 flavor=0x43 (kGUARD_EXC_STRICT_REPLY)` 殺死（`panic: initproc exited -- exit reason namespace 23 subcode 0x2000004300800407`）。
- **根因**：`DEVELOPMENT` 核心預設將 `task_exc_guard_default` 設為嚴格 Mach 回覆埠保護（`kGUARD_EXC_STRICT_REPLY` `0x40` | `kGUARD_EXC_MOD_REFS` `0x02` | `kGUARD_EXC_DESTROY` `0x01`）。
- **做法**：於核心命令列加入 `task_exc_guard_default=0`。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：進入 Boot 12 調度階段（仍遇 Policy 7 繞過 `task_exc_guard_default=0` 的情形，見 E-012）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，部分解決（需配合 E-012）。
- **出處**：`boot_failure_and_fix_log.md:L20,L128-L147`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-011 Boot 12：`cpus=7` 下跨核心 `SIGP` 斷言 panic

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：改為單核 `cpus=1`（ADT `--cpus 1`），核心 0 跑 XNU、`cpu@100` 跑 USB 探針
- **開關**：`cpus=7`、`cpus=1`
- **問題／現象**：`launchd` 調度期間於 CPU 5 觸發 panic：`panic(cpu 5 caller 0xfffffff00b5a2878): cpu_common.c:946 Assertion failed: getCpuDatap()->cpu_signal == SIGPdisabled (0x8 == 0x80000000, 8 == 2147483648)`。
- **根因**：在 `cpus=7` 多核設定下，SM8550 的 GICv3 distributor 在喚醒／同步次要核心時偶發遺失 IPI 訊號，導致 CPU 5 的 `cpu_signal` 狀態不一致。
- **做法**：依 `docs-lanes/ios27.md` 改為單核開機（`fuxi27-root.adt` 使用 `--cpus 1`，命令列設定 `cpus=1`），保留核心 0 給 XNU、`cpu@100` 給 USB 監看探針。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：消除跨核心 `SIGP` panic。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L21,L150-L160`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-012 Boot 13：Mach 埠安全策略 Policy 7 殺死 `launchd`

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`patch_kernel_guard.py` 關閉 `_ool_port_array_enforced` 並放行 `_mach_port_guard_ast`
- **開關**：無
- **問題／現象**：`launchd` 於 `Restore environment starting.` 後再次被 `EXC_GUARD AST: type=0x1 flavor=0x43 code=0x2000004300800407` 殺死。
- **根因**：反組譯 iOS 17 `/sbin/launchd` 發現其呼叫 `_mach_ports_register` 並以 disposition `0x11`（`MACH_MSG_TYPE_MOVE_SEND`）建立 XPC send port；XNU `_ipc_sec_policy_array` 之 Policy 7（`IPC_POLICY_OOL_PORT_ARRAY`）檢查 `_ool_port_array_enforced`（`DEVELOPMENT` 預設為 `1`）並要求 `COPY_SEND`（`0x13`），且 `_mach_port_guard_ast` 對 `flavor <= 0x80` 繞過 `task_exc_guard_default=0` 直接發送 `SIGKILL`。
- **做法**：建立 `scripts/patch_kernel_guard.py`：
  1. 將 `_ool_port_array_enforced`（偏移 `0xde119b`）由 `0x01` 改為 `0x00`；
  2. 將 Policy 7（`0xde19f0`）與 Policy 4（`0xde19a8`）動作由 `0x03` 改為 `0x01`（忽略）；
  3. 將 `_mach_port_guard_ast`（偏移 `0x3cac900`）之 `b.hi +0x28` 改為無條件 `b +0x28`；
  4. 更新 `kernel.json` SHA-256 並於命令列加入 `ool_port_array_enforced=0 enforce_strict_reply=0 sheng-no-lc=1`。
- **復現**：  ```sh
  python scripts/patch_kernel_guard.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 14 完全消除 `EXC_GUARD`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L22,L163-L185`; `scripts/patch_kernel_guard.py:L1-L50`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-013 Boot 14：`could not set up inheritance port`（naked-send 檢查）

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`patch_kernel_inheritance.py` 放行 `ipc_can_stash_naked_send`（Boot 15 發現仍缺 MIG 檢查）
- **開關**：無
- **問題／現象**：`EXC_GUARD` 消失，但 `launchd` 主動中止：`fuxi: sig 6 pid 1 pc 0x1eee4a8c0 lr 0x1eee6bb48` -> `fuxi: exit pid 1 launchd status 0x6 ns 7 code 0x1 could not set up inheritance port`。
- **根因**：`launchd` 於 `0x100016e14` 呼叫 `_mach_ports_register(mach_task_self(), &inheritance_port, 1)`，核心 `_kernelrpc_mach_ports_register3`（`0xfffffff00ace2954`）呼叫 `ipc_can_stash_naked_send`（`0xfffffff00acb0490`）回傳 `0`，導致回傳 `0x11`（`KERN_POLICY_LIMIT`）。
- **做法**：建立 `scripts/patch_kernel_inheritance.py`，將 `ipc_can_stash_naked_send`（偏移 `0x3cac490`）改寫為 `pacibsp; mov w0, #1; retab; nop`，並將 `_kernelrpc_mach_ports_register3` 內拒絕分支（`0x3cde98c`、`0x3cde998`、`0x3cde9a4`、`0x3cde9b4`）NOP 化。
- **復現**：  ```sh
  python scripts/patch_kernel_inheritance.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 15 仍出現同一錯誤訊息，進一步追查發現卡在 MIG demux（見 E-014）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用（與 E-014 搭配）。
- **出處**：`boot_failure_and_fix_log.md:L23,L188-L223`; `scripts/patch_kernel_inheritance.py:L1-L40`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-014 Boot 15：MIG demux `MIG_BAD_ARGUMENTS` (-304)

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：繞過 `__X_kernelrpc_mach_ports_register3` demux 檢查，強制回傳 `KERN_SUCCESS`
- **開關**：無
- **問題／現象**：Boot 15 `launchd` 仍回報 `could not set up inheritance port`（`sig 6 pid 1 pc 0x1de9328c0 lr 0x1de953b48 slide 0x1c314000`）。
- **根因**：XNU 未啟用 `LIBSYSCALL_INTERFACE` 編譯，導致 MIG server demux `__X_kernelrpc_mach_ports_register3`（`0xfffffff00adb1204`，檔案偏移 `0x3dad204`）要求 3 個 inline descriptor（`count == 3`、`msgh_size == 0x54`）；但 iOS 17 `libsystem_kernel.dylib` 傳送 1 個 OOL 埠陣列（`type = 2, count = 1`），demux 直接回傳 `-304`（`MIG_BAD_ARGUMENTS`）。
- **做法**：於 `__X_kernelrpc_mach_ports_register3` 入口（`0x3dad214`）改為無條件跳轉至 epilogue（`b #0xfffffff00adb12ac`，`26000014`），並於 `0x3dad2ac`、`0x3dad2d4` 強制 `mov w8, #0`（`RetCode = KERN_SUCCESS`）。
- **復現**：併入 `scripts/patch_kernel_inheritance.py` 重建 Boot 16 映像。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 16 PID 1 成功通過並進入 `dispatch_main`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：暫時繞過（後於 Boot 19 由 E-018 完整重寫取代）。
- **出處**：`boot_failure_and_fix_log.md:L24,L226-L251`; `scripts/patch_kernel_inheritance.py:L35-L41`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-015 Boot 16：`launchd` 進入 `dispatch_main`，子進程 `xpcproxy` 遇 `SIGTRAP`

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：於 `psignal_internal` 注入使用者態回溯列印以定位子進程崩潰點
- **開關**：`fuxi_user_backtrace`
- **問題／現象**：歷史性突破：PID 1 完成初始化並進入 `dispatch_main`，生成 `SpringBoard`（PID 5）等服務，但子進程 `xpcproxy` 立即因 `fuxi: exit pid ... xpcproxy status 0x5 ns 2 code 0x5`（`SIGTRAP`）退出，且無使用者態堆疊資訊。
- **根因**：當時尚無使用者態回溯列印（後於 Boot 17 查明為 `mach_ports_lookup()` 失敗）。
- **做法**：以 `scripts/patch_kernel_boot17.py` 於核心 `postsig_locked`（`0x4253d58`）NOP 化 `cmp w0, #1; b.ne`，使所有進程崩潰皆列印 `fuxi_user_backtrace`（PC、LR、FP、return chain）；同時讓 `_setsid`、`_spawn_validate_persona`、`_spawn_persona_adopt` 回傳 0。
- **復現**：  ```sh
  python scripts/patch_kernel_boot17.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 17 成功印出 `xpcproxy` 崩潰位置與呼叫鏈。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決診斷問題。
- **出處**：`boot_failure_and_fix_log.md:L25`; `scripts/patch_kernel_boot17.py:L21-L41`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-016 Boot 17：`mach_ports_lookup()` OOL 回覆長度不匹配

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`patch_kernel_lookup.py` 重寫 `_X_kernelrpc_mach_ports_lookup3` 輸出 OOL 埠陣列
- **開關**：無
- **問題／現象**：子進程 `libxpc_initializer` 觸發 `SIGTRAP`：`"Kernel bug: mach_ports_lookup() failed."`。
- **根因**：使用者態 `mach_ports_lookup()`（`msgh_id 3404`）僅提供 64 位元組接收緩衝區給 1 個 OOL 埠陣列（56 位元組回覆），而原生 `_X_kernelrpc_mach_ports_lookup3` 回傳 3 個 inline descriptor（84 位元組回覆），引發 `MACH_RCV_TOO_LARGE`（`0x10004004`）-> `__os_crash` -> `brk #1`。
- **做法**：撰寫 `scripts/patch_kernel_lookup.py` 重寫 `_X_kernelrpc_mach_ports_lookup3`（`0xfffffff00adb1368`，檔案偏移 `0x3dad368`，312 位元組），動態配置核心緩衝區、以 PAC 簽署指標並組裝 iOS 17 相容之 OOL 回覆訊息。
- **復現**：  ```sh
  python scripts/patch_kernel_lookup.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：`xpcproxy` `mach_ports_lookup()` 通過，推進至 Boot 18（生成 70+ 進程），但觸發堆積隔離 panic（見 E-017）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，並於 E-017 修正配置器型別。
- **出處**：`boot_failure_and_fix_log.md:L26`; `scripts/patch_kernel_lookup.py:L1-L50`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-017 Boot 18：核心堆積隔離混淆 panic (`kfree_heap_confusion_panic`)

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：改用 `kalloc_ext` 配對 `kalloc_type_view_3960` 並跳過 `kfree_zone` 檢查
- **開關**：無
- **問題／現象**：生成 70+ 進程（PID 2–70）後 panic：`panic(cpu 0 caller 0xfffffff00b5670c0): kfree: addr 0xfffffe8000456c60, size 24 found in heap data.kalloc.32 instead of default.kalloc.32 @kalloc.c:2783`。
- **根因**：Boot 17 的 OOL 回覆緩衝區使用 `kalloc_data(24, 0)`（屬於 `KHEAP_DATA_BUFFERS`）配置，但 `ipc_kmsg_copyout_descriptors` 釋放時透過 `kfree_ext` 預期其屬於 `ipc_kmsg_copyout_ool_ports_descriptor.kalloc_type_view_3960 | 1`（`KHEAP_DEFAULT`）。
- **做法**：  1. 更新 `scripts/patch_kernel_lookup.py` 改用 `kalloc_ext(ipc_kmsg_copyout_ool_ports_descriptor.kalloc_type_view_3960 | 1, 24, 0, 0)` 配置；
  2. 將 `kfree_zone` 堆積檢查（`0x3ce38e4` / `0xfffffff00ace78e4`）由 `b.eq +0x18` 改為無條件 `b +0x18`（`0x14000006`）。
- **復現**：  ```sh
  python scripts/patch_kernel_lookup.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 19 達成 1.19 MB 主控台輸出且零核心 panic。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L27,L254-L265`; `scripts/patch_kernel_lookup.py:L22-L28`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-018 Boot 19：子進程因 `Invalid bootstrap port` 遇 `SIGTRAP`

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`patch_kernel_register.py` 完整解包並呼叫 `_kernelrpc_mach_ports_register3`
- **開關**：無
- **問題／現象**：零核心 panic 並生成 300+ 進程，但子進程 `xpcproxy`（PID 300）載入 `dyld` 後遇 `SIGTRAP`：`fuxi: sig 5 pid 300 pc 0x1fca598ec lr 0x1fca41080 ... slide 0x2ae48000`、`xpcproxy exited due to SIGTRAP | sent by exc handler[300]`。
- **根因**：未滑移 PC `0x1d1c118ec`（`brk #1`）對應 `dyld_shared_cache_arm64.25` 內 `libxpc` 之 `"Configuration error: Invalid bootstrap port."`。因 Boot 16 直接跳過 `__X_kernelrpc_mach_ports_register3` 而未呼叫實作，導致 `launchd->itk_registered[0]` 維持 `NULL`，子進程繼承 `ports[0] = 0`。
- **做法**：撰寫 `scripts/patch_kernel_register.py` 完整替換 `__X_kernelrpc_mach_ports_register3`（`0xfffffff00adb1204`，312B 填充至 356B）：解包 OOL 埠陣列描述符、PAC 認證緩衝區（key `0x25da`）與埠指標（key `0x362f`）、呼叫原生 `_kernelrpc_mach_ports_register3`、將描述符 `count` 清零以保留 send rights、呼叫 `task_deallocate_grp(target_task, 2)` 並回傳標準 MIG 回覆（`RetCode = 0`、`msgh_size = 0x2c`）。
- **復現**：  ```sh
  python scripts/patch_kernel_register.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 20 發現硬編碼 `count == 3` 需調整（見 E-019）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用（經 E-019 修正後生效）。
- **出處**：`boot_failure_and_fix_log.md:L28,L268-L294`; `scripts/patch_kernel_register.py:L1-L50`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-019 Boot 20：`patch_kernel_register.py` 硬編碼 `count == 3` 導致 `launchd` 失敗

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：改為接受動態計數 `0 <= count <= 3`
- **開關**：無
- **問題／現象**：Boot 20 `launchd` 再次於 `0x100016e04` 失敗：`fuxi: exit pid 1 launchd status 0x6 ns 7 code 0x1 could not set up inheritance port`。
- **根因**：`launchd` 傳入 `count = 1`，而初版 `patch_kernel_register.py` 嚴格檢查 `cmp w11, #3; b.ne Lbad_args`，回傳 `-304`（`MIG_BAD_ARGUMENTS`）。
- **做法**：更新 `scripts/patch_kernel_register.py` 接受 `0 <= count <= 3`（`cmp w11, #3; b.hi Lbad_args`），於堆疊預置 3 個 `NULL` 槽位並依實際 `count` 迴圈解包。
- **復現**：  ```sh
  python scripts/patch_kernel_register.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 21 所有 `xpcproxy` 以 `status 0x0` 正常退出，各服務二進位成功 `exec`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L29,L297-L309`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-020 Boot 21：`SpringBoard` 缺 `/usr/lib/libobjc-trampolines.dylib` 崩潰

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`patch_kernel_trampoline.py` 攔截 `lookup_check_for_resolve_prefix` 導向 Cryptex
- **開關**：無
- **問題／現象**：`launchd` 進入 `dispatch_main` 並啟動 `SpringBoard`（PID 128）、`sleepd`（132）、`mDNSResponder`（134），但所有 ObjC 進程均中止：`couldn't dlopen libobjc-trampolines.dylib: dlopen(/usr/lib/libobjc-trampolines.dylib, 0x0106): tried: '/usr/lib/libobjc-trampolines.dylib' (no such file, not in dyld cache)`。
- **根因**：`libobjc-trampolines.dylib` 與 `libffi-trampolines.dylib` 位於 SystemOS Cryptex（`/private/preboot/Cryptexes/OS/usr/lib/`）。在 `dyld_flags=8` 下，`dyld` 直接開啟 `/usr/lib/...` 且根目錄無符號連結，回傳 `ENOENT`。
- **做法**：確認 `resources/ios27.tc` 含兩者之 CDHash（`67c97863...`、`f66d0b31...`），並撰寫 `scripts/patch_kernel_trampoline.py` Hook `lookup_check_for_resolve_prefix`（`0xfffffff00af614e0`），於記憶體內原地將該兩路徑改寫為 `/private/preboot/Cryptexes/OS/usr/lib/...`。
- **復現**：  ```sh
  python scripts/patch_kernel_trampoline.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 22 成功載入 trampoline，`SpringBoard` 進入 `running` 狀態。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L30,L312-L332`; `scripts/patch_kernel_trampoline.py:L1-L50`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-021 Boot 22：`SpringBoard` 首次穩定啟動，約 90 秒觸發 watchdog 重開

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：實驗：定位 90 秒重開來自未傳 `--reset-minutes 30`；分類出 `logd`/`backboardd` 等崩潰
- **開關**：無
- **問題／現象**：`SpringBoard`（PID 5）進入 `service state: running` 且零崩潰（同時運行 `CommCenter`、`mobiletimerd`、`coresymbolicationd`、`bluetoothd`），但裝置於 ~85–90 秒後自動重開進入 Fastboot／充電；另觀察到 `logd`（`SIGTRAP` `0x100b25160`）、`contextstored`/`donotdisturbd`（`SIGTRAP` `0x1ae4068c0`）、`backboardd`（`SIGABRT` `0x1c2617198`）崩潰。
- **根因**：  1. 90 秒重開：`ios-fuxi/shim/fuxi-probe/probe.c:1472` 將 `MON_DEADLINE` 初始化為 90 秒，而 `scripts/do_boot.py` 未傳 `--reset-minutes 30`（命令 `0x54`），到期後呼叫 PSCI `reboot()`；
  2. `logd`：檢查 `/private/var/db/diagnostics` 與 `uuidtext` 預期 `uid=272, gid=272, mode=0751` 與 `.migrated`，在唯讀根卷遇到 `EROFS`（30）觸發 `"BUG IN LIBTRACE: Failed to migrate directory"`；
  3. `contextstored`/`donotdisturbd`：缺乏 SEP `AppleKeyStore` 與 `/private/var/keybags/systembag.kb` 導致 `MKBEventsRegister` 失敗；
  4. `backboardd`：缺 `CADisplay`/`IOMobileFramebuffer` 導致 `addGlobalDevicePreferencesObserver:` 拋出未捕獲例外。
- **做法**：於 `scripts/do_boot.py` 加入 `--reset-minutes 30`，並規劃針對 `logd` 與 `/private/var` 的 VFS 路徑／屬性偽裝。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：於 Boot 23 驗證 `--reset-minutes 30`（見 E-022）。
- **參考來源**：ios-fuxi（出現在本項內文，細節見出處）
- **結論／未完成**：採用，90 秒重開問題已解決；daemon 崩潰繼續分析。
- **出處**：`boot_failure_and_fix_log.md:L31,L335-L345`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-022 Boot 23：突破 90 秒限制跑滿 300 秒，產生 431 進程與 6 代 `SpringBoard`

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：實驗：無重開完成 300 秒並擷取 `1080x2400` 主控台畫面；統計 10 種 daemon 崩潰
- **開關**：無
- **問題／現象**：驗證延長 watchdog 後之系統穩定度並統計所有背景服務崩潰分類。
- **根因**：`backboardd` 崩潰斷線導致 `SpringBoard` 以 `status 0xffffff00`（exit 255）跟隨退出。
- **做法**：使用含 `--reset-minutes 30` 之 `scripts/do_boot.py`（每 60 秒發送 `0x54` 續命封包）執行完整 300 秒監看。
- **復現**：  ```sh
  python scripts/do_boot.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：  - 跑滿 300 秒零重開，共生成 **431 個進程（最大 PID 432）**，`SpringBoard` 歷經 6 代（PIDs `5, 144, 200, 258, 325, 384`）皆達 `running`；
  - `runningboardd` (6)、`powerd` (19)、`mobiletimerd` (27)、`sleepd` (49)、`passd` (53)、`chronod`、`cloudkeychainproxy3` (98) 穩定運行；
  - 擷取 `resources/boot23-logs/framebuffer.png` 與 `framebuffer.bgra`（9.9 MB，1080x2400，驗證 4,165 個文字像素）；
  - 崩潰統計：`locationd` (61, `SIGABRT`)、`mediaserverd` (48, `SIGKILL`)、`donotdisturbd` (25, `SIGTRAP`)、`contextstored` (25, `SIGTRAP`)、`UserEventAgent` (23, `SIGTRAP`)、`backboardd` (11, `SIGABRT`)、`ACCHWComponentAuthService` (11, `SIGKILL`)、`lockdownd` (3, `SIGTRAP`)、`lsd` (2, `SIGABRT`)、`logd` (1, `SIGTRAP`)。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，取得完整 300 秒基準線。
- **出處**：`boot_failure_and_fix_log.md:L32,L348-L369`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-023 Boot 24：`runningboardd` 存活 300 秒，總退出下降 51%

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`patch_kernel_boot24.py` 抑制 `EXC_GUARD`（`logd`/`backboardd` 尚待續修）
- **開關**：無
- **問題／現象**：減少 `EXC_GUARD` 造成的服務重啟，並嘗試讓 `logd` 與 `backboardd` 存活。
- **根因**：實機 APFS 上 `/private/var/db/diagnostics` 屬主為 `uid=0, gid=0`（非 `501`）、缺少 `timesync`/`uuidtext`/`.migrated`，且 `stat()` 呼叫的是 `_lookup` 而非 `lookup_check_for_resolve_prefix`；另 `p->p_comm` 偏移 `0x5d4` 僅 4 位元組對齊，且 `backboardd` 走 Mach 例外結束路徑。
- **做法**：執行 `scripts/patch_kernel_boot24.py`，Hook `_lookup_check_for_resolve_prefix`、`_vn_stat_noauth`（`0xfffffff00af909e4`）、`postsig_locked`（`0xfffffff00b257d8c`），並以 `patch_kernel_guard_ast.py` 將 `_PROC_VIOLATED_GUARD__SEND_EXC_GUARD`（`0xfffffff00ad3046c`）替換為 `pacibsp; mov w0, #0; retab; nop`。
- **復現**：  ```sh
  python scripts/patch_kernel_boot24.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：跑滿 300 秒，總進程退出自 431 降至 212（-51%）；`runningboardd`（PID 5）300 秒零崩潰；`SpringBoard` 仍隨 `backboardd` 退出 6 次；擷取 `resources/boot24-logs/framebuffer.png`（118 KB）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用 `EXC_GUARD` 抑制補丁；`logd`／`backboardd` 於 Boot 25 續修。
- **出處**：`boot_failure_and_fix_log.md:L33,L372-L386`; `scripts/patch_kernel_boot24.py:L1-L60`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-024 Boot 25：`logd` 存活 285 秒零崩潰，定位 `backboardd` 真正退出路徑

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`_hook_namei`＋`_hook_vn_stat` 修好 `logd`；定位 `_exit_with_reason` 尾呼叫
- **開關**：無
- **問題／現象**：解決 `logd` 崩潰並找出 `backboardd` 繞過 `postsig_locked` 的原因。
- **根因**：`backboardd` 在 GCD worker 內呼叫 `abort()` -> `__pthread_kill`，經 `ux_exception` -> `_exit_with_fatal_exception_and_notify` -> `_exit_with_mach_exception`（`0xfffffff00b23b3a8`）直接尾呼叫（`b 0xfffffff00b238664`）`_exit_with_reason`，完全繞過 `postsig_locked`。
- **做法**：執行 `scripts/patch_kernel_boot25.py`：於 `0xfffffff00af60018`（`_hook_namei`）原地截斷 `.migrated`/`timesync`/`uuidtext` 至 `"."`；於 `0xfffffff00af909e4`（`_hook_vn_stat`）為 `logd` 偽裝 `st_uid=272, st_gid=272, mode=0751/0755`；保留 `postsig_locked` 與 `_PROC_VIOLATED_GUARD__SEND_EXC_GUARD` 補丁。
- **復現**：  ```sh
  python scripts/patch_kernel_boot25.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：`logd`（PID 72）進入 `running` 並存活餘下 285 秒零崩潰；`runningboardd`（PID 6）吸收 23 次 `EXC_GUARD AST` 並存活 300 秒；擷取 `resources/boot25-logs/framebuffer.png`（124 KB）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用 `logd` 虛擬化；`backboardd` 改由 Boot 26 攔截 `_exit_with_reason`。
- **出處**：`boot_failure_and_fix_log.md:L34,L389-L402`; `scripts/patch_kernel_boot25.py:L1-L60`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-025 Boot 26：`_hook_exit_with_reason` 誤呼叫 `proc_unlock` 導致 Mutex panic

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：移除誤呼叫之 `proc_unlock`，改為無鎖呼叫 `_thread_terminate_self()`
- **開關**：無
- **問題／現象**：攔截 `backboardd`/`logd` 崩潰執行緒使其僅終止單一執行緒，保持主進程存活，但啟動時立即 panic：`panic(cpu 0 caller 0xfffffff00b567b8c): Mutex 0xfffffff880036058 is unexpectedly not owned by thread 0xfffffff799a64d20 @lock_mtx.c:148`。
- **根因**：`scripts/patch_kernel_boot26.py` Hook `_exit_with_reason`（`0xfffffff00b238664`）時，誤將第 5 參數 `w4`（`rwlock_held`）當成 `p->p_mlock` 持有旗標；在函式入口處 `proc_lock(p)` 尚未取得（要到 `0xfffffff00b2386f8` 才上鎖），呼叫 `proc_unlock(p)` 觸發 `@lock_mtx.c:148`。
- **做法**：於 Boot 27 移除 `L_intercept_thread` 內之 `proc_unlock`，改為印出 `kprintf("fuxi: intercepted thread exit in %s\n", p->p_comm)` 後直接無鎖呼叫 `_thread_terminate_self()`（`0xfffffff00ad3b028`）。
- **復現**：  ```sh
  python scripts/patch_kernel_boot26.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：驗證 `_hook_exit_with_reason` 確實於 `logd`（PID 69）觸發 `sig 5` 時命中；無鎖修正見 Boot 27/28。
- **參考來源**：原始紀錄未列
- **結論／未完成**：停損修正，由 E-026 接續完成。
- **出處**：`boot_failure_and_fix_log.md:L35,L405-L419`; `scripts/patch_kernel_boot26.py:L1-L60`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-026 Boot 27：`_hook_lookup_prefix` 誤將 `flags` (`0x100`) 當指標解參考

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：修復：`patch_kernel_boot28.py` 恢復經驗證之 `_hook_lookup_prefix` 實作
- **開關**：無
- **問題／現象**：Boot 27 啟動立即發生資料中止 panic：`panic(cpu 0 caller 0xfffffff00b5a2878): Kernel data abort. at pc 0xfffffff00b62da0c, lr 0x59e982f00af60334 ... x0: 0xfffffff3979d5648 x1: 0x0000000000000100 ... far: 0x0000000000000100`。
- **根因**：`scripts/patch_kernel_boot27.py` 重構 `_hook_lookup_prefix` 時，誤將 `x1`（實為 `flags = 0x100 = CN_RESOLVE_PREFIX`，而非指標）執行 `ldr x2, [x1]` 導致存取 `0x100` 失敗。
- **做法**：撰寫 `scripts/patch_kernel_boot28.py`，還原經 `patch_kernel_trampoline.py` 驗證之 `_hook_lookup_prefix`（從 `x0` 比對前綴、設 `*flagsp = 0x80000000`、`*prefixlenp = 0`），同時保留 Boot 27 之無鎖 `_hook_exit_with_reason`（`candidate_sha256` `4201199c...`）。
- **復現**：  ```sh
  python scripts/patch_kernel_boot28.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：Boot 28 零 panic 跑滿 300 秒（見 E-027）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`boot_failure_and_fix_log.md:L36,L422-L433`; `scripts/patch_kernel_boot27.py:L54-L60`; `scripts/patch_kernel_boot28.py:L1-L50`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-027 Boot 28：300 秒零 panic、`SpringBoard`/`backboardd` 存活，診斷無畫面原因

- **日期**：2026-11-07/08（來源未記確切時分）
- **狀態**：結論：確認因 ADT 缺 `/arm-io/disp0` 強制 `BKDisplayIsHeadless=true`
- **開關**：無
- **問題／現象**：完成 300 秒開機並診斷實體螢幕仍顯示核心文字而無 iOS UI 之原因。
- **根因**：  1. **Headless 模式**：`backboardd` 透過 `IOMobileFramebuffer` 列舉 `/arm-io` 下 `device_type == "display-subsystem"`；`mkadt-fuxi27.py` 僅建立 `intc` 而漏建 `/arm-io/disp0`，迫使 `BKDisplayIsHeadless = true`；
  2. **主控台覆寫**：開機參數 `-v` 持續佔用 `0xb8000000` 主控台，且缺 `ios27.tc` 造成 `mediaserverd` 每 5 秒被 AMFI 拒絕（`0x8`）；
  3. **缺少 ADT 屬性**：`/arm-io/wdt` 缺 `no-pmu: 1`、`/device-tree/buttons` 缺 `home-button-type: 2`、`/device-tree/defaults` 缺 `no-effaceable-storage: 1`。
- **做法**：彙整缺口並於 Boot 29（E-028）補齊 ADT 與 TrustCache。
- **復現**：來源未記完整指令。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：300 秒零 panic 零 watchdog 超時，產生 `boot.log` (568 KB)、`framebuffer.png` (125 KB)、`display-after.bin` (432 B)、`native-report.bin` (152 B)、`progress.jsonl` (355 KB)；`SpringBoard` (PID 6)、`backboardd` (36)、`runningboardd` (5)、`logd` (69) 均 0 次退出（共 101+ PID，68 個背景服務常駐）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：完成診斷，轉入 E-028。
- **出處**：`boot_failure_and_fix_log.md:L436-L444`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-028 Boot 29：ADT 注入 `disp0`/`wdt`/`buttons`、靜態 TrustCache 與靜音主控台

- **日期**：2026-11-08（交接版）
- **狀態**：未解決：`headless=false` 且 68 服務常駐 300s 零 panic，但實體螢幕仍需 K5 `AppleCLCD` 管線
- **開關**：`sweetfb_noconsole=1`
- **問題／現象**：解除 `backboardd` headless 模式並降低主控台文字干擾。
- **根因**：ADT 缺顯示子系統與按鍵／看門狗屬性；`xnu-12377` 本身亦未連結 `AppleCLCD` / `SweetFramebuffer` 顯示管線（K5 里程碑）。
- **做法**：  1. 更新 `ios-fuxi/tools/mkadt-fuxi27.py`，加入 `/arm-io/disp0`（`device_type = 'display-subsystem'`、`compatible = 'sweet,display'`、`canvas-width = 1125`、`canvas-height = 2436`）、`/arm-io/wdt` (`no-pmu = 1`)、`/device-tree/buttons` (`home-button-type = 2`、`opposed-power-vol-buttons = 1`)、`/device-tree/defaults` (`no-effaceable-storage = 1`)，重新產生 `fuxi27-root.adt`（20,576 位元組，357 extents）；
  2. `mkpayload.py` 加入 `--trustcache resources/ios27.tc`（`/chosen/memory-map` 註冊 `TrustCache` `<0x8c6b24000, 0x10ba0>`，3 模組）；
  3. 開機參數加入 `sweetfb_noconsole=1`，打包 `payload27-dada.bin`（93,528,560 位元組）與 `fuxi-xnu-boot.img`（壓縮版 `fuxi-xnu-boot.img.gz` ~26 MB）。
- **復現**：  ```sh
  python scripts/watch_and_boot29.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：300 秒零 panic、`headless = false`、`SpringBoard`/`backboardd`/`runningboardd`/`logd` 零退出、68 背景服務常駐；但實體螢幕仍停留在 ABL splash framebuffer（`0xb8000000`），待 K5 移植 `AppleCLCD`／`SweetFramebuffer`。
- **參考來源**：ios-fuxi（出現在本項內文，細節見出處）
- **結論／未完成**：Track 2（`xnu-12377`）達 K4 里程碑；後續暫轉由 Track 1（`xnu-8796`）先取得可用圖形介面（見 E-030）。
- **出處**：`boot_failure_and_fix_log.md:L447-L459`; `HANDOVER.md:L45-L86`; `README_WINDOWS.md:L7-L77`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

## 顯示管線缺口與轉向 iOS 16（xnu-8796）

### E-029 `xnu-12377` 顯示管線缺口盤點與假 Apple Logo 移除

- **日期**：2026-11-08
- **狀態**：結論：確認 `loader.c` 已無假 logo 繪製，並盤點 `SweetFramebuffer` 無法直接複製之原因
- **開關**：無
- **問題／現象**：使用者明確要求移除自繪假 Apple Logo 並朝向實機可互動 iOS 圖形介面；同時確認 Windows 主機下之建置限制。
- **根因**：`ios-fuxi/xnu27/series` 與 `0004-components.patch` 未將舊版 `SweetFramebuffer.cpp` 接進 `xnu-12377`；該檔案依賴 `SweetSurface.h` 及多個受 `SWEET` 巨集閘控的介面，無法直接單檔複製到定義 `FUXI` 的 `xnu27`；且 Windows 缺乏 `xcrun`／Xcode 26 環境無法本地編譯 `xnu-12377`。
- **做法**：檢查 `ios-fuxi/shim/fuxi-loader/loader.c` 確認已無 `draw_apple_logo`、`apple_boot_asset`、`apple_logo`（僅保留清除 framebuffer），並確認 `fuxi-xnu-boot.img` 與 `out/fuxi-loader-logo/fuxi-xnu-boot.img` 雜湊皆為 `7729d67d2de4de6052e016aac442c020a83c17a5b316a6e856902ba15bce73a7`（`.bak` 為 `feed8b12...`）。
- **復現**：見 `scripts/remove_fake_logo.py`（T-027）。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：以裝置探針（`0x46`）確認 `launch=1, stage=8, active=1`，12 秒只讀採樣見 XNU 日誌計數自 `779,319` 增至 `789,393`（存於 `diagnostics/live-20261108-165440/kernel-ring-tail.bin`）。
- **參考來源**：ios-fuxi（出現在本項內文，細節見出處）
- **結論／未完成**：釐清實況，決定先評估原生含 CPU 顯示／觸控路徑之 `xnu-8796` 核心。
- **出處**：`CONTINUATION_20261108.md:L3-L16,L24`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-030 評估原生 iOS 16 核心路徑：`xnu-8796` RAM 診斷開機 `fuxi-diag-ram.img`

- **日期**：2026-11-08
- **狀態**：實驗：驗證 `IOCoreSurfaceRoot` 與 `AppleCLCD` 成功註冊（靜態 `init` PID 1）
- **開關**：`cpus=1`、`rd=md0`、`sweetlog=0`
- **問題／現象**：在不碰手機儲存分區的前提下，驗證 `zgl97/ios-fuxi` 的 `xnu-8796` 核心是否確實在小米 13 上具備 `IOCoreSurfaceRoot` 與 `AppleCLCD`。
- **根因**：`ios-fuxi/README.md` 記載 `xnu-8796` 已包含 CPU 顯示與觸控路徑。
- **做法**：自 `zgl97/ios-fuxi` GitHub Actions run `42244366810`（commit `979e2f08c704677bb75934ae96d4686ba9d1692b`，40 項 manifest SHA-256 全數吻合）下載 `fuxi-kernel-metal4` 存至 `candidates/kernel-metal4-zgl-42244366810/`，並以 `scripts/build_diag_loader.py` 打包純 RAM 診斷映像 `fuxi-diag-ram.img`（SHA-256 `f28831b2d493fdc17771278810334ffbf601903f5e1ced3e381752db11d12937`），搭配 `sweet-init.S` 與參數 `-v debug=0xc serial=3 cpus=1 keepsyms=1 rd=md0 sweetlog=0 wdt=-1`。
- **復現**：  ```sh
  python scripts/build_diag_loader.py
  fastboot boot candidates/kernel-metal4-zgl-42244366810/diag-loader/fuxi-diag-ram.img
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：`diagnostics/ios16-ram-kernel-corrected/boot.log` 確認 `IOCoreSurfaceRoot` 與 `AppleCLCD` 成功註冊，靜態 `init` 作為 PID 1 運作。
- **參考來源**：ios-fuxi（出現在本項內文，細節見出處）
- **結論／未完成**：採用，確認 `xnu-8796` 顯示服務可啟動，繼續建置 iOS 16 RootFS。
- **出處**：`CONTINUATION_20261108.md:L18-L28`; `diagnostics/ios16-ram-kernel-corrected/before.json:L1-L14`; `diagnostics/ios16-ram-kernel-corrected/boot.log:L1-L60`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-031 讀回 `ios27-root.img` 與隔離 QEMU Alpine 建置 iOS 16.7.16 HFS+ RootFS

- **日期**：2026-11-08
- **狀態**：實驗：備份 `ios27-root.img` 並產出 20 GiB `ios16-root-build.img`（`fsck.hfsplus` 通過）
- **開關**：無
- **問題／現象**：保留手機原有 `/data/ios27-root.img`（8 GB），並產出乾淨的 20 GiB iOS 16.7.16 (`20H392`) HFS+ 根映像供 Track 1 使用。
- **根因**：舊 `/data/ios16-root.img` 已不在手機上，且前期文件誤將版本寫為 16.7.10，實際來源為 **iOS 16.7.16 / 20H392**。
- **做法**：  1. 執行 `scripts/read_root27_backup.py` 將 `/data/ios27-root.img` 讀回至 `candidates/recovered-root27/ios27-root.img`（SHA-256 `eb19e569e86cc71cec4cf82924c5eefb891591ab396905b6f22fd69de0667c87`，與 `root_report.json` 視窗雜湊吻合）；
  2. 於隔離的 QEMU Alpine Linux VM 中，以只讀方式掛載 OS／SystemOS／AppOS 三份 APFS 映像，執行 `scripts/build_ios16_root_guest.sh` 產出 20 GiB `candidates/vm-tools/ios16-root-build.img`；
  3. 從 20H392 韌體提取 D22AP 裝置樹，將 61 個 `/product` 屬性加入候選 ADT。
- **復現**：見 `scripts/build_ios16_root_guest.sh`（T-005）與 `scripts/read_root27_backup.py`（T-009）。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：`ios16-root-build.img`（21,474,836,480 位元組，SHA-256 `5fc67460bcbdc1de0a6a076daa8cfb01c47ecfc71c2a5760cb8ab5a7acaa2864`）；兩個 Cryptex 卷逐位元吻合，OS 卷 51 項差異符合 `VirtualAudio` 停用、`MediaToolbox`、`launchd` 調整，`fsck.hfsplus -fn` 通過。
- **參考來源**：Linux（出現在本項內文，細節見出處）
- **結論／未完成**：採用，成功備妥 Track 1 根檔案系統。
- **出處**：`CONTINUATION_20261108.md:L30-L32`; `root_report.json:L1-L49`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-032 `f2fs_io.rs` pin 誤判與釐清 `FIEMAP` `0x1000` (`MERGED`) 旗標

- **日期**：2026-11-08
- **狀態**：修復：確認 `/data/ios16-codex-b.img`（160 extents）無 `UNWRITTEN` 等異常旗標
- **開關**：無
- **問題／現象**：確認手機上新建之 `/data/ios16-codex-b.img`（inode `152183`、20 GiB、`lsattr` `C`、160 extents）是否真正固定且可安全寫入。
- **根因**：上游 `scratch/f2fs_io.rs` 誤將 `F2FS_IOC_GET_PIN_FILE` 回傳 GC count `0` 判為 `unpinned`；另早期人工誤將 `FIEMAP` 旗標 `0x1000` 解讀為 `UNWRITTEN`（NDK 標頭定義 `0x1000` 為 `MERGED`，`0x800` 才是 `UNWRITTEN`）。
- **做法**：修正 `scratch/f2fs_io.rs` 判斷邏輯並重新檢查 `FIEMAP` 旗標。
- **復現**：編譯執行 `scripts/inspect_fiemap.c` 檢查檔案 extent。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：確認 160 個 extent（`diagnostics/ios16-codex-b-fiemap.txt`）之 `UNWRITTEN`、`SHARED`、`UNKNOWN`、`DELALLOC` 旗標皆為 0，且與 `ios27` 及舊 `/data/ios16-codex.img`（664 extents）無重疊。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，確認實體區塊配置安全無誤。
- **出處**：`CONTINUATION_20261108.md:L32-L33`; `diagnostics/ios16-codex-b-fiemap.txt:L1-L50`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-033 排除 Windows `adb` `0x1a` EOF 問題，改 TCP 29865 串流寫入與讀回驗證

- **日期**：2026-11-08
- **狀態**：修復：全檔 20 GiB 逐位元讀回比對 SHA-256 100% 吻合
- **開關**：無
- **問題／現象**：將 20 GiB `ios16-codex-b.img` 寫入手機未掛載之 `/dev/block/sda32` 實體 extent 時，早期管線寫入測試提早中斷：`short input or read error`／`short input: EOF on fd 0 after 1337 bytes`。
- **根因**：Windows 版 `adb` `stdin` 管線將位元組 `0x1a` 視為 `EOF`，導致串流寫入中斷。
- **做法**：改用 `adb forward tcp:29865 tcp:29865` 搭配 `scripts/stream_ios16_candidate.py`（呼叫裝置端 `/tmp/write-pinned-extents` 監聽 loopback `29865`），並在寫入前後卸載 `/data` 與 `/sdcard`、刷空區塊緩衝區後以 `scripts/verify_ios16_candidate.py` 逐位元讀回比對。
- **復現**：  ```sh
  adb forward tcp:29865 tcp:29865
  python scripts/stream_ios16_candidate.py --image <PATH_TO_20G_IMG> --block-bytes <SDA32_BYTES>
  python scripts/verify_ios16_candidate.py --image <PATH_TO_20G_IMG> --table <EXTENTS_JSON>
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：`diagnostics/ios16-candidate-write-v4.log` 顯示 160/160 extent、21,474,836,480 位元組寫入並同步完成；`diagnostics/ios16-candidate-readback.json` 確認 `compared_byte_for_byte: true`、`sha256: 5fc67460bcbdc1de0a6a076daa8cfb01c47ecfc71c2a5760cb8ab5a7acaa2864` 與主機映像完全一致。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，建立後續所有 20 GiB root 映像寫入與驗證標準流程。
- **出處**：`CONTINUATION_20261108.md:L34,L44`; `diagnostics/ios16-candidate-write.log`–`v4.log`; `diagnostics/ios16-candidate-readback.json:L1-L9`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-034 iOS 16.7.16 (`xnu-8796`) 首次實機開機、鎖屏截圖與主畫面手勢確認

- **日期**：2026-11-08 18:11–18:41
- **狀態**：實驗：顯示 iOS 鎖屏且上滑進主畫面可行，但 CPU 渲染極卡頓且 30 分鐘後觸發自動重置
- **開關**：無
- **問題／現象**：實機驗證 `xnu-8796`＋iOS 16.7.16 HFS+ root 能否進入可用圖形桌面與觸控互動。
- **根因**：純 CPU 渲染無 GPU 加速導致系統極為卡頓；`driverkitd`、`assetsd`、`AegirPoster`（signal 6）仍有崩潰，且藍牙／FairPlay 停用。
- **做法**：移除 TCP 轉發後，於 Fastboot 以 `fastboot boot` 載入候選映像（SHA-256 `f5710308b07989ae8d92712cccca3f15eef21aab71daa191ea8f25aa2e52a85d`），使用 `fuxi-xnu-monitor.py` 與 `scripts/capture_probe_framebuffer.py` 進行只讀觀察。
- **復現**：  ```sh
  fastboot boot candidates/kernel-metal4-zgl-42244366810/ios16-root-loader/fuxi-ios16-root.img
  python ios-fuxi/tools/fuxi-xnu-monitor.py --kernel <KERNEL_UNSTRIPPED> --payload <PAYLOAD_BIN> --out diagnostics/my-boot --seconds 300 --reset-minutes 30 --framebuffer --touch-power
  python scripts/capture_probe_framebuffer.py diagnostics/my-snapshot
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：  - `diagnostics/ios16-first-boot/boot.log` 確認辨識 160 extents、`BSD root: ufsroot0`、HFS+ 掛載成功、`SpringBoard`/`backboardd`/`AppleCLCD`/觸控服務開啟；
  - `diagnostics/ios16-first-boot/framebuffer.png` 首次擷取到 iOS 鎖屏與 Home 指示條；`18:22` `diagnostics/ios16-current/framebuffer.png` 顯示時鐘由 `4:05` 推進至 `4:10`（`autorefresh=0x80000001`）；
  - `diagnostics/ios16-interaction/boot.log` 確認 FTS 觸控晶片 ID `3640`、感測器輪詢正常、溫度峰值 `50.3°C`；
  - 使用者親眼確認實機顯示 **iOS 主畫面**且**從鎖屏上滑可行**，但回報「UI 非常卡頓」；約 `18:41`（30 分鐘重置期限）探針斷線，手機回到 Android。
- **參考來源**：ios-fuxi（出現在本項內文，細節見出處）
- **結論／未完成**：Track 1 成功點亮 iOS 16 桌面並驗證觸控，後續進入效能／GPU 加速階段（`000` 之後續工作）。
- **出處**：`CONTINUATION_20261108.md:L45-L50`; `README.md:L36`; `diagnostics/ios16-first-boot/before.json`; `diagnostics/ios16-interaction/before.json`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-035 建立效能 A/B 候選 `ios16-perf-loader` 與修正 monitor `--kernel-slide`

- **日期**：2026-11-08
- **狀態**：工具：產出含 `fuxiperf=1 fuxicpuload=10` 之開機映像（尚未上機）並修正 slide 誤判
- **開關**：`fuxiperf=1`、`fuxicpuload=10`
- **問題／現象**：針對 E-034 觀察到的 CPU 渲染卡頓（早期單點 EPSS 採樣顯示 `gold ~499 MHz`、`prime ~595 MHz`），製作高頻效能 A/B 測試映像；同時修正監看腳本誤讀 `xnu-8796` payload 標記為 `xnu27` slide 的問題。
- **根因**：舊版監看腳本將 `xnu-8796` payload 標記誤判成 `xnu27` kernel slide，導致位址解析錯誤；CPU 預設時脈偏低。
- **做法**：  1. 依 payload 版本修正預設 slide 與 log-ring 容量處理，並新增 `--kernel-slide` 參數；
  2. 以 `scripts/prepare_ios16_perf_payload.py` 複製通過驗證的 payload，於 cmdline 附加 `fuxiperf=1 fuxicpuload=10`，打包為 `candidates/kernel-metal4-zgl-42244366810/ios16-perf-loader/fuxi-ios16-root.img`（SHA-256 `f79972267b2cf0cb00409329bbf55eb1c72f4d9329b0b82d45d99df971d04b50`）。
- **復現**：  ```sh
  python scripts/prepare_ios16_perf_payload.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：產生 A/B 候選映像（當時尚未上機，且因 Android 已重開過，上機前須重驗 `FIEMAP`）。
- **參考來源**：原始紀錄未列
- **結論／未完成**：完成工具與候選準備（後續 GPU 效能路線接手）。
- **出處**：`CONTINUATION_20261108.md:L29,L51`; `scripts/prepare_ios16_perf_payload.py:L1-L25`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

## 雙系統與開機體驗

### E-036 KSU 雙系統開機模組 `fuxi_ios_boot`（`boot_b` 分流器 `chain-v1`～`v9`）

- **日期**：2026-11-14～2026-11-18
- **狀態**：結論：實作 `boot_b` 免電腦開 iOS，已於 2026-11-18 改用 `boot_a` 常駐選單並封存移除
- **開關**：無
- **問題／現象**：讓手機在不接電腦的情況下進入 iOS，同時保留 Android 與使用者資料。
- **根因**：ABL 無論一般開機或 recovery 開機皆使用 `boot` 分區之核心，區別在於一般開機的 bootconfig 含有 `androidboot.force_normal_boot`，而 recovery 開機沒有（若將 loader 放入 `recovery_a` 會無法運作並標記 a 槽不可開機）。
- **做法**：  1. 在 `boot_b` 放置分流器映像（`ios-fuxi/shim/fuxi-loader/chain.c`，由 `work\boot-chain\build-chain.py` 建置），在碰任何硬體前讀取 DTB initrd 範圍與 bootconfig：一般開機 → 啟動 iOS；recovery 開機 → 原地跳轉內嵌於 `0xA9200000` 之 Android 核心 → 進 TWRP；
  2. 以 `work\ksu-ios-entry\build-module.py` 打包 KernelSU 模組 `fuxi_ios_boot-<版本>.zip`（歷經 `chain-v1`、`v2`、`v3`、`v4`、`v6`、`v7`、`v8`、`v9`，`module.prop` 顯示最終版 `v9`）；
  3. 使用者在 KernelSU 點擊「執行」（`action.sh`）依序執行 5 步檢查：
     - `[1/5]` 確認目前在 `_a` 槽（`ro.boot.slot_suffix = _a`）；
     - `[2/5]` 確認 `/dev/block/mapper/codexnative_root_1108b` 未被 Android 對應，以 `bin/inspect-fiemap` 比對 `expected-fiemap.txt`、以 `bin/check-pin` 確認 `flags=0x800000 pin_rc=0 moved=0`；
     - `[3/5]` 核對 `boot_b` 前 `loader.size`（66326528 B）之 SHA-256 等於 `loader.sha256`（v9：`7977fbf0...2773`），並核對 `recovery_b` 等於 TWRP `twrp.sha256`（`7d589d3c...ac1`）；
     - `[4/5]` 呼叫 `bootctl set-active-boot-slot 1` 切至 `b` 槽；
     - `[5/5]` `sync` 並 `reboot` 進入雙系統選單。回 Android 時長按「電源＋音量上」進 TWRP 切回 Slot A（或卡死時「電源＋音量下」7 秒暖重置後立刻按「電源＋音量上」）。
- **復現**：  ```sh
  python work\ksu-ios-entry\build-module.py chain-v9-dualboot-launching
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：2026-11-14 使用者親手驗證完整來回（KSU → iOS → TWRP → Slot A → Android）；注意 `b` 槽一般開機時 USB 不會出現（ABL 僅在 fastboot 模式開 USB）。2026-11-16 06:33 換 `chain-v2`、08:47 換 `chain-v3`。
- **參考來源**：ios-fuxi、TWRP（出現在本項內文，細節見出處）
- **結論／未完成**：被取代（2026-11-18 04:45 起 `boot_a` 已改為常駐 dualboot 選單，KSU 模組 `fuxi_ios_boot` 已依使用者要求從手機移除並封存於 `D:\xiaomi13\fuxi_Backup\ksu-module-remove-ksu-module-20261118\`；`boot_b` 留作 `chain-v9` 備援且禁止切回）。
- **出處**：`xiaomi13-standalone-boot.md:L11-L27`; `work/ksu-ios-entry/build-module.py:L1-L75`; `work/ksu-ios-entry/fuxi_ios_boot/action.sh:L1-L47`; `work/ksu-ios-entry/fuxi_ios_boot/module.prop:L1-L7`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-037 開機觸控延遲 30 秒成因與改預設為 10 秒

- **日期**：2026-11-14
- **狀態**：修復：`fuxi_touch.c` `fuxitouchdelay` 預設 30 秒，先以 loader 調 10 秒再合入核心補丁
- **開關**：`fuxitouchdelay`、`fuxitouchdelay=10`
- **問題／現象**：使用者回報「鎖屏剛出現時觸控沒反應」，約等十數秒才可操作。
- **根因**：`fuxi-h1/fuxi_touch.c` 的 `ft_thread` 固定等待 `fuxitouchdelay`（預設 30 秒，文件未記理由）才開始掃描；例如 0019 次約 41–42 秒畫出鎖屏，觸控直到約 53 秒才啟動。
- **做法**：先以 `native-touch10-user-loader` 傳入 `fuxitouchdelay=10` 測試；同日傍晚於核心補丁 `kernel-input-fixes.patch` 將預設值改為 10 秒。
- **復現**：CI run `43575185761`。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：後續不必每顆 loader 都額外帶 `fuxitouchdelay=10`。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用，已解決。
- **出處**：`xiaomi13-boot-logo-request.md:L11-L13,L22`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-038 開機真 Apple Logo 疊加開機跑碼待辦（低優先）

- **日期**：2026-11-14
- **狀態**：未解決：採樣 USB 抓圖需 16s 無法抓 2s logo，待從 rootfs 取原圖並改 console 背景重畫
- **開關**：無
- **問題／現象**：使用者要求「擷取真 logo、保留跑碼、跑碼疊在 logo 上顯示」（取代 11/08 移除之假 logo），明講優先程度不高。
- **根因**：目前鎖屏前那 ~2 秒的 logo 是 `backboardd` 啟動後 iOS 自行繪製；`capture_probe_framebuffer.py` 走 512-byte USB 控制傳輸，抓一張 `1080x2400` 需 ~16 秒，來不及抓只出現 2 秒的 logo 幀；且 XNU 文字 console 捲動會搬移整塊 framebuffer，不能只在 loader 預先畫一張圖。
- **做法**：構想改從 root 映像取出 iOS 原生 logo 圖檔（候選路徑 `/usr/share/progressui/applelogo*`，未確認），並修改 XNU 文字 console 捲動／清除邏輯改以 logo 當背景重畫。
- **復現**：尚未實作。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：尚未驗證。
- **參考來源**：原始紀錄未列
- **結論／未完成**：未完成（低優先待辦）。
- **出處**：`xiaomi13-boot-logo-request.md:L14-L20`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

## 周邊準備與參考專案盤點（2026-11-14）

### E-039 小米 13 硬體適配現成方案總調查

- **日期**：2026-11-14（2026-11-16 補充基頻／相機／本機建置調查）
- **狀態**：結論：確定優先移植順序：亮度 → ADSP+GLINK 基礎層 → 電池 → 聲音 → Wi-Fi/藍牙
- **開關**：`fuxi`
- **問題／現象**：為小米 13（`fuxi`，SM8550）周邊硬體（亮度、電池、聲音、Wi-Fi、藍牙、USB、基頻、相機）尋找可直接移植或參考的現成專案，避免從零開發。
- **根因**：本機 `UniXNU`、`unixnu-fuxi` 與社群專案（`UniXNU/UniXNU-sheng`、`Kerfand/UniXNU-Fuxi-Arm64e-iOS17` 等）已有同 SoC（SM8550）或同機型實證實作。
- **做法**：離線盤點並制定建議移植順序：
  1. **亮度**：僅動 DSI0，移植 `unixnu-fuxi/package/AppleARMBacklight.cpp` 之 `fuxi-backlight=dsi`（DCS `0x51`），但須改由掃描輸出在兩次傳輸間代送，避免 `IODelay` 忙等；
  2. **ADSP＋GLINK／QRTR 基礎層**：自 `UniXNU-sheng` 移植 `AdspProbe.cpp`、`AdspFirmware.c`、`QcomSmem`、`QcomGlink`、`QcomQrtr`，打通後接**電池**（`ShengBattmgr.c`/`ShengBattery.cpp`，改為單電芯）；
  3. **聲音**：移植 AudioReach（GPR `adsp_apps`）＋`CS35L41`（非 sheng 的 `CS35L43`）＋HAL 外掛，並參考 Kerfand 卡住的喇叭保護 `spac` 與 ADT `product-id`/`acoustic-id 8006`；
  4. **Wi-Fi／藍牙**：參考 `UniXNU/Ath12kWifi`＋sheng `WifiProbe`（WCN7850 供電／PCIe／MSI）與 `UniXNU/QcaBluetooth`（`fuxi` UART 在 QUP2 SE6），將 Apple 端介面改回 iOS 16 版（注意 GPL-2.0-only 授權遵循）；
  5. **額外參考**：`UniXNU/QcomDwc3`（USB）、`UniXNU/QcomBaseband`（基頻）、`starlte`/`ios-redfin`（相機／通話）、`ios-redfin` `tools-localbuild`（WSL 本機編譯 `xnu-8796.141.3`）。
- **復現**：純離線文獻與程式碼調查，未觸及手機。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：確認小米 13 的硬體差異點（單電芯、CS35L41、QUP2 SE6、iOS 16 userland 介面）。
- **參考來源**：UniXNU-sheng、UniXNU、Kerfand、QcomBaseband（出現在本項內文，細節見出處）
- **結論／未完成**：採用作為後續 `000` 硬體適配線（亮度、ADSP/電池、音訊、Wi-Fi、藍牙）之總藍圖。
- **出處**：`work/hardware-reference-survey-20261114.zh-TW.md:L1-L39`; `xiaomi13-hardware-reference-projects.md:L1-L33`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-040 亮度 DSI0 `AppleARMBacklight` 離線補丁準備（`0117`）

- **日期**：2026-11-14
- **狀態**：結論：完成 `fuxibacklight=4/5` 補丁與主機測試，但調查建議改由掃描輸出代送不忙等
- **開關**：`fuxibacklight=1|2|3`、`fuxibacklight=4`、`fuxibacklight=5`
- **問題／現象**：解決既有 `0109-fuxi-backlight.patch`（`fuxibacklight=1|2|3`）僅繼承 `IODisplay` 而非 `AppleARMBacklight` 導致 `CoreBrightness` 不綁定、且未操作硬體暫存器的問題。
- **根因**：`CoreBrightness` `-[CBDisplayContaineriOS findBacklight]` 要求 `backlight-control = true` 且 `IOObjectConformsTo(service, "AppleARMBacklight")`。小米 13 面板使用 DSI0（`0xae94000`）TPG 命令 DMA 傳送 MIPI DCS `0x51`（`inverted-dbv` 高位元組優先，範圍 `0x4..0x7ff`，下限鉗制 `8`）。
- **做法**：製作隔離補丁 `work/peripherals-prep-20261114/backlight/patches/0117-fuxi-backlight-dsi.patch`（`FuxiDsiBacklight.cpp`、`fuxi_dsi_backlight_logic.h`），新增 `fuxibacklight=4`（獨立 `IOWorkLoop`＋`16ms IOTimerEventSource`＋超時熔斷 `fHalted`）與 `fuxibacklight=5`（含電源興趣通知）。
- **復現**：  ```powershell
  python D:\xiaomi13\fuxi_ios\work\peripherals-prep-20261114\backlight\verify_backlight_dsi.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：通過 `git apply --check`、NDK Clang C++14 `-Wall -Wextra -Werror` 編譯與 DCS `0x51` 單元測試。
- **參考來源**：原始紀錄未列
- **結論／未完成**：`hardware-reference-survey-20261114.zh-TW.md` 指出該 `0117` 草稿另開執行緒直接寫 DSI，與掃描輸出共用同一條命令 DMA，**不建議直接照用**（僅沿用其硬體規格）。
- **出處**：`work/peripherals-prep-20261114/backlight/README.md:L1-L18`; `work/hardware-reference-survey-20261114.zh-TW.md:L15,L38`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-041 音訊 `P-AU0/P-AU2` 離線準備（`0118` RPMH 鎖與 `CS35L41` DT）

- **日期**：2026-11-14
- **狀態**：結論：完成跨驅動 TCS 鎖補丁與 `CS35L41` 規格整理，仍缺 ADSP PAS/GLINK 與韌體
- **開關**：無
- **問題／現象**：為音訊適配 `P-AU0`（HAL 外掛）與 `P-AU2`（跨驅動 Apps RSC DRV2 TCS 鎖）做離線準備並提取 live DT 硬體規格。
- **根因**：`fuxi_wlan.c::rh_send_request()` 原有未加鎖之 `rh_poisoned` 檢查，多驅動共用 Apps RSC 會發生競爭；且尚未自手機提取 ADSP 韌體與 ACDB 拓撲。
- **做法**：  1. 製作 `audio/patches/0118-fuxi-rpmh-arb-wlan.patch` 與 `fuxi_rpmh_arb.c`，在 `rh_send_request()` 改用 `fuxi_rpmh_arb_enter(..., FUXI_RPMH_OWNER_WLAN, 1000000u)` 與 `fuxi_rpmh_arb_leave(..., ok)`；
  2. 製作 `fuxi_cs35l41_dt_spec.h`（從 `dtb/fuxi-live.dtb` 提取 I2C `0x880000`、雙 `CS35L41` `0x40`/`0x42` reset GPIO `183`/`182`、ADSP carveout `0x9e980000`/`0x9ea00000`）；
  3. 記錄 macOS Xcode 建置 `FuxiAudio.driver` 與 `fuxi-sys-root.py --restore-virtualaudio`（不可單獨恢復 `VirtualAudio.plugin` 以免 `mediaserverd` 崩潰）及測試 preamble 同步提醒（`tests_update_hint.md`）。
- **復現**：  ```powershell
  python D:\xiaomi13\fuxi_ios\work\peripherals-prep-20261114\verify_all.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：`verify_audio_host.py` 於臨時目錄通過 patch 套用與 C 語法檢查；`P-AU2 ~ P-AU9` 仍缺 ADSP PAS/GLINK、GENI I2C、CS35L41、WCD938x 及手機端韌體提取。
- **參考來源**：原始紀錄未列
- **結論／未完成**：離線準備完成，待 ADSP 基礎層就緒後合入。
- **出處**：`work/peripherals-prep-20261114/audio/BUILD_AND_STAGE_MACOS.md:L1-L38`; `work/peripherals-prep-20261114/audio/tests_update_hint.md:L1-L11`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-042 Wi-Fi `fuxiwifiios=1`、`P17` 診斷與 608 位元組開機參數組

- **日期**：2026-11-14
- **狀態**：結論：產生 9 組 `<608B` 開機參數與 WCN7850 韌體 SHA256 清單；802.11 資料面待開發
- **開關**：`fuxiwifiios=1`、`sweetsample`、`sweetscan`、`sweetexecswap`、`sweetnull`、`fuxiwlanmlo=0x17d`、`fuxiwlanrails=1`
- **問題／現象**：整理 iOS 設定頁假體 Wi-Fi UI（`fuxiwifiios=1`）與實機 WCN7850 `P17`／`wlan-rails` 診斷旗標，並確保所有組合不超過 XNU-8796 `boot_args.CommandLine` 的 608 位元組上限（最多 607 ASCII 字元）。
- **根因**：現行 `0025` base cmdline 已佔 562 位元組（僅餘 45 位元組），直接附加長串 `fuxiwlan*` 參數會超過 608 位元組。
- **做法**：  1. 以 `wifi/generate_cmdlines.py` 產出 `cmdlines/*.txt` 與 `cmdlines.json`：含 `0025_wifi_ui_fake` (576 B)、`0025_wifi_ui_plus_backlight_dsi` (592 B)，以及透過移除 Metal profiler 旗標（`sweetsample`/`sweetscan`/`sweetexecswap`/`sweetnull`）壓縮至 ≤607 B 的 `wcn7850_p17_*` 系列（`fuxiwlanmlo=0x17d`/`0x1bd`、`fuxiwlanrails=1`/`2`）；
  2. 製作 `wifi_fw_expected.json`（`amss20.bin`、`amss.bin`、`bd_m3gl.elf`、`regdb_xiaomi.bin`）與 `scripts/pull_fuxi_firmware.ps1`；
  3. 記錄 Windows 上 `sync-fuxi-wifi-ios.py`（大小寫排序差異）與 `sync-fuxi-backlight.py`（CRLF 差異）之跨平台注意項。
- **復現**：  ```powershell
  python D:\xiaomi13\fuxi_ios\work\peripherals-prep-20261114\verify_all.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：通過 `verify_wifi_prep.py` 長度與格式檢查；當時實機進度尚卡在 `W17 try16` `WLAN_MODE (0x22)` 無回應，且未有 802.11 資料面。
- **參考來源**：原始紀錄未列
- **結論／未完成**：離線準備完成（後續另改走 `Ath12kWifi` 主線方案）。
- **出處**：`work/peripherals-prep-20261114/wifi/README.md:L1-L29`; `work/peripherals-prep-20261114/README.md:L11`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-043 電池 SPMI v7 / `PMK8550 vadc@9000` / `PMIC_RTR_ADSP_APPS` 規格分析

- **日期**：2026-11-14
- **狀態**：結論：確認 `SweetBattery` 因 SPMI v7 退回靜態 100%，規劃先唯讀 VADC 探針再接 ADSP
- **開關**：無
- **問題／現象**：盤點小米 13 電量與充電顯示所需硬體規格，避免未經實機驗證即硬寫 SPMI 暫存器。
- **根因**：`0025`/`metal4`/`wlan6g` 核心已內建 `SweetBattery.cpp`（因 `0082` 定義 `ARM64_BOARD_CONFIG_SWEET`），但 `bsd/dev/sweet_spmi.c` 鎖死 SM7150 SPMI v5（`0x0c440000`）並拒絕 `arb_version >= 0x70000000`，故印出 `SWEET BATTERY: unsupported SPMI arb=...` 後退回靜態 100% / 4200 mV；且檢視 `dtb/fuxi-live.dtb` 確認小米 13 無獨立 I2C 電量計。
- **做法**：整理 `fuxi_battery_hw_spec.h`（SPMI v7 `0x0c400000..0x0c500000`、`PM8550B SID 7`、`PMK8550 (SID 0) vadc@9000` 9 個 ADC 通道如 `0x78f`/`0x78e` 與溫度通道、ADSP `pmic_glink` 通道 `PMIC_RTR_ADSP_APPS`），並規劃兩階段路線：先唯讀 `vadc@9000` 探針量測換算曲線，再隨 ADSP PAS+GLINK 實作 `PMIC_RTR_ADSP_APPS` 用戶端。
- **復現**：  ```powershell
  python D:\xiaomi13\fuxi_ios\work\peripherals-prep-20261114\battery\verify_battery_spec.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：`verify_battery_spec.py` 以 `dtb/fuxi-live.dtb` 交叉驗證所有通道與位址並通過 NDK Clang `-Wall -Wextra -Werror` 檢查。
- **參考來源**：原始紀錄未列
- **結論／未完成**：採用作為後續 ADSP＋電池適配規格依據。
- **出處**：`work/peripherals-prep-20261114/battery/README.md:L1-L22`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-044 藍牙 QUP2 SE6 規格、H4 framer 與 `sweetnoexec` 解除前置清單

- **日期**：2026-11-14
- **狀態**：結論：備妥 H4 狀態機與接腳規格；未有核心驅動前嚴禁移除 `sweetnoexec=bluetoothd`
- **開關**：`sweetnoexec=bluetoothd,fairplayd.H2`、`sweetnoexec=bluetoothd`
- **問題／現象**：整理小米 13 藍牙（WCN7850 `bt_kiwi`）硬體規格與可重用 H4 UART framing 元件，並定義解除使用者態封鎖的安全閘門。
- **根因**：現行開機參數以 `sweetnoexec=bluetoothd,fairplayd.H2`（Patch 0095）封鎖 `bluetoothd`；且現有核心全無 `/dev/uart.bluetooth`（H4 `3000000 bps`）與 `/dev/btreset` 驅動，亦無 Broadcom → QCA vendor HCI 轉譯。
- **做法**：整理 `fuxi_bt_hw_spec.h`（`qcom,qup_uart@898000` QUP2 SE6、SPI `0x1cd`、`BT_EN=gpio81`、`BT_SW_CTRL=gpio82`、共享 6 路 WCN7850 PMU 電源軌）與獨立可編譯之 `fuxi_h4_framer.{h,c}`，並在 `unblock_bt_prep.md` 明訂 4 項硬條件未齊前**嚴禁**移除 `sweetnoexec=bluetoothd`。
- **復現**：  ```powershell
  python D:\xiaomi13\fuxi_ios\work\peripherals-prep-20261114\bluetooth\verify_bt_host.py
  ```
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：`fuxi_h4_framer.{h,c}` 通過 NDK Clang `-Wall -Wextra -Werror` 編譯與 Python 單元驗證。
- **參考來源**：原始紀錄未列
- **結論／未完成**：離線規格與元件就緒，待後續整合 `QcaBluetooth` 時接續。
- **出處**：`work/peripherals-prep-20261114/bluetooth/README.md:L1-L18`; `work/peripherals-prep-20261114/bluetooth/unblock_bt_prep.md:L1-L16`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-045 參考專案 `UniXNU-sheng` 與 `UniXNU-sm8550-common` 技術盤點

- **日期**：2026-11-14（參考檔案時間含 2026-11-02～11-12）
- **狀態**：結論：記錄 SM8550/sheng 在 GPU、觸控、AppSync、電源與記憶體壓縮之實證做法
- **開關**：`fuxi`
- **問題／現象**：萃取同 SoC（SM8550）官方參考移植 `UniXNU-sheng`（小米平板 6S Pro，iPadOS 27.0.1 `24A446`／macOS 27.3 `26C5035r`）的已驗證實作，作為 `fuxi` 硬體適配與效能除錯對照。
- **根因**：`sheng` 與 `fuxi` 共用 SM8550 平台（UFS、GICv3、Adreno 740、WCN7850、SMMU、GENI）。
- **做法**：讀完 `work/ref-sheng/` 與 `work/ref-sheng-bt/sheng/` 之技術報告，關鍵可借鑑項目包括：
  - **SM8550 平台**（`UniXNU-sm8550-common`）：`Sm8550GeniUart`（GPLL0-even 51.2 MHz 支援 3.2 Mbaud）、`Sm8550Gcc`（共享時脈與 apps-SMMU 鎖）、`Sm8550QupDma`（4 KiB ArmSmmu4K 分頁表）；
  - **GPU / Metal**（`ipados27-gpu.md`、`metal-upstream-rendering.md`）：單採樣管線、雙環搶佔（ring 0/1 與 1s watchdog）、`LinearCheap` 紋理平鋪實測（A740 linear 1.339 ms vs optimal 1.048 ms）、uniform 陣列容量修正；
  - **觸控與幀時間**（`ipados27-touch-frame-gaps.md`）：`iconservicesagent` 同步 XPC 等待（4.644 s）導致長幀、`backboardd` 64 MiB 頁面配線耗時 178.904 ms、IRQ 至 SPI 完成中位數 2.52 ms；
  - **AppSync**（`ipados27-appsync.md`）：`libunixnu-ldid.dylib`＋`ubc_cs_blob_add` 動態註冊 trust cache；
  - **開機啟動修復**（`ipados27-startup-repair-2026-11-02.md`）與 **macOS 記憶體壓縮／Swap**（`macos27-memory-run139.md`：壓縮比 2.82:1、5 GiB 回讀 81s）及 **ABL 記憶體交接**（`macos27-abl-memory.md`）。
- **復現**：參考倉庫建置命令 `./unixnu build kernel --device ../UniXNU-sheng`。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：各報告均區分主機 ASan/UBSan 測試、arm64e 編譯與 `sheng` 實機觀測結果。
- **參考來源**：UniXNU-sheng、UniXNU（出現在本項內文，細節見出處）
- **結論／未完成**：作為 `fuxi` SM8550 周邊移植與效能定位之核心參考依據。
- **出處**：`work/ref-sheng/UniXNU-sm8550-common/README.md:L1-L46`; `work/ref-sheng-bt/sheng/README.md:L1-L78`; `work/ref-sheng-bt/sheng/reports/*.md`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-046 參考專案 `UniXNU/Ath12kWifi` 技術盤點

- **日期**：2026-11-14（參考檔案）
- **狀態**：結論：Linux v7.0.14 `ath12k`＋`wpa_supplicant 2.12`＋`org.unixnu.wifi.control` 架構
- **開關**：`fuxi`
- **問題／現象**：了解 `UniXNU/Ath12kWifi` 如何將 Linux v7.0.14 `ath12k`/`mac80211`/`cfg80211` 搭配 `wpa_supplicant 2.12` 移植至 XNU 並於 `sheng`（WCN7850）實機連網。
- **根因**：上游私有／半私有 WCN7850 路徑卡在韌體狀態機，而 `Ath12kWifi` 採用 Linux 主線驅動棧，已在 SM8550＋WCN7850 實機完成開關、掃描、WPA2 關聯、DHCP 與網路傳輸。
- **做法**：核心控制端點為 `org.unixnu.wifi.control`（`nw_cfg80211_control.c`），使用者態由已簽署之 `/usr/libexec/unixnu-wpa_supplicant`（`driver_sheng.c`）負責 SME/WPA/PMF 四向交握，韌體自 `/private/var/ngpu/firmware/ath12k/WCN7850/hw2.0/` 讀取 `amss.bin`、`m3.bin`、`board-2.bin`，並對接 `en0`／Apple80211（24A446 非同步 540B 關聯結果事件，30s join 超時，1s RSSI 更新，64-mbuf RX 批次，NAPI 256 封包 / 2 ms 預算）。
- **復現**：見 `Ath12kWifi/README.md`：`python3 tools/fetch-sources.py --check`、`python3 tools/build-supplicant.py --target ios`、`test-mainline-runtime.py` 等。
- **主機測試**：`test-mainline-runtime.py`
- **驗證紀錄**：主機生命週期測試釋放全部 287/294 追蹤配置，125 個物件與 13 個 XNU 匯入零缺漏；實機完成 WPA2 與 DHCP（熱點／超時／吞吐尚待）。
- **參考來源**：UniXNU、Linux（出現在本項內文，細節見出處）
- **結論／未完成**：成為後續 `fuxi` 原生 Wi-Fi（`ath12k`）成功連網之直接技術藍本。
- **出處**：`work/ref-sheng/Ath12kWifi/README.md:L1-L115`; `work/ref-sheng-bt/sheng/reports/ipados27-wifi-association.md:L1-L35`; `work/ref-sheng-bt/sheng/reports/ipados27-wifi-mainline-migration.md:L1-L99`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-047 參考專案 `UniXNU/QcaBluetooth` 技術盤點

- **日期**：2026-11-14（參考檔案）
- **狀態**：結論：`btqca.c`＋GENI UART DMA＋`UART.SK`＋`bluetoothd` native adapter 架構
- **開關**：`fuxi`
- **問題／現象**：了解 `UniXNU/QcaBluetooth` 如何以 Linux `btqca.c` 驅動 WCN7850 並與 Apple `bluetoothd` 對接。
- **根因**：WCN7850 為 Qualcomm 藍牙晶片，需經 GENI UART DMA 跑 `btqca.c` 啟動序列，且 `bluetoothd` 預設僅懂 Apple/Broadcom vendor HCI。
- **做法**：  - 核心端：`qbt_core.c`（H4/IBS）、`qbt_geni.c`（GENI SE DMA：4x2048B RX、1x4096B TX）、`qbt_transport.c`（`UART.SK` kernel pipe，3.2 Mbaud）、sysctl `kern.qbt_boot`/`kern.qbt_power_on`/`kern.qbt_firmware`；
  - 使用者態：`BlueTool.c`（XPC 服務，讀取 `kern.qbt_power_on` 上電）、`QcaBTType0.dylib`（`Type0.c`）＋`patch-ios27.py`（將 `bluetoothd` 導向 controller type 0，清除 vendor table／hooks，強制 0x2041/0x2042 延伸掃描與 0x2035 位址設定）；
  - 並記錄 `ipados27-bluetooth-startup.md` 中 `addon writer` 寫入 `launchd.plist` 殘留 55 位元組導致 `No service cache` 的修復（補寫 `va_data_size`）。
- **復現**：見 `QcaBluetooth/README.md` 與 `native-ios27.md`（`test-runtime.py`、`test-geni.py`、`test-native.py`、`build-type0.py`、`patch-ios27.py`）。
- **主機測試**：`test-runtime.py`、`test-geni.py`、`test-native.py`
- **驗證紀錄**：144/165 個指令案例與 58 個 ASan/UBSan HCI 案例通過；`sheng` 實機達成配對、重連、A2DP、AirPods 降噪與電量顯示（HFP/SCO 通話未測）。
- **參考來源**：UniXNU、Linux（出現在本項內文，細節見出處）
- **結論／未完成**：作為後續 `fuxi` 藍牙上電與 `QcaBluetooth` 移植之參考。
- **出處**：`work/ref-sheng-bt/QcaBluetooth/README.md:L1-L76`; `work/ref-sheng-bt/QcaBluetooth/native-ios27.md:L1-L102`; `work/ref-sheng-bt/ipados27-bluetooth-native.md:L1-L103`; `work/ref-sheng-bt/ipados27-bluetooth-startup.md:L1-L78`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-048 參考方案 `RAPHAEL-WIFI-PORT-PLAN.md`（SM8150 Wi-Fi 移植紀律）

- **日期**：2026-11-14（參考檔案，R35+ 立項）
- **狀態**：結論：記錄 R35–R38 單變數輪次、BDF 選型與 15 項主機回歸檢查紀律
- **開關**：`fuxi`
- **問題／現象**：參考兄弟機型（SM8150 / `raphael`）對照 `HeliumStudio-Dev/hackios-xnu-kernel` 移植 WCN3990 `ath10k-SNOC` 之工程紀律與輪次規劃。
- **根因**：高通 WLAN 移植涉及 MPSS/TZ PAS、SPMI 五路供電、AOSS QMP 時鐘、SMMU、GLINK/QRTR/RMTFS/TFTP 等多層依賴，一次改多項極難定位。
- **做法**：制定 R35（MPSS 裝載 `wifi_step=1..8`）、R36（ICNSS+BDF+`0x21 FW_READY`）、R37（SNOC 掃描/關聯/DHCP）、R38（toggle/rescan 穩定性）單變數輪次表與 `wifi=0` 回滾開關；嚴禁同時啟動 `ath10k` 與 `qcacld`，並強制移入 15 項主機回歸檢查工具（`check-wifi-*.py`）。
- **復現**：見 `RAPHAEL-WIFI-PORT-PLAN.md` 第五～六節。
- **主機測試**：無（原始紀錄未提）
- **驗證紀錄**：明確區分 ASan/UBSan 通過與實機穩定性驗證。
- **參考來源**：RAPHAEL（出現在本項內文，細節見出處）
- **結論／未完成**：其「單變數輪次＋事前註冊判讀樹＋回滾開關」紀律可供 `fuxi` 參考（硬體本身為 WCN3990/SM8150，不直接套用至 WCN7850/SM8550）。
- **出處**：`work/ref-raphael/RAPHAEL-WIFI-PORT-PLAN.md:L1-L63`（2026-11-18 由早期紀錄盤點逐項整理，Gemini 撰寫、主代理整合與抽查）

### E-049 WCN7850 原廠韌體路線的 M5–W17 主機模型

- **日期**：zgl97/ios-fuxi 基底 979e2f08 之前，2026-11-18 核對測試入口。
- **狀態**：上游主機測試保留，後續實機延伸見 K-041～K-048，日常 ath12k 路線見 K-049 起。
- **開關**：早期模型依對應 docs-lanes 文件使用 WLAN 分階段實驗值。W17／P17 記於 wlan-p17.md 的 fuxiwlanmlo 選項。
- **問題／現象**：需要逐層區分 PCIe、設定電源、MHI、QRTR／WLFW 與韌體啟動，避免把主機模擬當成實機連線。
- **根因**：每一階段由不同傳輸與韌體事件推進。M6 之後仍保留獨立的測試入口，部分後續測試會重用前一階段 synthetic peer。
- **做法**：以下檔名皆位於 ksrc 的 tools/ 或 docs-lanes/。

  | 測試檔名前綴 test-fuxi-wlan- | 涵蓋內容 | 原始說明 |
  | --- | --- | --- |
  | m5.py、m6.py、m6-artifacts.py | M5 相容入口、production C 的 MMIO／VFS／記憶體模型、boot 產物封裝核對 | wlan-bt.md |
  | m6i.py、rails.py | cmd-db／BCM／RSC、ON-only rails 與 synthetic W16 peer | wlan-rails.md |
  | m6k.py、m6l.py、m6m.py | PCIe 探測、cache／ASPM、向量與大小界線、L1SS／BHI | 各測試檔首與 wlan-bt.md |
  | m6o.py | PCIe／RPMh／VFS／DMA，W9 POR INTVEC 診斷 | wlan-w9.md |
  | w10.py、w11.py、w12.py | BHIe 到 AMSS、MHI／QRTR／WLFW、配置與記憶體握手 | wlan-w10.md、wlan-w11.md、wlan-w12.md |
  | w13.py | RESPOND_MEM、EI golden bytes 與有界協商 | wlan-w13.md |
  | w14.py、w15-audit.py | BDF／M3 DMA、EI 交叉核對 | wlan-w14.md |
  | w16.py、w17.py | WLAN_MODE 無回覆時的 IPCR 順序與 P17 診斷 | wlan-w16.md、wlan-p17.md |

- **復現**：在 ksrc 根目錄用 Linux／WSL 的 Python 3、clang 與 sanitizers。從 python3 tools/test-fuxi-wlan-w13.py 和 python3 tools/test-fuxi-wlan-w17.py 跑 production C 模型。m6-artifacts.py 需要依 wlan-bt.md 備妥對應里程碑的封裝產物。w15-audit.py 預設離線，需要比對 Linux EI 定義時依其 --help 提供來源。完整參數與案例以各版本檔首和 lane 文件為準。
- **主機測試**：測試入口見上表。當前 harness 的 hw000-preparation.yml 和 kernel-adsp-battery.yml 直接執行 M6i、rails 與後續 W18。
- **驗證紀錄**：此條目盤點入口與原始證據。個別上游 ASan／UBSan 結果見各 lane 的驗證段落。實機 W18／P17 紀錄見 K-041～K-047。
- **參考來源**：S-099 的 0099 補丁、ksrc docs-lanes/wlan-*.md 及各測試入口。
- **結論／未完成**：保留這批模型供追查電源／握手回歸。現行日常使用採 native ath12k。
- **出處**：ksrc tools/test-fuxi-wlan-*.py 和 docs-lanes 的 M5–W17 記錄。

## 盤點附註（2026-11-18）

> 整理早期紀錄時記下的漏讀與疑點，原文照錄（編號已改成本紀錄庫的編號）。處理後請在對應項目更新，並刪掉這裡的條目。

1. **版本號紀錄矛盾（`HANDOVER.md` / `README_WINDOWS.md` vs `CONTINUATION_20261108.md` / `boot_failure_and_fix_log.md`）**：
   - `HANDOVER.md`、`README_WINDOWS.md` 與 `run_complete_ios_boot.py` 標題均寫「**iOS 16.7.10 (Sydney 20H392)**」；而 `boot_failure_and_fix_log.md` 標題寫「**iOS 17 / XNU (`xnu-12377` / `24A446`)**」但內文卷名仍出現 `SydneyUpdate20H392.D22D221OS`；`CONTINUATION_20261108.md:L31` 明確更正來源實為 **iOS 16.7.16 / 20H392**（並非 16.7.10）。
2. **`diagnostics/` 內二進位與未全文讀取之大型文字檔**：
   - `diagnostics\ios16-ram-kernel-test\boot.log` 前 40 行含有 NUL 位元組與二進位資料（無法作為純文字解析，該目錄另有 `boot-corrected.log` 為純文字）。
   - `diagnostics\ios16-first-boot\boot.log`、`ios16-interaction\boot.log`、`ios16-observe-latest\boot.log`、`ios16-observe-1825\boot.log`、`ios16-observe-1826\boot.log`、`ios16-ram-kernel-corrected\boot.log` 皆僅讀前 60 行；`ios16-codex-b-fiemap.txt`、`ios16-codex-b-fiemap-initialized.txt`、`current-extents27.json` 僅讀前 50 行；`ios16-codex-b.map` 為二進位 `FXMAP01` 格式故跳過。
3. **`boot_failure_and_fix_log.md` 中部分早期步驟未保留完整重建指令**：
   - Boot 1–12 與 Boot 29 提及 `tools/mkadt-fuxi27.py`、`tools/ios27-prelink.py`、`tools/ios27-root.py trust-bundle`、`mkpayload.py` 等腳本名稱與部分旗標（如 `--drop-apfs`、`--root-uuid`、`--trustcache`、`--cpus 1`），但未記下當時於 macOS 執行的完整 CLI 指令字串，亦未記下精確到分鐘之日期時間。
4. **未定狀態之歷史腳本**：
   - `scripts/do_boot30_win.py`、`scripts/auto_stage.py`、`scripts/boot_clean_verify.py`、`auto_boot_orchestrator.py`、`wait_for_adb_and_boot.py` 未見於 `AGENTS.md` 或 `README.md` 最新流程引用，無法僅從本批來源確認是否仍在使用，已依規則標註「不確定」。
5. **外部參考目錄內之其餘程式／報告**：
   - `work\ref-sheng\` 與 `work\ref-sheng-bt\` 依任務指示僅盤點 `.md` 文件，未逐一讀取 `QcaBluetooth\src\`、`UniXNU-sheng\package\` 等原始碼與 `porting.toml`；且 `work\ref-sheng\UniXNU-sheng\reports\` 與 `work\ref-sheng-bt\sheng\reports\` 多數檔案內容重疊（後者另含 macOS 與 metal 系列報告），已統一彙整於 E-045。
