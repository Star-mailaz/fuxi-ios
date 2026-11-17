# Fuxi RAM 多區整合準備

## 2026-11-16 host inventory checkpoint

輸入為使用者指定的 `D:\xiaomi13\fuxi_ios\work\hw-survey\fuxi-live-20261116.dtb`。檔案與 FDT header 的長度均為 **815061 bytes**，trailing bytes 為 0。來源 SHA-256 為 `2d7e97ea52bf67a79ef7b99487131a41bd87fc0ab774983ce62bfb9fa79fb9fa`。本 checkpoint 的測試種類為 host-only，實機容量、可存取性與 XNU 多區配置的驗證狀態均為待證。

工具沿用既有 `parse()` 和 `cells()`，另做半開區間 union、intersection 與 subtract。JSON 保留每個 node 的原始 property hex、parent cell counts、解碼範圍、零長度 tuple、保留 flags、未解析理由，以及 DTB 和 parser 的 SHA-256。整數 bytes 和 hex endpoints 是精確稽核值，MiB 浮點欄位供顯示使用。來源 parser SHA-256 為 `55decb4c6f6b32e00fc7a3c51057cdd6c2b619baaa34ec7b70d0e7cd955b783c`。[既有 parser](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-inspect-dtb.py:13) [inventory entry](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-ram-inventory.py:193)

在 `D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc` 執行下列命令可取得完整 JSON 與 host tests 結果。

```powershell
python -B tools/fuxi-ram-inventory.py ../../hw-survey/fuxi-live-20261116.dtb
python -B tools/test-fuxi-ram-inventory.py -v
```

### 可重算總量

| 量 | 精確 bytes | MiB | 語意 |
| --- | ---: | ---: | --- |
| advertised `/memory` raw decoded sum | 12543721472 | 11962.625 | DT 廣告值，實體容量解讀待證 |
| advertised `/memory` union | 12543721472 | 11962.625 | 9 個 reg tuples 中 8 個有正長度，合併後 7 段 |
| FDT reserve-map union | 0 | 0 | 此檔 reserve-map entries 為空 |
| `reserved-memory` static reg union | 553441280 | 527.802734375 | 跨所有 static nodes 去重並合併相鄰區間 |
| static reservations 與 advertised union 的交集 | 543229952 | 518.064453125 | 扣除候選時實際命中 advertised banks 的量 |
| static reservations 在 advertised union 外的部分 | 10211328 | 9.73828125 | 另列的 DT 保留區域 |
| 指定 current XNU 9g window | 9630121984 | 9184 | `[0x8c0000000, 0xafe000000)` |
| 指定 current GPU scratch | 33554432 | 32 | `[0xafe000000, 0xb00000000)` |
| 扣除已知 exclusions 後的 candidates | 2336815104 | 2228.560546875 | 15 段，動態分配與 live-overlap clearance 待證 |
| 17 個 decoded dynamic `size` requests 的加總 | 809504768 | 772.00390625 | 配置要求的算術和，實際 placement/activation/union 待證 |
| unresolved reservation union | `null` | `null` | unknown placement 和 flags lifetime 待證 |
| candidate after all reservations、certified usable、installed physical RAM | `null` | `null` | 需要額外證據 |

本 DTB 中指定 XNU 和 GPU 區間都落在 advertised union 內，兩者與已解析 static reservations 的交集為空。總量可由 `11962.625 - 518.064453125 - 9184 - 32 = 2228.560546875 MiB` 重算。JSON 的 `current_layout_checks` 同時保留動態 allocation 與 live overlaps 的未解析狀態。9g exclusion 取自使用者指定配置及既有 variant，當次手機 boot 配置待獨立確認。[9g variant](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/variants/ram9g.patch:6)

### advertised union

| Start inclusive | End exclusive | MiB |
| --- | --- | ---: |
| `0x80000000` | `0x80e00000` | 14 |
| `0x811d0000` | `0xd8000000` | 1390.1875 |
| `0xd8140000` | `0xd8160000` | 0.125 |
| `0xe7cb0000` | `0x100000000` | 387.3125 |
| `0x880000000` | `0x8b9d00000` | 925 |
| `0x8b9f00000` | `0x8bbd00000` | 30 |
| `0x8c0000000` | `0xb00000000` | 9216 |

原始 `/memory` 另含 `(0xd8800000, size=0)`。工具保存此 tuple 與未解析理由。末段由原始 `[0x8c0000000, 0x980000000)` 與 `[0x980000000, 0xb00000000)` 相鄰合併而成。上方兩個額外 bank 之間存在 **2 MiB** hole，`0x8bbd00000` 至 current base `0x8c0000000` 之間另有 **67 MiB** hole。

### candidates after known exclusions

| Start inclusive | End exclusive | MiB |
| --- | --- | ---: |
| `0x811d0000` | `0x81200000` | 0.1875 |
| `0x81480000` | `0x81a00000` | 5.5 |
| `0x81a40000` | `0x81c00000` | 1.75 |
| `0x81cf4000` | `0x81d00000` | 0.046875 |
| `0x81f20000` | `0x82600000` | 6.875 |
| `0x82800000` | `0x8a800000` | 128 |
| `0x9b09c000` | `0x9b100000` | 0.390625 |
| `0xa3080000` | `0xa4a80000` | 26 |
| `0xa4a80800` | `0xa7000000` | 37.498046875 |
| `0xa7400000` | `0xb8000000` | 268 |
| `0xbab00000` | `0xd4d00000` | 418 |
| `0xe7cb0000` | `0xff800000` | 379.3125 |
| `0xffe00000` | `0x100000000` | 2 |
| `0x880000000` | `0x8b9d00000` | 925 |
| `0x8b9f00000` | `0x8bbd00000` | 30 |

低位址 13 段合計 **1273.560546875 MiB**，current base 之前的高位址兩段合計 **955 MiB**。每段均附 `possible_dynamic_reservations`，整體還受 `unbounded_unknown_placement_nodes` 與 `live_overlaps_unverified` 約束。實際納入 VM 前需要 16 KiB page 對齊、reservation placement、存取權限與 live-owner clearance。例 `0xa4a80800` 起點含 2 KiB offset，raw candidate 的完整 byte 數與可納入的整頁量需分別驗證。

## 保留與未解析分類

`reserved-memory` 共 65 個 nodes。其中 37 個有 static `reg`，35 個含正長度，另兩個 `demura_region_0/1` 為 literal zero reg。所有正長度 static reg 都納入去重 union。`no-map` 共 43 個 nodes、`reusable` 共 17 個 nodes，其原始 flags 和 XNU mapping/reclaim lifetime 未解析理由逐 node 保留。flags 的計數與 static/dynamic 分類存在重疊。

17 個 nodes 有 dynamic `size`，18 個 nodes 有 `alloc-ranges`。`ramoops_region` 提供 allocation window 而其 requested size 缺失。低位候選的 JSON 逐段列出 16 個可能配置於該處的 dynamic nodes。高位兩個候選可能命中 `demura_heap_region`、`mem_dump_region`、`ramoops_region`、`debug_kinfo_region` 的 allocation windows。前兩者分別要求 40 MiB、52 MiB，後兩者的 window 可跨低位和高位 banks。配置位置、是否啟用、重疊 union 和可回收時機均待證。

12 個 nodes 的物理 placement 缺乏可解析的 positive reg 或 allocation window，包括 `xbl_dt_log_merged@81a00000`、六個 `trust_ui_vm_*` nodes、三個 `oem_vm_*` nodes，以及兩個 zero-reg `demura_region_*` nodes。帶 `@address` 的 node name 只作名稱保存。這些未知保留量以 `null` 呈現，candidate 的最終可用量持續待證。

此檔 `/` 與 `/reserved-memory` 都是 `#address-cells=2`、`#size-cells=2`，後者 `ranges` 為空，identity address translation 可解析。工具對 cell counts 不同、缺失或非空 `ranges`、unsupported widths、malformed tuple、64-bit overflow 和 nested-bus memory 都保留原始資料及未解析理由。相對 bus 位址的 physical translation 需要另補證據。

## single-contiguous owning sources

目前 handoff 用一組 base/size 描述 kernel window。把同一 base 的 bank span 設為 12 GiB，end 會成為 `0xbc0000000`，此 DTB 的相鄰 advertised span 則止於 `0xb00000000`。925 MiB 與 30 MiB 的兩個候選位於既有 base 之前，納入時還要表示兩個 holes。9g 數值的來源是目前 layout 及 scratch 邊界，手機 12GB 容量的整合仍需以下 owning invariants 的證據。

| Owning source | 已查得的 invariant | 多 range 待證點 |
| --- | --- | --- |
| `tools/mkadt-fuxi.py` 的 `PHYS_BASE`、`BANK_SIZE`、`configure_ram` | 固定 base，bank span 選項為 `full` 與 `9g`，`MEM_SIZE = BANK_SIZE - GPU_SIZE` | noncontiguous banks 與每個 hole 的 ADT/VM 表示方式 |
| `tools/mkadt-fuxi.py` 的 `memory_contains`、`validate_live` | 可以合併相鄰 advertised banks 證明 requested span 連續，實際驗證採一個 `PHYS_BASE/BANK_SIZE` | reservation placement 與 live-owner extents 的 complete exclusion |
| `tools/mkpayload.py` 的 `adt_dram`、header pack | 由 `/chosen` 取一組 `dram-base/dram-size`，payload header 寫一組 `PHYS_BASE/MEM_SIZE` | range table 的傳遞、版本與既有 callers |
| `shim/fuxi-loader/loader.c` 的 payload/boot_args、layout gate | 一組 `physBase/memSize`，base 等於 `0x8c0000000`，size 等於支援的 span | 多區 handoff、bootstrap image placement、重試或失敗前 exclusion |
| `shim/fuxi-loader/loader.c` 的 segment copy 與 top | `PA = VA + phys_base - virt_base`，ADT/boot_args 接在 kernel_end，topOfKernelData 由一個連續序列推導 | 額外 banks 的 PA/VA translation 及分段 staging 所有權 |
| `xnu/variants/ram9g.patch`、`xnu/fuxi-adreno/fuxi_adreno.c` | `FG_RAM_BASE=0x8c0000000`，`FG_RAM_SIZE=0x23e000000`，GPU gate 檢查 `gPhysBase` 相等和 `gPhysSize <= FG_RAM_SIZE` | 多段 physical memory 的整體表示及 scratch exclusion 能否維持正確 |
| `xnu/patches/0101-fuxi-gpu-nc-cache-sync.patch` | physical cache path 先查 NC alias，再用 `gPhysBase/gPhysSize` 作單區間判斷，PFN 先 widen 再 shift | 新 bank、holes、PFN width、cache attribute 與 physical helper 的合法範圍 |
| `xnu/patches/0011-sweet-physmap-alignment-padding.patch` | physmap L1 count 和 end 以 scalar `real_phys_size` 加 slide/padding 決定，padding 依 `PTOV_TABLE_SIZE * ARM_TT_TWIG_SIZE` | per-range PTOV entries、VA aperture、對齊 padding、page-table capacity 與 sparse PFNs |
| `tools/fuxi-xnu-monitor.py` | base/size gate 與 `read_ram` 以 current window 的 offset 及 4 GiB request banks 解碼 | 額外 PA banks 的讀取協定、symbol translation、holes 邊界 |

ADT 的 source positions 為 constants/configure、continuous coverage 和 validator。來源連結附精確起始行。[mkadt constants](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/mkadt-fuxi.py:27) [coverage](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/mkadt-fuxi.py:46) [validator](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/mkadt-fuxi.py:67)

Payload 與 loader 的一組 base/size、線性 segment placement、topOfKernelData handoff 可直接從 owning code 追蹤。[ADT dram reader](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/mkpayload.py:240) [payload header pack](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/mkpayload.py:323) [loader boot_args](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:35) [layout gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:122) [segment copy](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:158) [top handoff](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:178)

FG/gPhys range gate、pmap physical cache gate 和 physmap sizing 的來源位置如下。[9g variant](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/variants/ram9g.patch:6) [FG VM bound gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/fuxi-adreno/fuxi_adreno.c:658) [pmap cache gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0101-fuxi-gpu-nc-cache-sync.patch:7) [physmap padding](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0011-sweet-physmap-alignment-padding.patch:12) [physmap L1 sizing](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0011-sweet-physmap-alignment-padding.patch:27) [physmap end](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0011-sweet-physmap-alignment-padding.patch:33)

Monitor 的 owning gate 和 offset decoder 分別位於 payload geometry 檢查與 `read_ram`。[monitor geometry](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-xnu-monitor.py:183) [monitor read_ram](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-xnu-monitor.py:212)

### pinned XNU 與完整原碼缺口

CI checkout 的 blacktop builder pin 為 `663906528d1cd5ea8fde7de6f16de73db9511549`，CI 選擇 `MACOS_VERSION=13.5`。native recipe 的 `RC_ProjectSourceVersion` 為 `8796.141.3`。9g variant 經 `FUXI_RAM_LAYOUT=9g` 選入 required patch。這些是 source selection 與 patch application 的 owning 證據，當次 CI 輸出仍須對應其 source/inputs manifest。[builder pin](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/ci/pins.env:2) [CI source selection](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/ci/build.sh:279) [native version](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/build-fuxi-native.sh:25) [variant staging](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/ci/prepare-kernel.py:30)

本次所查 `ksrc/xnu`、`work/kdraws-src/xnu` 與 `work/adsp-battery/xnu-base` 缺少完整 `osfmk/arm64/arm_vm_init.c`、`osfmk/arm/pmap/pmap.c`、`osfmk/vm/vm_resident.c` 和 `pexpert/pexpert/arm64/boot.h`。因此 `gPhysBase/gPhysSize` 初始化、VM bootstrap free-page enumeration、pmap PV metadata/PFN indexing、PTOV population、bootstrap identity mappings 和 actual board configuration 的多區行為均列待證。此處 physmap 的結論限於已讀 owning patch 所呈現的 sizing expressions。

## DT 之外的 live-overlap 待證

Loader link layout 包含 BSS、兩個各 `0x8000` bytes 的 stacks、embedded payload 和 `_image_end`。link 起點為相對位址 0，實際 load address 和 end 要由該次 image manifest、symbols 或 handoff report 求得。持續執行的 monitor core 還持有 USB/DMA buffers、report data 及可能的 page tables/heap。這些 live owners 的精確 PA extents 需要獨立清查。[loader link layout](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.ld:8) [monitor core ownership](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/mkadt-fuxi.py:144)

Loader 以 runtime `probe_fdt_address()/probe_fdt_bytes()` 檢查 FDT 與 scratch overlap，並以 `_payload_start/_payload_end` 檢查 embedded staging 與 kernel window overlap。候選加入需要對每個 proposed range 做完整 live-owner comparison。原始/relocated FDT、payload/initrd source buffers、kernel segments、RAMDisk/trust cache、ADT、boot_args 和 `topOfKernelData` 所覆蓋 bootstrap bytes 都需列入。這些保留可能由 loader 或 ADT memory-map 生成，其 coverage 需與輸入 DTB 另外核對。[runtime FDT/scratch check](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:149) [payload/kernel check](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:163) [RAMDisk/trust-cache staging](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/mkpayload.py:289) [ADT/boot_args placement](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/shim/fuxi-loader/loader.c:178)

## 最小可行下一個 checkpoint

下一個 checkpoint 為 host-only 的「current window 加一個額外 bank」來源追蹤與 admission 模型。先用本 DTB 的 30 MiB bank `[0x8b9f00000, 0x8bbd00000)` 作 synthetic fixture，真實 admission 狀態持續由 pending reservations 決定。

1. 取得與 CI source selection 和 inputs manifest 對應的完整 XNU source，對 `gPhysBase/gPhysSize`、free-page enumeration、PTOV/PV population 和 board page-table configuration 標出精確 owning 行號。
2. 以 canonical 16 KiB-aligned PA ranges 建立 host admission trace，涵蓋 current XNU window、30 MiB synthetic bank、兩個 holes、static reserve union、GPU 32 MiB window，以及 pending dynamic/live owners。pending owner 須有明確未解析結果。
3. trace 檢查每個交給 allocator 的 PFN 都有 advertised coverage 與 exclusion clearance，每個 PA/VA conversion 可來回，每個 hole/GPU/monitor extent 皆有正確邊界，且 PFN shift、size arithmetic 與 endpoints 無截斷。
4. 由 owning source 決定額外 bank 所需的 handoff representation、sparse allocator/pmap metadata 和 monitor read semantics。checkpoint 的可驗收結果為具 source/line provenance 的 host trace 與通過的 boundary fixtures。

後續多區支持還須驗證 boot_args/ADT range-table consumer、bootstrap mapping coverage、available-page accounting、PTOV entry capacity、physmap aperture sizing、PV indexing/PFN widths、cache attributes、static allocation/topOfKernelData lifetime、warm/retry paths、DMA addressability 和 security access rights。實機整體可用容量及所有 candidates 的 admission 留待這些證據完成。

## Host validation

`python -B tools/test-fuxi-ram-inventory.py -v` 通過 **20 tests**。測試涵蓋 overlap/adjacency/duplicates union、subtract/intersection、holes、empty/zero-size、64-bit overflow 和 full-address-space union、fragmented banks、current9g/GPU exclusion、current-window holes/conflicts、reserve-map/static reg 去重、dynamic/missing/zero reservations、cell mismatch/default widths、malformed tuples/size、address translation 未解析、reservations outside advertised banks，以及 DTB hash/parser reuse。另以 200 組固定 seed 小位址集合驗證 subtract 與逐 byte set difference 相符。Python syntax 與 trailing whitespace 檢查通過。[range host tests](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/test-fuxi-ram-inventory.py:65) [synthetic FDT tests](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/test-fuxi-ram-inventory.py:124)
