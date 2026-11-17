# Fuxi RAM admission：XNU owning-source checkpoint

## 2026-11-16 交付範圍與結論

這是獨立、host-only 的小 checkpoint：新增 admission 工具、專屬 tests 與本文件；只讀既有 inventory、board production code 和 owning patches。沒有改 mkadt／payload／GPU／loader／sync／build／patch，沒有 commit、push、branch、鎖、adb、fastboot 或手機操作。使用者回報的 current9g RAM512 MiB 4/4／cache-evict 與既有 20/20 inventory host tests 是主線證據，本 worker 沒有重跑，也不把它們當成新 bank 的實機證明。

**結果：current9g＋30 MiB synthetic bank 的幾何 union 是 9214 MiB，但 admission 仍是 `defer`，新增 admitted bytes 是 0，完整 owner clearance 後的 allocatable bytes 是 `null`。** 讀到的官方 ARM64 bootstrap 使用 scalar span、dense per-page metadata 和 contiguous startup enumeration；PTOV 有 segment 表，VM 也有 late page-create 路徑，因此不能把結論擴張成「XNU 所有路徑永遠不能多區」。同樣沒有 Apple 9 GiB／9GB cap 的來源證據；本設計不以 9 GiB 作手機容量上限，也不保證整台 12GB 都可加入 XNU。

[admission 工具](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py:1)・[專屬 tests](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/test-fuxi-ram-admission.py:28)・[前一個 inventory checkpoint，僅引用未改](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/docs-lanes/ram-multirange-preparation.md:1)

## 官方 source provenance

- Repository：[Apple 官方 apple-oss-distributions/xnu](https://github.com/apple-oss-distributions/xnu)。Tag：[xnu-8796.141.3](https://github.com/apple-oss-distributions/xnu/tree/xnu-8796.141.3)。
- Annotated tag object：`f625db25f47631424dc62ac1c3414b6e530f7e8a`；resolved commit：[1b191cb58250d0705d8a51287127505aa4bc0789](https://github.com/apple-oss-distributions/xnu/commit/1b191cb58250d0705d8a51287127505aa4bc0789)。本次以官方 [tag ref API](https://api.github.com/repos/apple-oss-distributions/xnu/git/ref/tags/xnu-8796.141.3) 與 [tag object API](https://api.github.com/repos/apple-oss-distributions/xnu/git/tags/f625db25f47631424dc62ac1c3414b6e530f7e8a) 複核，沒有推送上游。
- 只快取必要的 **13 檔、1,247,301 bytes**，不是完整 source checkout，位置為 `D:\xiaomi13\fuxi_ios\work\adsp-battery\ram-source-reference\xnu-8796.141.3`。raw download 使用上述 immutable commit，不修改原始 bytes。13 檔均通過官方 commit tree 的 Git blob SHA-1 核對，以及下列 SHA-256 核對。
- 每列附實際 tag URL。每檔的 immutable `commit_url`、expected／actual SHA-256、size、verified／missing／hash-mismatch 狀態也會寫進 admission JSON 的 `official_sources.files`；來源缺失或 hash 不符是 pending evidence，不會因此放行。[source verifier](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py:224)

| 官方 tag source URL | Bytes | SHA-256 |
| --- | ---: | --- |
| [osfmk/arm64/arm_vm_init.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c) | 89175 | `3aef6df1e86fea3061ef4b5b83053502e2c50bf2e636d6949c4d55a58181e3f5` |
| [osfmk/arm64/start.s](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/arm64/start.s) | 24304 | `bf92967ea96e638f5a9a002cd4e478272f08616531d212caa919944c85e8a023` |
| [osfmk/arm/arm_init.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/arm/arm_init.c) | 24661 | `5161a3fc8b31b3317e2dd745594ec8a6877590a3976147b52bfd1255d9eec47e` |
| [osfmk/arm/pmap/pmap.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/arm/pmap/pmap.c) | 427347 | `78cdd8a97fae341dd2b757c8def4799e824f56e79ccb8d1b654f92cd6c78e375` |
| [osfmk/arm/pmap/pmap_data.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/arm/pmap/pmap_data.c) | 150036 | `564ee64643bc22d66a36734fa75c3967fca7f592b3dd4f1c1c41160db7742b67` |
| [osfmk/arm/pmap/pmap_data.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/arm/pmap/pmap_data.h) | 66466 | `26f464e4dc2dd71da80d1155f7314a8f107d0a8be54965ac03def390a7dadc17` |
| [osfmk/arm64/machine_routines.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/arm64/machine_routines.c) | 75359 | `663b25f0d52c811dc09a646ab8a5c904826f4312a1bfd23c2d3a9744cb3eb2a1` |
| [osfmk/vm/vm_resident.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/vm/vm_resident.c) | 278889 | `0c0dd352efef32cb032cd0a84f77cce77ba77a90412420df76d2e0f5e9ea81e1` |
| [osfmk/vm/vm_page.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/vm/vm_page.h) | 68982 | `527fc93aaf8c5fa8f66c6ca213d8b9fc59dd924f5af0ad45d55424f8051334a3` |
| [osfmk/mach/arm/vm_types.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/mach/arm/vm_types.h) | 5980 | `b2deb6cfadc2972a42f698b1822393d240f96c1f91426f4f087e0cffc367225d` |
| [osfmk/mach/vm_types.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/mach/vm_types.h) | 7530 | `df52204bad8668284b16da16007a0b88553dd4dc2e6882093fe2f2d335ad2330` |
| [pexpert/arm/pe_init.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/pexpert/arm/pe_init.c) | 25404 | `828368f9415c9749f661563a714152d88f70ce639faae867c900dcfdbdf53b79` |
| [pexpert/pexpert/arm64/boot.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/pexpert/pexpert/arm64/boot.h) | 3168 | `efdfec46319cb147297682a8faebe02873f845261b57f7511ab8e15c13ef3439` |

這補上前一 checkpoint 缺少上述 owning source 的缺口；**官方 reference 並不等於當次 CI 套完 board patches 的完整 source tree／compiled configuration**。當次 build inputs manifest、applied patches、symbols 和實際 runtime boot_args／PTOV 尚未在本 worker 驗證。

## Actual ARM64 owning-source 核對

### boot_args、device tree 與 scalar span

| 已讀 owning source，行號為原始官方檔 | 查得的行為與限制 |
| --- | --- |
| [boot_args:58](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/pexpert/pexpert/arm64/boot.h:58) | 只有一組 `virtBase/physBase/memSize/topOfKernelData`，另有 `memSizeActual`；沒有 bank vector 欄位。 |
| [arm_vm_init:1831](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:1831) | `gVirtBase/gPhysBase` 直接取 boot_args，`real_phys_size` 取 `memSize` 或含 KASAN shadow，`gPhysSize = mem_size` 依 page 邊界向下取整；`mem_actual` 是另一個值。 |
| [maxmem／VA guards:1851](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:1851) | `memory_size` 可以縮 `mem_size`，另有 VA aperture 與 bootstrap table capacity guards；不是固定 9GB 常數。 |
| [avail_start:1940](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:1940)・[avail_end:1957](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:1957)・[first_avail:2371](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:2371) | 初始 available tail 從 `topOfKernelData` 起，end 為 `gPhysBase + mem_size`，bootstrap allocations 後才決定 `first_avail`；不是 `/memory` union。 |
| [dram-base／size:615](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/arm_init.c:615) | `/chosen/dram-base`、`dram-size` 成為 `gDramBase/gDramSize`，原文明確區分它們與 kernel-managed `gPhysBase/gPhysSize`。 |
| [DT initialization:403](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/pexpert/arm/pe_init.c:403)・[named graphics memory-map:256](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/pexpert/arm/pe_init.c:256)・[TrustCache memory-map:1286](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:1286) | DT 來自 boot_args 的 pointer／length；`/chosen/memory-map` 有 BootCLUT、boot picture、TrustCache 等 named image consumers。這些不是 free-bank enumeration API。Linux FDT advertised `/memory` 和 XNU loader 生成的 ADT 也不是同一份資料。 |
| [bootstrap bases／L2 mappings:563](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/start.s:563) | 依 kernel Mach header 調整一組 PA／VA base 和 memory size，再建 bootstrap mappings。新增 lower bank 不能只換 memSize 而忽略 base offset、image placement、L2 邊界與 table capacity。 |

上述已核對的 ARM64 startup 路徑沒有把 FDT 的多個 `/memory` reg tuples 或 named memory-map 直接轉成 allocator banks。這是對 owning startup code 的結論，不是對未快取的所有 Apple board code／hotplug 路徑作不存在宣告。

### PTOV／physmap、PV 與 free-page enumeration

| Owning source | 多 range 能力／缺口 |
| --- | --- |
| [PTOV table:358](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:358)・[PA／VA lookup:370](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:370) | 有 8 個 `{pa,va,len}` entries；找不到時仍走 scalar affine fallback。PA fallback 用 `real_phys_size`，VA fallback 用 `gPhysSize`；segment lookup 本身不是 hole／owner validity proof。 |
| [PTOV population:1485](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:1485)・[non-PPL physmap:1590](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:1590) | entries 由 kernel／physmap protection segments 產生，保留 block offset，超過 8 entries 會 panic；non-PPL 路徑 map pre-kernel prefix 與 scalar tail。8 entries 不能解讀成「可自動接 8 個 RAM banks」。 |
| [pre-kernel release:1635](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:1635) | 原有 `ml_static_mfree(phystokv(gPhysBase), segLOWEST-gVirtBase)` 會嘗試回收整個 prefix；把 base 向下移後，prefix 裡的 holes／live owners 必須另作 exclusion。 |
| [pmap span:2207](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap.c:2207)・[pa_valid／pa_index:75](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap_data.h:75) | `vm_first_phys=gPhysBase`、`vm_last_phys=avail_end`；validity 是一個區間，PV／attribute index 是 `(PA-vm_first_phys)/PAGE_SIZE`。只跳 allocator holes、不修 validity，holes 仍被看成 managed pages。 |
| [pmap_valid_page hole TODO:11193](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap.c:11193) | owning source 明列 hole-aware implementation TODO，實作仍呼叫 scalar `pa_valid()`。 |
| [PV／attribute／PTD sizing:613](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap_data.c:613)・[pp_attr type:1097](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap_data.h:1097) | PTDs 和 per-page tables 依 scalar `mem_size` 配置；`npages=atop(mem_size)`，pp_attr 每 slot 2 bytes，PV head 每 slot 一個 pointer。metadata 要涵蓋 ordinal span，不能只用幾何 union bytes 配小表。 |
| [RAM enumeration:2593](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap.c:2593)・[pmap_next_page:2637](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap.c:2637) | free count 和 span 都以 `first_avail..avail_end` 計算，逐頁增加 `first_avail`；附近 `pmap_is_bad_ram()` 回傳 false。函式雖名為 initialize_ram_ranges，這版實作不是 bank vector。 |
| [vm_pages allocation:1433](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/vm/vm_resident.c:1433)・[initial array enumeration:1538](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/vm/vm_resident.c:1538)・[implicit PFN:422](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/vm/vm_page.h:422) | ARM64 用 free-page span 配 startup vm_pages。array 內 PFN 是 `array index + vm_first_phys_ppnum`；直接把 hole-skipping enumeration compact 到 array 會破壞 PFN，SET macro 也有相等 assert。 |
| [late vm_page_create:1694](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/vm/vm_resident.c:1694)・[explicit out-of-array PFN:413](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/vm/vm_page.h:413)・[ml_static_mfree:1760](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/machine_routines.c:1760) | VM 有 late-add 路徑，使用 fictitious-common 取得顯式 PFN 的 vm_page 再 release；ml_static_mfree 先查 mapping／修改 protections，並調 wired counters。這不是 metadata、mapping、duplicate-release 和 owner-proof 均可省略的 unrestricted hotplug。 |

## 16 KiB host admission 模型

工具直接 import 既有 inventory 的 parser 與 union／intersection／subtract helpers，沒有重寫 inventory。所有區間為 `[start,end)`；requested ranges 必須非空且 16 KiB 對齊，advertised coverage 向內取整，static／GPU／observed owner extent 向外取整。端點按 uint64 檢查，exclusive end 可以是 `2^64`，但 PFN 仍必須符合真實 type 的 uint32 bounds。[實際 ppnum_t typedef:69](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/mach/vm_types.h:69)・[ARM64 LP64 address types:103](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/mach/arm/vm_types.h:103)・[實際 admission helpers](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py:42)

每個 audited PFN 都執行 widened PFN→PA→PFN 和 bounds 檢查；scalar span 內每頁另查 dense metadata index。每個幾何 eligible page 的第一個和最後一個 byte 執行 synthetic PA→VA→PA。JSON 壓成相同決策的 runs，**不是只抽查 run 首尾 PFN**；但 PA／VA byte checks 是每頁兩點，不是整頁每 byte。[PFN trace loop](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py:244)

模型使用 `VA = 0xfffffe0000000000 + PA - scalar_span.start`，並拒絕落在非 whitelist／excluded PA 的 conversion。這只是經 bounds 檢查的 affine model：不驗證實際 ARM VA configuration、PTE、TLB、cache attributes、security permissions 或真實 PTOV segments。`actual_gVirtBase`、`actual_PTOV_entries`、`first_avail_actual`、`pmap_free_pages_actual`、`pmap_free_pages_span_actual` 均保持 `null`；`production_pmap_verified=false`。PFN 有合法型別／metadata index，絕不代表該頁可 allocate。[translation helpers](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py:122)・[trace output model](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py:307)

### Pending gate 與 live owners

- 已觀測正長度 owner extent 即使 lifetime pending 仍排除整頁；static reservations、GPU、advertised holes 或未要求區域為 `reject`。
- dynamic `size/alloc-ranges`、no-map／reusable lifetime、zero reg、memory／reserve-map 未解析項目都保留理由。allocation window 是可能的 scope，不是實際 allocation；缺失／空／零長度 scope 不能縮成零影響。
- `ranges=null` 或 owner manifest 缺失／空，維持 pending；零長度 owner tuples 不當成 complete absence。只有 `state=resolved`、`coverage_complete=true`、非空 evidence、明確 ranges 才能解除該 owner 的 host gate；`[]` 只有在上述完整 absence 證據下才表示確定沒有 extent。
- 即使 synthetic owners 全部 complete，`actual-pmap-and-board-integration` 仍固定 pending，工具不會給 production admission。未知 owner union 和最終 allocatable bytes 一律 `null`，不把 null 轉成 0，也不把所有 raw candidates 自動納入。

[owner normalization](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py:147)・[inventory pending evidence import](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py:196)

此 DTB trace 有 **69 個 evidence／owner records**：63 個 unresolved reserved-memory nodes、1 個 unresolved `/memory`、4 個未量測 live-runtime groups、1 個 board-integration gate。每個 requested bank 都有 22 個 pending IDs；其中可能配置於兩 bank 的 bounded dynamic owners 是 `demura_heap_region`、`ramoops_region`、`debug_kinfo_region`、`mem_dump_region`。其餘包括 12 個未知 placement 的 DT reservation nodes、zero `/memory` tuple，以及下列 DT 之外的 live owners：

| JSON owner ID | 尚未量測的 live PA extents |
| --- | --- |
| `live-owner-0` | loader image、BSS、stacks、page tables、heap |
| `live-owner-1` | persistent monitor core、USB／DMA buffers、monitor-owned data |
| `live-owner-2` | original／relocated FDT、payload／initrd staging buffers |
| `live-owner-3` | kernel segments、RAMDisk／trust cache、ADT、boot_args、topOfKernelData 覆蓋的 bootstrap bytes |

這些 groups 的 description、ranges、scope 和 evidence 會留在 JSON；ranges／scope／evidence 未取得時為 `null`。DT reserve-map 沒有 entries 不代表上述 owners 不存在。既有 loader 自己就有 runtime FDT／scratch 和 payload／kernel overlap checks，以及連續 ADT／boot_args staging。[FDT check](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:149)・[payload overlap](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:163)・[staging](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:178)

## 實際 DTB admission checkpoint

輸入沿用 `D:\xiaomi13\fuxi_ios\work\hw-survey\fuxi-live-20261116.dtb`，815061 bytes，SHA-256 `2d7e97ea52bf67a79ef7b99487131a41bd87fc0ab774983ce62bfb9fa79fb9fa`。JSON 同時保留 inventory 的 parser SHA-256 `55decb4c6f6b32e00fc7a3c51057cdd6c2b619baaa34ec7b70d0e7cd955b783c`。30 MiB bank 採 DT advertised geometry 作 synthetic admission fixture，**未新增手機存取證據**。

| Trace range，end exclusive | MiB | PFN start → end exclusive | PFNs | 決策 |
| --- | ---: | --- | ---: | --- |
| `[0x8b9d00000,0x8b9f00000)`，preceding context hole | 2 | `0x22e740 → 0x22e7c0` | 128 | reject，且在 raw scalar span 之外 |
| `[0x8b9f00000,0x8bbd00000)`，extra bank | 30 | `0x22e7c0 → 0x22ef40` | 1920 | defer |
| `[0x8bbd00000,0x8c0000000)`，internal hole | 67 | `0x22ef40 → 0x230000` | 4288 | reject |
| `[0x8c0000000,0xafe000000)`，current9g | 9184 | `0x230000 → 0x2bf800` | 587776 | defer，本次是新 admission proof，不否定主線 baseline |
| `[0xafe000000,0xb00000000)`，固定 GPU scratch | 32 | `0x2bf800 → 0x2c0000` | 2048 | reject |
| page-rounded static reservations，15 個 union ranges | 527.828125 | 各段列在完整 JSON | 33781 | reject，均在上述 raw scalar span 之外 |

static page-aligned union 是 **553467904 bytes**；比原 inventory static union 多 **26624 bytes**，因任何局部保留都排除整個 16 KiB page。FDT reserve-map 為空是本 DTB 的已知事實；dynamic／flags／live owners 的未知量仍為 null，沒有加總 dynamic requests 後假稱可用量。

| 數量 | 精確 bytes | MiB／其他值 | 語意 |
| --- | ---: | ---: | --- |
| raw scalar envelope `[0x8b9f00000,0xafe000000)` | 9731833856 | 9281 | span，含 67 MiB hole；不是 loader 可直接接受的 layout |
| requested union／geometry after known exclusions | 9661579264 | 9214 | 9184＋30；完整 ownership 未證，不是 allocatable total |
| requested 與已知 static／GPU exclusions 的交集 | 0 | 0 | 只是本 DT 已解析集合的交集，不是 pending owner 量 |
| pending owner union／allocatable after all owners | `null` | `null` | 未解析，不是零 |
| newly admitted | 0 | 0 | 沒有 production admission |

完整 trace 共 **41 runs**，逐一檢查 **629941 PFNs**；其中 **40245 reject**、**589696 defer**。scalar metadata indices 檢查 **593984** 頁；幾何 pages 的 synthetic PA／VA roundtrip 檢查 **589696** 頁、**1179392** 個 points。這些 checks 是 host arithmetic，沒有讀寫該 PA。

在 ARM64 LP64、PAGE_SIZE=16 KiB、沒有 maxmem／KASAN 調整的 scalar metadata 模型下，9281 MiB envelope 需要 593984 個 slots：pp_attr 為 **1187968 bytes**、page-rounded PV heads 為 **4767744 bytes**。PTD root 和 vm_pages bytes 保持 null，因 compiled struct sizes、實際 `first_avail`／bootstrap steals、PV heuristics 和配置尚未確認。

真實 bank 幾何的 compaction 反例也寫在 JSON：extra bank 最後一頁與 current bank 第一頁的實際 PFNs 為 `0x22ef3f,0x230000`；若 compact 到兩個相鄰 startup vm_pages slots，implicit PFNs 卻是 `0x22ef3f,0x22ef40`。不能把「pmap_next_page 跳 holes」當成完整修復。

## Source-backed 最小下一個 boardpatch 提案

**提案而非已套用 patch：預設關閉的 board experiment，只處理 current9g＋這個 30 MiB bank。** 優先評估「physical metadata span＋explicit whitelist/exclusions＋lower prefix late-add」而不是盲目把 base／size 改成 12g。若完整證據不能建立，保持 defer，不下放任何 PFN。

### 幾何與 metadata budgets

為使 scalar handoff base 對齊 32 MiB，下一個 host boardpatch 設計可評估 base `0x8b8000000`，end 仍為 `0xafe000000`，span `0x246000000`＝**9312 MiB**；extra bank 的邊界本身仍需 L2／L3 exclusion 處理。這只是 alignment proposal，不是已驗證 bootstrap layout；PA／VA base 要成對平移 128 MiB，保留 kernel 既有 PA／VA placement，並核對 linker／loader／bootstrap table capacity。

| proposed span 內部分類 | Range | MiB | 規則 |
| --- | --- | ---: | --- |
| 未選取的 advertised prefix | `[0x8b8000000,0x8b9d00000)` | 29 | 不加入 whitelist，不 release |
| preceding hole | `[0x8b9d00000,0x8b9f00000)` | 2 | reject |
| extra bank | `[0x8b9f00000,0x8bbd00000)` | 30 | 完整 owner／mapping／hardware proof 前 defer |
| internal hole | `[0x8bbd00000,0x8c0000000)` | 67 | reject |
| current bank | `[0x8c0000000,0xafe000000)` | 9184 | 保留原基線；新 layout proof 仍待證 |

因此 proposed span 9312 MiB，requested union 9214 MiB，**98 MiB 不在 whitelist**，不是可用量。host arithmetic 已檢查此 proposal 的 595968 scalar metadata slots、**1191936 bytes pp_attr**、**4767744 bytes page-rounded PV heads**；PTD／vm_pages／實際 allocatable totals 仍未證。

### 必須成組處理的 invariants

1. **版本化 handoff 與 live-owner ledger。** 定義 board-only 16 KiB whitelist／exclusion manifest、完整 ownership coverage、來源 hashes、phase／release-once 狀態，再由實際 consumer 使用；目前沒有這個 range-table consumer。loader 仍要求 base `0x8c0000000`、支援的 scalar size 和 32 MiB-aligned virt_base，copy 與 boot_args 都用 affine offset。必須以可稽核新 layout 驗證替代 gate，而不是刪 gate。原始與 relocated FDT／payload／monitor extents 不一定在 DT reservations。[loader gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:122)・[copy offset](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:158)・[boot_args／memSizeActual](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:188)
2. **保留 dense PV／attribute ordinal span，修正 managed-PA validity。** tables 仍覆蓋 aligned span，各 PFN index 不 compact；hole slots 不可 release，也不能因 index 存在就標 valid。`pa_valid/pmap_valid_page`、physical cache helpers 等須以完整頁 whitelist／exclusions 判定。`gPhysSize/mem_size` 若採 span 語意，不能再同時充當 allocatable bytes。所有 bootstrap metadata allocations 要證明落在連續、已清查的 current-bank tail。
3. **避免破壞 startup vm_pages implicit PFN。** 只有在 `first_avail..avail_end` 整段連續且完成 owner clearance 的條件下，才保留 existing current-tail enumeration，讓 lower 30 MiB 不進 startup compact array，VM 初始化後走顯式 PFN 的 `vm_page_create()` 路徑。需修 pre-kernel prefix release，按白名單與保留 ledger 切分；mapping／protections、managed metadata 和 duplicate-free 防護要先成立。如果 current tail 本身有洞，此捷徑不成立，需改 dense hole placeholders 或 explicit PFN lookup 的更完整 VM 方案。
4. **physmap／PTOV／bootstrap exclusion。** pre-kernel mappings、scalar tail、block／hint mappings 和 fallback conversion 不得讓 holes、GPU 或 live reservations 取得一般 RAM 存取語意；必要時拆 L2／L3 mappings。核算 PTOV permission segments 的總數而非只數 banks，驗證 8-entry limit、PA block offset、VA aperture、random slide 和 bootstrap tables。既有 padding patch已改 scalar physmap end／L1 sizing，但並未提供 range ownership。[local padding definition](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0011-sweet-physmap-alignment-padding.patch:12)・[L1 sizing](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0011-sweet-physmap-alignment-padding.patch:27)
5. **VM accounting 與 metadata overhead。** owning source 把 `max_mem=mem_size`，initial wired count 又是 `atop(max_mem)-free counts`；把 hole span 填進去會把洞算入 totals／wired baseline。要明確區分 span、advertised／installed 量、managed／reclaimable pages、bootstrap steals、late release 和 allocatable pages，處理 `mem_actual/max_mem_actual/memSizeActual` 的真實語意與 counters，不能用猜測的容量覆蓋 null。單呼叫 `vm_page_create()` 也不等同完成 wired-accounting 更新。[max_mem assignment](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/arm_vm_init.c:2204)・[initial wired accounting](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/vm/vm_resident.c:1208)・[late wired decrement](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm64/machine_routines.c:1803)
6. **GPU invariant 保持強檢查，不搬 scratch。** current GPU `[0xafe000000,0xb00000000)` 固定 32 MiB，仍完全排除一般 VM／physmap。現有 FG gate 要求 `gPhysBase==FG_RAM_BASE && gPhysSize<=FG_RAM_SIZE`；向下擴 metadata span 會使它失敗，必須改成可驗證的 span／whitelist／scratch disjoint invariant，而非關掉檢查。NC alias 的 bounded path 保留，後續 scalar physical cache guard 必須拒絕 holes；PFN shift 仍先 widen。這些耦合 production 變更需另一個有授權的 integration checkpoint，本 worker 沒有改動。[ram9g constants](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/variants/ram9g.patch:6)・[FG VM gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/fuxi-adreno/fuxi_adreno.c:658)・[NC／physical cache gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0101-fuxi-gpu-nc-cache-sync.patch:7)

下一個最小可驗收 checkpoint 應先在**當次 pinned＋applied board source** 做預設關閉的 host／build preparation：真實 C validity／index／release helpers 與本 trace 對照、每個 bootstrap allocation 和 startup array 的 PFN identity 可稽核、holes／GPU／pending owners 全拒絕、late release ledger 與 counters 守恆。取得完整 live-owner proof 和 actual boot_args／PTOV／first_avail 後，才另行評估新增 1920 頁的實機 checkpoint；目前不承諾任何新 PFN 已可用。

## 本次實際 checks 與尚待證

在 `D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc` 執行：

```powershell
python -B D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/test-fuxi-ram-admission.py -v
python -B D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-admission.py
```

**36/36 host tests 通過**，直接 import 實際 admission helpers，涵蓋 16 KiB requested／exclusion alignment、uint64 endpoints／overflow、uint32 PFN width、scalar index boundaries、每頁兩點 PA／VA roundtrip、hole／GPU／static rejection、dense-array 反例、null／empty／zero／mixed-zero owners、scope 邊界、evidence／coverage gates、live descriptions／未解析理由保存、來源 missing／hash-mismatch 和 JSON null roundtrip。[boundary tests](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/test-fuxi-ram-admission.py:28)・[roundtrip tests](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/test-fuxi-ram-admission.py:88)・[owner tests](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/test-fuxi-ram-admission.py:132)・[trace tests](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/test-fuxi-ram-admission.py:218)

default actual-DTB CLI、`--inventory-json -` stdin 入口都通過 JSON／counts／defer／null／source-hash assertions。可讀既有 inventory JSON file 的 `--inventory-json FILE`，不需要修改既有 inventory；本次 stdin 檢查在記憶體中重用其輸出，沒有新寫 inventory 檔。另複核官方 tag／commit identity、13/13 upstream Git blobs／SHA-256，以及上述 32 MiB-aligned proposal 的 whitelist／holes／metadata arithmetic。

**仍待證：**當次 board-patched compiled configuration（ARM_LARGE_MEMORY／XNU_MONITOR／KASAN／page-table granules）、actual boot_args／ADT named owners、PTOV／PTE／cache state、topOfKernelData／first_avail／free-page counts、所有 dynamic activation／placement／lifetime、live-owner 完整 PA extents、late-add accounting 與 DMA／security access，以及新 bank 和新 layout 的實機存取／穩定性。沒有 hardware writes，沒有重做主線 RAM512 測試，沒有日常部署或全 12GB 可用保證。
