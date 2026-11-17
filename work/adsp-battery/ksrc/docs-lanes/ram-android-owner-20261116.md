# Fuxi 8/12GB SKU、Android owners 與 30MiB shadow 提案

日期：2026-11-16。這是 host-only evidence／source／算法 checkpoint，不是新增 RAM admission。只新增本文件；RAM shadow 四檔已由主代理提交於 `27bb0cf5536d1ad2d9826b273ca48a0f9b49bf99` 並 freeze。本 worker 不改 loader／shim／mkadt／GPU／sync／其他 agents 檔案，不操作手機、鎖、adb／fastboot、commit／push。文件只保留摘要、hash 與 owning references，不收錄或發布 raw DTB、private memory capture、payload／boot image。

## 先分 SKU，再分 layout

**目前連接設備是使用者確認的 12GB 版。主代理另在當前 live FDT 的 `/memory` property `ddr_size` 確認四個 bytes `0000000c`，按 big-endian u32 解碼為 12。** 本輪 `ro.boot.ddr_size` 無值不表示 8GB，更不能用 `/memory` union 或 `MemTotal` 猜 SKU。

| 項目 | 12GB SKU | 8GB SKU |
| --- | --- | --- |
| identity／topology evidence | 使用者確認＋live FDT `ddr_size=12`，現有 capture 僅適用此 SKU | 無 captured DTB、獨立 live map、boot 或 hardware test；unsupported／fail-closed |
| 現行 layout | `usable9g` 是 `[0x8c0000000,0xafe000000)`＝9184MiB 階段窗口，不是 12GB 整合終點 | 不複用 12GB PA topology；也不把現有 `full`／5GiB 窗口叫作 8GB profile |
| GPU scratch | 此 12GB layout 的 `[0xafe000000,0xb00000000)`＝32MiB，固定排除 | scratch base／size／owners 未證；不得硬編 `0xafe000000` 或猜另一個 PA |
| counters | physical SKU、DT advertisement、metadata span、managed／allocatable／free bytes 分開 | 必須取得自己的 advertisement、保留 union、usable counters；目前未知量維持 null |
| 允許的下一步 | 繼續 12GB 共用 driver／host proof／小 bank 準備 | 只做辨識與拒絕 regression；不 build 可 boot 候選 |

12GB 上縮小 available memory，可測共用 driver、allocation 壓力與 SKU／越界拒絕；**不是 8GB 真實 topology／owner validation 或正式 8GB 驗收**。正式 8GB 驗收最後仍需 8GB 實機；不讓尚缺的 8GB 證據阻擋 12GB 的 bounded 準備。

主代理 owns `tools/mkadt-fuxi.py`、`tools/test-fuxi-ram9g.py` 與兩個 work/prepare loaders 的 SKU/layout 分離和 metadata；本文件不代改。`physical_sku=12g` 與 `usable_layout=9g` 是不同欄位，不把一個 size selector 當 SKU。主代理回報 9184MiB 日常 chain-v6 已部署；這不是全 RAM、全 12GB 或 8GB 的硬體驗收。

**12g/9g image 絕不能在 8GB 上進入 XNU／GPU staging。** Host packer 的 SKU gate 不替代 runtime FDT guard：入口須在任何 kernel／scratch 寫入之前，驗證傳入 FDT、唯一合法 `ddr_size` 的 big-endian u32、image SKU 相符，以及該 SKU 的 live advertised ranges／reserved extents。missing／malformed／conflict／8GB unsupported 必須停止 XNU 路徑，不能 fallback 到 12GB PA 常數。此處是 guard contract，尚未宣稱已接入部署影像。

## 當前 Android capture 對照

Capture 時間為 `2026-11-16T16:05:37.896075+08:00`。本 worker 只讀 host copy，五個 records 的長度與 SHA-256 均已核對。來源 manifest：[memory.json](D:/xiaomi13/fuxi_ios/work/adsp-battery/android-memory-20261116-1606/memory.json:3)。

| 輸入／視圖 | 本次數字／狀態 | 不能推出的結論 |
| --- | --- | --- |
| iomem.txt | 12217 bytes；SHA-256 `01f9cf713d9327d5c4eabe25a3c695ea6bf4dab6535b5394508929784f1780fe` | 不是完整的 dynamic／firmware／iOS owners manifest |
| meminfo.txt | 1234 bytes；SHA-256 `c00259db11de24928c061b202813cdac5c6347d7041aa1dcabbdb9c60410a2e6` | 不代表每頁均可供 XNU 使用 |
| Android System RAM union | 14 段，12049768448 bytes＝11491.5546875MiB | 包含列於其內的 reserved children，不是 free RAM |
| Linux MemTotal | 11459124KiB＝11190.55078125MiB | OS managed 視圖，不是 physical SKU 或 XNU allocatable |
| Linux CmaTotal | 790528KiB＝772MiB，CmaFree 為 0 | 不與候選／DT dynamic size requests 相加減，不視為額外空閒 bank |
| memblock-memory／reserved | 兩者皆 `MISSING_READ_ONLY_INTERFACE` | missing 不表示零保留或 owner coverage complete |
| DT advertisement union | 12543721472 bytes＝11962.625MiB | 此數不是焊接 DRAM 總量／全 12GB 可加入 VM 的證明 |

DT host reference SHA-256 為 `2d7e97ea52bf67a79ef7b99487131a41bd87fc0ab774983ce62bfb9fa79fb9fa`；本 worker 用既有 [parser](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/fuxi-inspect-dtb.py:13) 再核對 `/memory/ddr_size`，確為 `0000000c`／big-endian u32 12。reuse inventory 和 union/intersection/subtract，不另發布 DTB。iomem 的 inclusive end 先加一轉成 `[start,end)`，再對 parent／child 重疊及相鄰去重。所有本次 System RAM 均在 DT advertised union 內。

| DT 幾何候選 `[start,end)` | MiB | 與 Android 已列 owners 的 raw byte-union 交集 MiB |
| --- | ---: | ---: |
| `[0x880000000,0x8b9d00000)` | 925 | 0；完整列於 System RAM，但 absence／lifetime 未證 |
| `[0x8b9f00000,0x8bbd00000)` | 30 | 0；同上，仍 defer |
| `[0xa7400000,0xb8000000)` | 268 | 78.515625，Kernel code／data 與 reserved |
| `[0xbab00000,0xd4d00000)` | 418 | 364，reserved |
| `[0xe7cb0000,0xff800000)` | 379.3125 | 316，reserved |

來源：[高位兩 banks](D:/xiaomi13/fuxi_ios/work/adsp-battery/android-memory-20261116-1606/iomem.txt:294)・[Linux kernel owners](D:/xiaomi13/fuxi_ios/work/adsp-battery/android-memory-20261116-1606/iomem.txt:278)・[MemTotal](D:/xiaomi13/fuxi_ios/work/adsp-battery/android-memory-20261116-1606/meminfo.txt:1)。全部 15 個 DT 候選合計 2336815104 bytes＝2228.560546875MiB，其中 Android 已列 owners 交集為 795361280 bytes＝758.515625MiB；**相減不是可 admit 量**。另有 `[0xa4a80800,0xa4a81000)` 的 2KiB 不在 Android System RAM，16KiB replay 必須排除不完整頁。

目前 9184MiB 窗口內 Android reserved union 是 328122368 bytes＝312.921875MiB；GPU 固定 32MiB 全落於 Android reserved union，末尾重複 parent/child 不重算。這些是 Android 當前 phase 的觀測，不意味日常 XNU 的同位址持久佔用，也不據此縮改主線窗口。

**925 與 30MiB 是兩個各自 contiguous 的 lower banks，合起來不是 contiguous：** 中間 `[0x8b9d00000,0x8b9f00000)` 有 2MiB hole；30MiB 與 current bank 間 `[0x8bbd00000,0x8c0000000)` 有 67MiB hole。高位兩個候選仍可能命中 `demura_heap_region`、`mem_dump_region`、`ramoops_region`、`debug_kinfo_region` 的 allocation windows；unknown placement、zero reg、no-map／reusable lifetime 仍 pending。沒有 child owner 標籤不表示無 owner。

Android capture 沒有解除 iOS loader／persistent monitor／USB DMA／original及relocated FDT／payload／kernel、ADT、boot_args staging 的 owner gate。`persistent_owner_clearance_verified=false`、`xnu_admission_verified=false`、`allocatable_after_all_owners_bytes=null`；任何下一個 shadow replay 都必須保存 phase、source hash、未解析理由及 coverage，不能將 null 改成 0。

既有 [actual-trace checkpoint](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/docs-lanes/ram-admission-checkpoint.md:83) 的 **69 個 pending evidence／owner records**（63 unresolved reserved-memory、1 unresolved `/memory`、4 live-runtime groups、1 integration gate）仍保留；不是 69 個可相加的保留量，也不是每頁都與 69 個 owner 重疊。本輪 owner observations／native synthetic bits 不解除這些 records，不重做或修改 frozen trace／ledger：`pending=69`、`shadow_released_pages=0`、`allocatable_bytes=null`，沒有 VM release。

## 本輪下一個最小邊界

只評估 12GB 的 30MiB／1920 PFNs，不加入 925MiB，不移 GPU scratch，不改已部署 9184MiB 窗口。本輪後續 source／native proof 只允許 query／分類／計畫，不呼叫 `vm_page_create`、`ml_static_mfree` 或 free-list release；production pmap／PTE／cache state 仍未證。

### 已查 chain-v6／shim owners

不能只讀 development ksrc 而假定它就是部署 shim：[chain builder](D:/xiaomi13/fuxi_ios/work/boot-chain/build-chain.py:28) 的 source 是 `D:/xiaomi13/fuxi_ios/ios-fuxi/shim`，chain-v6 使用 `native-dly-ram9g-batfresh-sb127-loader` 的 loader/payload objects。[build record](D:/xiaomi13/fuxi_ios/work/boot-chain/chain-v6-ram9g-batfresh/build.txt:3)

| Owner／邊界 | 本輪 host 核對 | 925／30MiB 結論 |
| --- | --- | --- |
| 完整 chain image | stored monitor `before.json` 的 `[0xa8000000,0xabfe0000)`，66977792 bytes；與 loader.elf `_head/_end/_image_end` symbol offsets 一致 | 兩 bank 都無交集；只綁定該 boot record，不是所有未來 load placements |
| BSS／stacks／USB DMA | BSS `[0xa8044000,0xa8074000)`；兩 stacks 在其後、payload 前；16KiB `dma_area` 在 `[0xa8070000,0xa8074000)` | 全在上述 image 內；DMA lifetime 不能因 XNU launch 就當作結束 |
| embedded payload／Linux footprint | payload `[0xa8084000,0xa914cff0)`；Linux 由 `0xa9200000` 起，image header footprint 止於 `0xabfe0000` | 兩 bank 都無交集；不收錄原始 payload/boot image |
| kernel／ADT／boot_args destination | payload header 經原 owning affine 公式得 ADT `0x8c2790000`、boot_args `0x8c2794000`、top `0x8c2798000`；kernel destination 在 current bank | 兩 bank 都無交集；不是 free-page／metadata allocation clearance |
| runtime original FDT | probe 保存 pointer/length，但此 stored `before.json` 沒有其 extent；`probe_fdt` symbol 的 PA 只是 pointer 變數地址 | **unknown／pending，不能把變數地址當 FDT extent**；仍可能妨礙任一新 bank |

來源：[stored MON_IMAGE/MON_END](D:/xiaomi13/fuxi_ios/work/Codex-Xiaomi13-GPU-20261109/native-hw000chainv6-ram9g-batfresh-boot-1/before.json:11)・[chain linker footprint](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader-chain.ld:13)・[USB static buffer](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:37)・[DMA pointer](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1426)・[persistent secondary loop](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:780)・[FDT pointer](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1547)・[destination gate](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:120)・[ADT/top formula](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:177)。

可審計 hashes：`before.json`＝`44ae548d5adcac33b0843a1b08c4ad1452bff5cb016127ef3740d984a49a7da2`；chain `loader.elf`＝`b5ce327c9301c98889ba9f2ab130fc93d3682b849b29c4e0f264551b768c4c45`；loader `memory-layout.json`＝`70cf7cb52d0cfa4c0ad24199c93cdd5ce2f6608b3026dbc433b6ba1df89b6317`。只讀既有檔案／ELF symbols，沒有 build/deploy chain。

在本輪讀到的 source 中，probe 只驗 FDT magic/total length，loader 驗 scalar layout 和 GPU/FDT overlap；**沒有 `/memory/ddr_size` runtime SKU gate**。chain 的 invalid FDT/initrd 可沿原 fallback 走 XNU，因此 chain mode decision 不能充當 SKU guard。[probe entry](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1533)・[GPU staging 前](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:149)・[chain selection](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/chain.c:133)。這是只讀研究時的狀態，不宣稱主代理後續 guard 已部署；本 worker 不代改入口。

### 實際 applied owning-file replay

既有官方 tag [xnu-8796.141.3](https://github.com/apple-oss-distributions/xnu/tree/xnu-8796.141.3)，commit `1b191cb58250d0705d8a51287127505aa4bc0789`。在 TemporaryDirectory 複製六個必要公開 owning files，再按照 [prepare-kernel](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/tools/ci/prepare-kernel.py:16) 的 lexicographic required-patch 順序，對命中這六檔的 `0008,0010,0011,0012,0082,0101` **逐個實際 `git apply --check`／`git apply`**，未執行 provider/build scripts。9g variant 修改 FG constants，未命中這六檔。本輪 generator SHA-256 為 `efbcf409234ba6134bc20b5c441fbdf00b70b613528d0461c5a4e4edd8b75ee4`。

這補足純 official source 不能代表 local applied modifications 的缺口；**仍是六檔 source-level replay，不是完整當次 CI tree／headers／compiled configuration 或部署 kernel 的重建證明**。沒有新建持久 source cache，也沒有改 generator／production tree。

| Applied view | SHA-256 | 實際行號／不變量 |
| --- | --- | --- |
| `osfmk/arm64/arm_vm_init.c` | `b2de540a9c87c68cfa05305e419c1cf0b026da1f983d8ae372326338e01f3b6a` | 1871 base、1886 size；1901／1925 physmap capacity；1636 scalar prefix release |
| `osfmk/arm/pmap/pmap.c` | `39f0124dda9e52ad167bf6c69a6d50f11cb777a1ee2b59b45c30e4a90c0b98bb` | 2207 PV origin；2593 count、2617 span、2637 next_page；11216 valid_page 仍 scalar |
| `osfmk/arm/pmap/pmap_data.h` | `26f464e4dc2dd71da80d1155f7314a8f107d0a8be54965ac03def390a7dadc17` | 75 `pa_valid`、98 `pa_index`，未改的實際 bodies |
| `osfmk/arm/pmap/pmap_data.c` | `564ee64643bc22d66a36734fa75c3967fca7f592b3dd4f1c1c41160db7742b67` | 613 PTD heuristics、633 dense npages；tables 由 scalar mem_size 配置 |
| `osfmk/vm/vm_resident.c` | `0c0dd352efef32cb032cd0a84f77cce77ba77a90412420df76d2e0f5e9ea81e1` | 1208 wired accounting；1433 vm_pages span；1556 first PFN；1694 explicit late create |
| `osfmk/vm/vm_page.h` | `527fc93aaf8c5fa8f66c6ca213d8b9fc59dd924f5af0ad45d55424f8051334a3` | 422 array PFN＝index＋first；out-of-array 用顯式 PFN |

後四檔沒有被本輪命中 patches 改動，精確 local owning references 可直接使用：[pa_valid/index](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap_data.h:75)・[PV sizing](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap_data.c:633)・[startup enumeration](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/vm/vm_resident.c:1538)・[PFN identity](D:/xiaomi13/fuxi_ios/work/adsp-battery/ram-source-reference/xnu-8796.141.3/osfmk/vm/vm_page.h:422)。前兩檔的 applied 行號是上述 hash 綁定的生成 view，不假裝它們仍等於 official 行號；修改來源：[physmap padding](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0011-sweet-physmap-alignment-padding.patch:1)・[Fuxi conversion](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0082-fuxi-ram-bringup.patch:1)・[physical cache gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0101-fuxi-gpu-nc-cache-sync.patch:7)。

### 30MiB 最小算法／只列五個耦合修改點

1. **SKU/owner gate 在先。** 僅 user/live-FDT 確認的 12GB profile 可做此 geometry；8GB／missing／conflict 拒絕。original FDT、monitor lifetime、上述四個 dynamic windows 及 unknown owners 未清查前，新 bank 一律 defer。guard 不替換主代理 packer/loader 工作。
2. **metadata span 與 managed/free eligibility 分開。** proposal 為 `[0x8b8000000,0xafe000000)`＝9312MiB／595968 dense slots，白名單只含 current9184＋extra30＝589696 pages。29MiB 未選 prefix＋2/67MiB holes＝98MiB／6272 slots 不能 release。`pa_valid/pa_index`／PV sizing 必須協同；kernel、ADT、bootstrap metadata 等已管理 wired pages不能因「不是 free」就被 `pa_valid` 誤拒絕，holes／GPU 則不成為 managed RAM。pp_attr budget＝1191936 bytes、LP64 page-rounded PV heads＝4767744 bytes；PTD／vm_pages／actual free totals 仍待 compiled sizes/first_avail，不能填零。
3. **physmap 與 prefix release 按 whitelist 切段。** 若採 aligned base proposal，PA/VA base 須成對下移 128MiB，保留既有 image PA/VA offset；不是直接修改 12g size。applied arm_vm_init 的 scalar prefix mapping/release 必須拆分，不得 map/free 29＋2＋67MiB；30MiB 邊界需 16KiB/L3 handling，並重新驗 PTOV segments、8-entry/VA capacity 及 GPU NC alias。既有 [FG base/size gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/fuxi-adreno/fuxi_adreno.c:659)／[physical cache scalar gate](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/xnu/patches/0101-fuxi-gpu-nc-cache-sync.patch:7) 也需改成明確的 span/managed/scratch-disjoint invariant，不能關掉檢查或搬 GPU。
4. **startup vm_pages 不 compact 跨洞。** 保留已清查、contiguous current `first_avail..avail_end` startup tail；30MiB 不塞進其 implicit-PFN array。extra PFNs 是 `[0x22e7c0,0x22ef40)`，1920 頁；current 首 PFN `0x230000`，不是 extra end `0x22ef40`。若 current tail 也有洞，此捷徑不成立。owner/metadata/mapping 全完成後才另外評估 explicit `vm_page_create` 路徑，不能拿跳洞的 pmap_next_page 當完整修復。
5. **release-once/accounting 才是 admission 邊界。** 下列 native patch 只產生 shadow 計畫，不接 VM；未來 consumer 必須整段 preflight、phase/lifetime clear、單次 release 和 counter 守恆。span 不可直接灌入 `max_mem` 的 wired formula；不能把 6272 hole slots、925MiB 未選 bank 或 772MiB requests/CMA 變成 free count。現有 frozen ledger 可作獨立 oracle，不修改它或假稱它已有 wire-format/boot consumer。

### Native patch 草案：只新增 shadow query，原 helpers 不動

以下 diff 的目標是 replay 後的 `pmap_data.h`；`pa_valid/pa_index` 完全保留。default query 只 reject/defer；`FUXI_RAM30_HOST_PROOF=1` 僅供 native fixture 產生 hypothetic plan，和 `FUXI` 一起編譯會直接 `#error`。沒有 allocator、mapping、boot registration 或可 boot 8GB profile。三個 proof bits 是 host assertion（1＝iOS owners，2＝pmap/dense metadata，4＝VM PFN/accounting），不是證據驗證器；本次實際 evidence 未設齊這三 bits。

```diff
--- a/osfmk/arm/pmap/pmap_data.h
+++ b/osfmk/arm/pmap/pmap_data.h
@@ -99,7 +99,55 @@ pa_index(pmap_paddr_t pa)
 {
 	return (unsigned int)atop(pa - vm_first_phys);
 }
 
+#ifndef FUXI_RAM30_HOST_PROOF
+#define FUXI_RAM30_HOST_PROOF 0
+#endif
+#if defined(FUXI) && FUXI_RAM30_HOST_PROOF
+#error FUXI_RAM30_HOST_PROOF_is_not_a_boot_feature
+#endif
+
+enum fuxi_ram30_shadow_action {
+    FUXI_RAM30_REJECT,
+    FUXI_RAM30_DEFER,
+    FUXI_RAM30_CURRENT_GEOMETRY,
+    FUXI_RAM30_PLAN_EXPLICIT_PFN
+};
+
+static inline bool
+fuxi_ram30_sku_matches(uint32_t image_sku, const uint8_t *ddr_size,
+    unsigned int property_bytes)
+{
+    if (image_sku != 12 || !ddr_size || property_bytes != 4)
+        return false;
+    uint32_t live_sku = (uint32_t)ddr_size[0] << 24 | (uint32_t)ddr_size[1] << 16 |
+        (uint32_t)ddr_size[2] << 8 | ddr_size[3];
+    return live_sku == 12;
+}
+
+static inline enum fuxi_ram30_shadow_action
+fuxi_ram30_shadow_pa(uint32_t image_sku, const uint8_t *ddr_size,
+    unsigned int property_bytes, uint64_t pa, const unsigned int *ios_proofs,
+    unsigned int *metadata_index)
+{
+    const uint64_t metadata_base = 0x8b8000000ULL;
+    const uint64_t bank_start = 0x8b9f00000ULL;
+    const uint64_t bank_end = 0x8bbd00000ULL;
+    const uint64_t current_start = 0x8c0000000ULL;
+    const uint64_t current_end = 0xafe000000ULL;
+    if (PAGE_SIZE != 0x4000 || !metadata_index || (pa & 0x3fffULL) ||
+        (pa >> 14) > 0xffffffffULL || !fuxi_ram30_sku_matches(image_sku, ddr_size, property_bytes))
+        return FUXI_RAM30_REJECT;
+    bool extra = pa >= bank_start && pa < bank_end;
+    bool current = pa >= current_start && pa < current_end;
+    if (!extra && !current)
+        return FUXI_RAM30_REJECT;
+    *metadata_index = (unsigned int)((pa - metadata_base) >> 14);
+    if (!ios_proofs || *ios_proofs != 7 || !FUXI_RAM30_HOST_PROOF)
+        return FUXI_RAM30_DEFER;
+    return extra ? FUXI_RAM30_PLAN_EXPLICIT_PFN : FUXI_RAM30_CURRENT_GEOMETRY;
+}
+
 /* See the definition of pv_head_table for more information. */
 extern pv_entry_t **pv_head_table;
 
```

### Native driver：公開 fixtures，不讀 DTB/cache

此 driver 的 `pa_valid/pa_index` bodies 與上表已 applied 的 owning source 完全相同；其 globals／PAGE_SIZE 是 host fixture，不冒充 actual boot_args。`ram30-shadow-body.h` 由前述 diff 的 added lines 取得。

```c
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define PAGE_SIZE UINT64_C(0x4000)
#define atop(value) ((value) >> 14)
typedef uint64_t pmap_paddr_t;
static pmap_paddr_t vm_first_phys = UINT64_C(0x8c0000000);
static pmap_paddr_t vm_last_phys = UINT64_C(0xafe000000);
static inline bool
pa_valid(pmap_paddr_t pa)
{
	return (pa >= vm_first_phys) && (pa < vm_last_phys);
}
static inline unsigned int
pa_index(pmap_paddr_t pa)
{
	return (unsigned int)atop(pa - vm_first_phys);
}
#include "ram30-shadow-body.h"
static uint64_t checks;
#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "FAIL %d: %s\n", __LINE__, #condition); exit(1); } checks++; } while (0)
int main(int argument_count, char **arguments)
{
    if (argument_count == 2 && !strcmp(arguments[1], "asan-canary")) {
        volatile uint8_t *canary = malloc(1);
        CHECK(canary != NULL);
        canary[1] = 1;
        free((void *)canary);
        return 0;
    }
    CHECK(argument_count == 1);
    const uint8_t sku12[] = {0, 0, 0, 12}, sku8[] = {0, 0, 0, 8}, little[] = {12, 0, 0, 0};
    const unsigned int complete = 7, pending = 0;
    unsigned int ordinal = UINT32_MAX;
    CHECK(fuxi_ram30_sku_matches(12, sku12, 4));
    CHECK(!fuxi_ram30_sku_matches(8, sku8, 4) && !fuxi_ram30_sku_matches(8, sku12, 4));
    CHECK(!fuxi_ram30_sku_matches(12, sku8, 4) && !fuxi_ram30_sku_matches(12, little, 4));
    CHECK(!fuxi_ram30_sku_matches(12, NULL, 4) && !fuxi_ram30_sku_matches(12, sku12, 3));
    CHECK(!fuxi_ram30_sku_matches(12, sku12, 5) && !fuxi_ram30_sku_matches(0, sku12, 4));
    CHECK(!pa_valid(UINT64_C(0x8b9f00000)) && pa_valid(UINT64_C(0x8c0000000)));
    CHECK(pa_index(UINT64_C(0x8c0000000)) == 0);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_C(0x8b9f00000), NULL, &ordinal) == FUXI_RAM30_DEFER && ordinal == 1984);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_C(0x8bbcfC000), &pending, &ordinal) == FUXI_RAM30_DEFER && ordinal == 3903);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_C(0x8b9f00001), &complete, &ordinal) == FUXI_RAM30_REJECT);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_C(1) << 46, &complete, &ordinal) == FUXI_RAM30_REJECT);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_MAX & ~UINT64_C(0x3fff), &complete, &ordinal) == FUXI_RAM30_REJECT);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, 0, &complete, &ordinal) == FUXI_RAM30_REJECT);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_C(0x8b9f00000), &complete, NULL) == FUXI_RAM30_REJECT);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_C(0x8bbd00000), &complete, &ordinal) == FUXI_RAM30_REJECT);
    CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_C(0xafe000000), &complete, &ordinal) == FUXI_RAM30_REJECT);
    for (unsigned int incomplete = 0; incomplete <= 8; incomplete++) {
        if (incomplete == 7) continue;
        CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, UINT64_C(0x8b9f00000), &incomplete, &ordinal) == FUXI_RAM30_DEFER);
    }
    uint64_t deferred = 0, holes = 0, planned = 0, current = 0;
    for (uint64_t slot = 0; slot < 595968; slot++) {
        uint64_t pa = UINT64_C(0x8b8000000) + slot * PAGE_SIZE;
        bool whitelist = (pa >= UINT64_C(0x8b9f00000) && pa < UINT64_C(0x8bbd00000)) || pa >= vm_first_phys;
        enum fuxi_ram30_shadow_action result = fuxi_ram30_shadow_pa(12, sku12, 4, pa, NULL, &ordinal);
        if (!whitelist) { CHECK(result == FUXI_RAM30_REJECT); holes++; continue; }
        CHECK(result == FUXI_RAM30_DEFER && ordinal == slot);
        CHECK(UINT64_C(0x8b8000000) + (uint64_t)ordinal * PAGE_SIZE == pa);
        deferred++;
        result = fuxi_ram30_shadow_pa(12, sku12, 4, pa, &complete, &ordinal);
        if (!FUXI_RAM30_HOST_PROOF) CHECK(result == FUXI_RAM30_DEFER);
        else if (pa < vm_first_phys) { CHECK(result == FUXI_RAM30_PLAN_EXPLICIT_PFN && !pa_valid(pa)); planned++; }
        else { CHECK(result == FUXI_RAM30_CURRENT_GEOMETRY && pa_index(pa) + 8192 == ordinal); current++; }
    }
    for (uint64_t pa = UINT64_C(0x880000000); pa < UINT64_C(0x8b9d00000); pa += PAGE_SIZE)
        CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, pa, &complete, &ordinal) == FUXI_RAM30_REJECT);
    for (uint64_t pa = UINT64_C(0xafe000000); pa < UINT64_C(0xb00000000); pa += PAGE_SIZE)
        CHECK(fuxi_ram30_shadow_pa(12, sku12, 4, pa, &complete, &ordinal) == FUXI_RAM30_REJECT);
    for (uint64_t pa = UINT64_C(0x8b9f00000); pa < UINT64_C(0x8bbd00000); pa += PAGE_SIZE)
        CHECK(fuxi_ram30_shadow_pa(12, sku8, 4, pa, &complete, &ordinal) == FUXI_RAM30_REJECT &&
              fuxi_ram30_shadow_pa(8, sku12, 4, pa, &complete, &ordinal) == FUXI_RAM30_REJECT);
    CHECK(deferred == 589696 && holes == 6272 && deferred + holes == 595968);
    CHECK(planned == (FUXI_RAM30_HOST_PROOF ? 1920 : 0));
    CHECK(current == (FUXI_RAM30_HOST_PROOF ? 587776 : 0));
    CHECK(UINT64_C(0x230000) - UINT64_C(0x22ef40) == 4288);
    CHECK(UINT64_C(0x22ef40) - UINT64_C(0x22e7c0) == 1920);
    printf("{\"host_proof\":%d,\"checks\":%llu,\"deferred_unknown_owner_pfns\":%llu,\"excluded_span_slots\":%llu,\"hypothetical_extra_plan_pfns\":%llu,\"vm_release_called\":false,\"physical_device_test\":false}\n",
        FUXI_RAM30_HOST_PROOF, (unsigned long long)checks, (unsigned long long)deferred,
        (unsigned long long)holes, (unsigned long long)planned);
    return 0;
}
```

### 可重現 native／ASan 命令

在 ksrc 根目錄執行以下 PowerShell。它只抽取本文件公開 C/diff 到 TemporaryDirectory，reuse 現有 compiler discovery，不執行 audio tests，不讀 DTB／Android capture／官方 cache。C11 warnings-as-errors＋ASan 不可 skip；兩模式的 intentional heap OOB 都必須被捕捉，`FUXI`＋host-proof compile 必須因指定 `#error` 失敗。只有 host 模式可做 synthetic plan，沒有 VM release 或 boot image。

```powershell
Set-Location -LiteralPath D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc
$text = Get-Content -LiteralPath docs-lanes/ram-android-owner-20261116.md -Raw -Encoding UTF8
[regex]::Match($text, '(?ms)^```python\r?\n(.*?)^```').Groups[1].Value | python -B -
if ($LASTEXITCODE -ne 0) { throw 'RAM30 public native proof failed' }
```

```python
from pathlib import Path
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
sys.dont_write_bytecode = True
root = Path.cwd()
text = (root / 'docs-lanes/ram-android-owner-20261116.md').read_text(encoding='utf-8')
diff = re.search(r'^```diff\n(.*?)^```$', text, re.S | re.M).group(1)
code = re.search(r'^```c\n(.*?)^```$', text, re.S | re.M).group(1)
body = ''.join(line[1:] + '\n' for line in diff.splitlines() if line.startswith('+') and not line.startswith('+++'))
spec = importlib.util.spec_from_file_location('ram30_compiler', root / 'tools/test-fuxi-audio-prep.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
compiler, environment = module.compiler_environment()
environment = dict(environment, ASAN_OPTIONS='halt_on_error=1:detect_leaks=0')
msvc = Path(compiler[0].strip('"')).name.lower() in ('cl', 'cl.exe')
print('compiler:', compiler[0])
with tempfile.TemporaryDirectory(prefix='fuxi-ram30-native-') as temporary:
    directory = Path(temporary)
    (directory / 'ram30-shadow-body.h').write_text(body, encoding='utf-8')
    source = directory / 'driver.c'
    source.write_text(code, encoding='utf-8')
    flags = (['/nologo', '/TC', '/std:c11', '/W4', '/WX', '/Od', '/Zi', '/MD', '/fsanitize=address'] if msvc else
             ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer'])
    for enabled in (0, 1):
        executable = directory / (f'ram30-{enabled}.exe' if os.name == 'nt' else f'ram30-{enabled}')
        definition = ([] if not enabled else ['/DFUXI_RAM30_HOST_PROOF=1'] if msvc else ['-DFUXI_RAM30_HOST_PROOF=1'])
        output = [f'/Fe:{executable}', f'/Fd:{directory / f"ram30-{enabled}.pdb"}'] if msvc else ['-o', str(executable)]
        subprocess.run(compiler + flags + definition + [str(source)] + output, cwd=directory, env=environment, check=True, timeout=60)
        result = subprocess.run([str(executable)], cwd=directory, env=environment, capture_output=True, text=True, check=True, timeout=60)
        checks = json.loads(result.stdout)
        if (checks['host_proof'] != enabled or checks['checks'] <= 1000000 or
            checks['deferred_unknown_owner_pfns'] != 589696 or checks['excluded_span_slots'] != 6272 or
            checks['hypothetical_extra_plan_pfns'] != (1920 if enabled else 0) or
            checks['vm_release_called'] is not False or checks['physical_device_test'] is not False):
            raise ValueError('Native shadow counts/default-off contract mismatch')
        print(json.dumps(checks))
        canary = subprocess.run([str(executable), 'asan-canary'], cwd=directory, env=environment, capture_output=True, text=True, timeout=30)
        report = canary.stdout + canary.stderr
        if canary.returncode == 0 or 'AddressSanitizer' not in report or 'heap-buffer-overflow' not in report:
            raise ValueError('ASan runtime did not catch intentional host-only heap OOB')
        print(f'PASS ASan mode={enabled}: heap-buffer-overflow caught, exit={canary.returncode}')
    definition = ['/DFUXI=1', '/DFUXI_RAM30_HOST_PROOF=1'] if msvc else ['-DFUXI=1', '-DFUXI_RAM30_HOST_PROOF=1']
    output = ['/c', f'/Fo:{directory / "boot-forbidden.obj"}'] if msvc else ['-c', '-o', str(directory / 'boot-forbidden.o')]
    guard = subprocess.run(compiler + flags + definition + [str(source)] + output, cwd=directory, env=environment, capture_output=True, text=True, timeout=60)
    if guard.returncode == 0 or 'FUXI_RAM30_HOST_PROOF_is_not_a_boot_feature' not in guard.stdout + guard.stderr:
        raise ValueError('FUXI+host-proof must fail compilation by required #error')
    print('PASS boot guard: FUXI+HOST_PROOF compilation rejected by required #error')
print(json.dumps({'input_mode': 'public-doc-fixtures-only', 'private_dtb_read': False, 'source_cache_read': False,
                  'sanitizer_skipped': False, 'production_pmap_verified': False, 'new_bank_admitted': False}))
```

第二命令是**明示的 local source check**，只需要官方 cache 的 `pmap_data.h`，不讀實機 DTB/capture；缺 source 或 hash 不符就失敗。該檔未被命中 patches 改動，hash 與六檔 applied replay 一致。diff 以 LF bytes 寫出，避免 Windows `write_text` 將 context 轉成 CRLF。

```powershell
Set-Location -LiteralPath D:\xiaomi13\fuxi_ios\work\adsp-battery\ksrc
@'
from pathlib import Path
import hashlib
import re
import shutil
import subprocess
import tempfile
root = Path.cwd()
text = (root / 'docs-lanes/ram-android-owner-20261116.md').read_text(encoding='utf-8')
source = root.parent / 'ram-source-reference/xnu-8796.141.3/osfmk/arm/pmap/pmap_data.h'
if hashlib.sha256(source.read_bytes()).hexdigest() != '26f464e4dc2dd71da80d1155f7314a8f107d0a8be54965ac03def390a7dadc17':
    raise ValueError('Actual applied owning-header hash mismatch; no source fallback')
code = re.search(r'^```c\n(.*?)^```$', text, re.S | re.M).group(1)
for name in ('pa_valid', 'pa_index'):
    pattern = rf'{name}\(pmap_paddr_t pa\)\n\{{(.*?)\n\}}'
    if re.search(pattern, code, re.S).group(1) != re.search(pattern, source.read_text(encoding='utf-8'), re.S).group(1):
        raise ValueError('Native helper body differs from actual source: ' + name)
with tempfile.TemporaryDirectory(prefix='fuxi-ram30-source-check-') as temporary:
    directory = Path(temporary)
    destination = directory / 'osfmk/arm/pmap/pmap_data.h'
    destination.parent.mkdir(parents=True)
    shutil.copyfile(source, destination)
    proposal = directory / 'ram30-shadow-proposal.patch'
    proposal.write_bytes(re.search(r'^```diff\n(.*?)^```$', text, re.S | re.M).group(1).encode('utf-8'))
    for operation in (['--check'], []):
        subprocess.run(['git', '-C', str(directory), 'apply', *operation, str(proposal)], check=True, timeout=30)
print('PASS owning hash/native bodies/regular git apply --check and apply; temporary copy only')
'@ | python -B -
if ($LASTEXITCODE -ne 0) { throw 'RAM30 local source check failed' }
```

### 本輪實際結果與下一個 gate

MSVC `14.50.35717`，`/std:c11 /W4 /WX /Od /Zi /MD /fsanitize=address` 實際編譯／執行；沒有 sanitizer skip。首次 default-off 的 unused-parameter 警告已用 proof gate 順序修正，未降低警告等級。

| Check | 實際結果 |
| --- | --- |
| 未定義 host-proof，default-off | 1838558 CHECKs；589696 unknown-owner PFNs 全 defer；6272 span slots reject；extra plan＝0 |
| host-proof＝1，公開 synthetic bits | 同 1838558 CHECKs；pending 仍全 defer；只在 bits＝7 的 synthetic query 計畫 extra1920＋current587776；不是 admission |
| 邊界／守恆 | 16KiB、null/malformed/endian SKU、8GB/mismatch、NULL/incomplete owners、64-bit extremes、PA↔dense index，595968＝589696＋6272；925MiB scope-unselected／32MiB GPU 全拒絕 |
| ASan runtime／boot guard | 兩模式 intentional heap-buffer-overflow 均 exit1 且有 ASan 診斷；`FUXI`＋host-proof compile 因指定 `#error` 拒絕 |
| actual owning source | 六檔依 `0008,0010,0011,0012,0082,0101` 實際 replay，hash 全符；native 原 helper bodies 相同；doc diff regular `git apply --check`＋apply 通過（只在 temporary copy） |

公開 C driver SHA-256＝`7eb9e34cf5a6296ecb1c0f1577efc298460c85dd488cf6efe472d4fbd594726f`；diff added-body SHA-256＝`51a7ef9d01e2e1e90f34d27f82dceb087ef4f232df9f3d5c29a65e7ecc0ab42e`（UTF-8/LF）。public native 命令不依私有 capture 或 source cache；local source check 另行明示，不能在 public CI 偷偷 skip 缺資料。

**最小下一安全步驟：** 主代理完成入口的 SKU/runtime FDT 拒絕 gate，並對這一個 12GB／30MiB bank 補齊 iOS handoff phase 的 original/relocated FDT extent、persistent monitor／DMA coverage、dynamic-window placement/lifetime；Android 當前 owner evidence 不代替此 clearance。未齊就保持 defer，不產可 boot new-bank profile。owner 清查後，才依上述五個耦合點做完整 applied-tree 的 metadata／physmap／explicit-PFN／counter host proof，再決定獨立實機驗證；不可只改 scalar base/size 或直接 late release。

本輪沒有 VM release、production pmap/PTE/PTOV/GPU alias 實測、完整 kernel build 或任何 hardware writes；新 bank admitted＝false、final allocatable bytes＝null。8GB 正式驗收仍需 8GB 實機；12GB 縮小 available memory regression 不冒充該驗收，也不把 9184MiB／9GiB 階段窗口當成 12GB 的終點。925MiB 候選、772MiB size requests/CMA 均未轉成可用量。
