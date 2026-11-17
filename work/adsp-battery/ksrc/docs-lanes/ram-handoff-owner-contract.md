# Fuxi handoff owner contract：linker 邊界與 runtime 缺證

2026-11-16，初讀 `17:20 +08:00`，主代理更新 source 後於 `17:32` 複核；ksrc 初始 baseline `a066a05d5be74dacac0d597b2ee71dd199e79bf4`，複核 HEAD `06c7b643af1cf6b3c28a9cb3ae9fcb2e86215606`。只新增本文件；不改 shim／VM／canonical／既有 RAM 工具，不 build、不操作手機／鎖、不 commit。不發布 raw DTB、private capture 或 ELF／payload。這是 ownership observation contract，不是新 RAM admission 或已實作的 report ABI。

此 snapshot 只綁定已確認的 **12GB SKU／usable9g**；9184MiB 是階段窗口而非 12GB 終點。8GB 缺獨立 topology／owner／boot 證據，保持 unsupported，不生成 profile；12GB 限縮 memory regression 不代替 8GB 實機驗收。

## Owning source 與 binary 綁定

[current chain builder](D:/xiaomi13/fuxi_ios/work/boot-chain/build-chain.py:29) 使用 `D:/xiaomi13/fuxi_ios/ios-fuxi/shim`，其 [object/link list](D:/xiaomi13/fuxi_ios/work/boot-chain/build-chain.py:74) 是 `fuxi-loader/start.S`＋`loader.o`＋`probe.o`＋`chain.o` 等，**不是** `fuxi-probe/start.S` 或 generic `shim/start.S`。9g loader objects 重用 payload 目錄；本輪沒有執行 builder。

目前 ksrc 的 `loader.ld` 與 canonical bytes 相同；`start.S`、`loader.c`、`probe.c` 不同，ksrc 沒有同名 chain linker/source。不可用 development source 的行號冒充日常 chain 的 source。[既有 owner checkpoint](D:/xiaomi13/fuxi_ios/work/adsp-battery/ksrc/docs-lanes/ram-android-owner-20261116.md:61) 已記錄來源差異。

| 本輪只讀來源 | SHA-256 |
| --- | --- |
| canonical `fuxi-loader/loader.ld` | `424648dc476c1fab7a0f0015bec34732423697d423e1a5a2a475b9663443534e` |
| canonical `fuxi-loader/loader-chain.ld` | `4898d27caebe33890919bcc0b8a39f8adb1e7e7766073e57689aae854ede1e94` |
| canonical `fuxi-loader/start.S` | `7e2d0a6c8b1442e7e881480151ce1886cd37b1c46cca1ed45b950933b87db2ed` |
| canonical `fuxi-loader/loader.c` | `0685ad0c913fb10a2c5c4e0127a297e85c30d08fe4272b3c855e30c037c55a25` |
| canonical `fuxi-loader/chain.c` | `c9ee5735aa747a924cd628310dd0983172b77843164a5cb14590149d162bb5d9` |
| canonical `fuxi-loader/fuxi-ram-profile.h` | `088c04267e025f6c4a93b9f3008ce58be4cf877dbd9786447c0a9b5e0c8bb3d5` |
| canonical `fuxi-probe/probe.c` | `4a5c1c8e2321a9a22dec85ad08794c69c6d46ff9de87a2a7b1a17b6d1bfd7365` |
| canonical `fuxi-probe/monitor.h` | `035f0d0eff76308ba8a7a43e9bc7362b00d16cfd4044749a35bbd13b7316a825` |
| canonical `fuxi-probe/gpu-handoff.h` | `37005b98cc2615c9bc36a8cda1707a926ce0256875e22af41cdff7724588752a` |
| current `work/boot-chain/build-chain.py` | `1a71ba479f5c723f7896d04cd6476d94ee9bcb89b8f276fe72639aa0b5fa2d75` |

只讀 ELF 是 `D:/xiaomi13/fuxi_ios/work/boot-chain/chain-v6-ram9g-batfresh/loader.elf`，SHA-256 `b5ce327c9301c98889ba9f2ab130fc93d3682b849b29c4e0f264551b768c4c45`；對照 normal loader 是 `D:/xiaomi13/fuxi_ios/work/Codex-Xiaomi13-GPU-20261109/native-dly-ram9g-batfresh-sb127-loader/loader.elf`，SHA-256 `009af2c5638c589b13941d496828e0fdc3a793dbb684ebd96257433576bc8357`。source hashes 是本輪讀取的 view，**不宣稱 archived ELF 有完整 source-to-binary provenance**；直接 ELF symbols／entry disassembly 是另一路 binary 證據。

複核的 [current loader guard](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:16) 已使用 `fuxi-ram-profile.h`，在 `probe_main` 前做 FDT readability/profile 檢查；它讀至 `roundup4(total)`，拒絕該 read-window 與整個 loader image 或 `[FG_RAM_BASE,FG_RAM_BASE+FG_BANK_SIZE)` 相交。[caller](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:250) 只在 StaticOk12G 時繼續。這是 current source 證據，不把兩個舊 ELF 當成 guard 已建置／部署證明；helper 的 [local arrays](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/fuxi-ram-profile.h:152) 也要求未來新 ELF 重新核對 primary-stack 使用量。

主代理最新交接：**第20趟 12GB incoming FDT guard 通過並進 SpringBoard**。這是主代理提供的另一個實機 checkpoint，不是本 worker 的手機操作或兩個 archived ELF 的驗收；更不表示 lower30MiB／925MiB、persistent owners 或全12GB 已 cleared，`pending=69/release=0/allocatable=null` 不因此改變。

## 已收斂的 image／stack 範圍

兩 linker 都從 VMA 0 開始。[normal layout](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.ld:8)／[chain layout](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader-chain.ld:13) 在 BSS 後各留 `0x8000` 給 primary、secondary stack；stack 向下成長，`_secondary_stack_top == _payload_start` 不表示與 payload 重疊。

`llvm-nm -n -S --defined-only` 在兩既有 ELF 得到以下相同 RVAs。下表 PA **只**使用 [stored chain report](D:/xiaomi13/fuxi_ios/work/Codex-Xiaomi13-GPU-20261109/native-hw000chainv6-ram9g-batfresh-boot-1/before.json:11) 的 `MON_IMAGE=0xa8000000` 換算：`PA=MON_IMAGE+(symbol-_head)`；normal ELF 沒有在本輪另配 runtime load base。

| Owner envelope `[start,end)` | ELF RVA | 此 stored chain 的 PA | Lifetime／限制 |
| --- | --- | --- | --- |
| code、rodata、firmware、data 與前置 padding | `[0,0x44000)` | `[0xa8000000,0xa8044000)` | monitor 有 caller／vectors 時保留 |
| 全部 BSS，含 reports／fault state／DMA statics | `[0x44000,0x74000)` | `[0xa8044000,0xa8074000)` | 192KiB；不能只保留 USB array 而忘記其餘 BSS |
| primary stack | `[0x74000,0x7c000)` | `[0xa8074000,0xa807c000)` | 32KiB assigned envelope；不是 runtime stack high-water 證明 |
| secondary stack | `[0x7c000,0x84000)` | `[0xa807c000,0xa8084000)` | 32KiB；persistent CPU 仍使用，不因 primary 進 XNU 就 free |
| embedded payload | `[0x84000,0x114cff0)` | `[0xa8084000,0xa914cff0)` | copy source；本 contract 不提出 reclaim |
| chain Linux footprint，含 serialized end 之後的尾部 | `[0x1200000,0x3fe0000)` | `[0xa9200000,0xabfe0000)` | `LINUX_IMAGE_SIZE`，不是 ELF file bytes |
| 保守 parent image，包括 stacks、alignment gaps、Linux footprint | `[0,0x3fe0000)` | `[0xa8000000,0xabfe0000)` | 66977792 bytes；與上述子項 union 去重，不相加 |

Normal `_image_end=_payload_end=0x114cff0`；chain `_linux_end=0x3f3ea00`，但 `_image_end=_end=0x3fe0000`。[chain linker](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader-chain.ld:24) 明列 Linux footprint；僅依 PT_LOAD/file end 會漏 `0xa1600` bytes 尾部及 BSS 後的兩個 stack gaps。`start.S` [Image header](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/start.S:4) 使用 `_image_end`。

直接 disassembly 的 primary `adr` 在 RVA `0x818` 解析至 `0x7c000`；secondary 在 RVA `0x18ac` 解析至 `0x84000`，與 linker 相符。[primary entry](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/start.S:14) 清 BSS 後使用 primary stack；[secondary entry](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/start.S:137) 自設 SP、VBAR，沒有重新清 BSS。

## 不只 USB：static DMA 最小表

| Object | ELF RVA／bytes | 此 stored chain 的 raw PA extent |
| --- | --- | --- |
| `dma_area` | `0x70000`／16384 | `[0xa8070000,0xa8074000)` |
| `gpi_ring`，兩個 channel rings | `0x4b400`／2048 | `[0xa804b400,0xa804bc00)` |
| `gpi_evr`，event ring | `0x4c000`／4096 | `[0xa804c000,0xa804d000)` |
| `gpi_txb` | `0x4b100`／64 | `[0xa804b100,0xa804b140)` |
| `gpi_rxb` | `0x4afc0`／265 | `[0xa804afc0,0xa804b0c9)` |

[USB layout](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:863) 的 event buffer／TRBs／setup／data 都以 `dma_area` 為 base；[programming](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1063) 使用 `ud.dma_pa+offset`，[initialization](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1423) 設 `ud.dma_pa=ud.dma`。這依賴 CPU MMU/cache entry ABI，不證明 handoff 後 SMMU/IOVA epoch 未變。

[GPI declarations](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:527)／[ring programming](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:587)／[TX/RX submission](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:665) 是額外 DMA owners，不在 `dma_area` 內。四個 GPI arrays raw sum 6473 bytes，16KiB outward-rounded union 為 `[0xa8048000,0xa8050000)`＝32KiB，已包含於 BSS parent；不是另一個可加減的容量。`lo32` 與 ring high-word=0 的假設也須保留，不搬這些 buffers。

ELF 中 `ud` 已被 compiler scalar-replace 成 `ud.0..ud.9`；不存在一個可藉 `sizeof(ud)`／單一 symbol 自動認定的 runtime DMA ledger。symbol 只證明已配置 object envelope；要封閉 bus targets，仍需 phase-matched 的 event/TRB address、length、resource ownership 與 SMMU 狀態，不把宣告 array 範圍冒充 hardware quiescence。

## Handoff owner 最小 contract

所有 row 都要帶 `owner_id`、`epoch/phase`、source/ELF hash、address space、已驗證 `[start,end)`、coverage、lifetime；unknown 欄位為 null/pending，不填 0。版本標籤可用 `fuxi-handoff-owners-v1`，**目前沒有實作此 producer／consumer**。

| 必須覆蓋的 owner | Link map／既有 runtime report 可提供 | 尚缺／本輪保留政策 |
| --- | --- | --- |
| monitor image＋BSS＋兩 stacks | 上表 RVAs；`MON_IMAGE/MON_END`、branch、ELF hash；SP initializer 的 binary proof | 保守 hold parent image；須綁同 boot。assigned stack 不冒充 high-water／未越界證據 |
| USB DMA／controller resources | `dma_area` symbol、初始化公式；runtime event/TRB pointer/length、CPU/SMMU epoch | 本輪沒有 post-handoff register snapshot；RUN_STOP／未完成 TRB 不能當已停機 |
| touch GPI DMA | 四個 symbols；source 的 `touch_report[37/38]` 是 ring/event pointer，硬體 context 設定來源明確 | 即使沒有後續 CPU polling，DMA engine 不一定已 halt；沒有 stop/drain proof 就 hold |
| entry FDT，可能已被 ABL relocation | `probe_info.fdt_address/fdt_size`；實際 pointer、total、`roundup4(total)` read-window、validated hash；producer allocation capacity 若有 | 原 FDT extent 仍 null；非零 pointer 搭配 size0 是 invalid/unresolved，不是空 owner；total 不等於 allocation capacity |
| 任何另一次 relocated FDT／alias | 必須有 actual producer、source/destination extents、copy bound/hash、final reader pointers、phase | reviewed Fuxi path 沒有另建完整、持久的 relocated-FDT producer；USB response 的暫存 chunk 不替代原 owner。不據此宣稱 ABL/其他 component 沒有 copy，不生成零保留記錄 |
| 外部 initrd／bootconfig | valid FDT 的 `linux,initrd-start/end`、selected XNU/Linux branch 與 allocation/lifetime | chain 會讀這些 bytes；64MiB 是 mode fallback threshold，不是固定保留量。缺 producer coverage 仍 pending |
| kernel segments／Apple ADT／boot_args destinations | bounded payload header 的 affine formula；`MON_BOOT_ARGS`＋實際 `topOfKernelData`／segment extents | 不以整段 scalar memSize 冒充 staging owner；不是 free-list clearance；Apple ADT 與 raw FDT 分開 |

已知 parent image 與其 stack/static DMA 均不交於 lower 925／30MiB，但這只消去「已知 image envelope 可能放在那裡」的幾何疑問；**不解除其他 live-owner、dynamic DT、inherited ABL/EL3 owners，不降低 frozen trace 的 69 pending**。

## FDT 與 persistent monitor 生命周期

1. [entry 保存 x0 到 x19](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/start.S:16)。[chain_select](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/chain.c:133) 讀 FDT/外部 initrd，Linux branch 仍以 x19 作 x0 跳入 embedded Image；不把未選 Linux 當成 initrd allocation 已回收。
2. XNU branch 的 [probe_main](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1547) 保存同一 entry pointer；只記 pointer/total，沒有複製 raw FDT。`probe_fdt` 的 symbol PA `0xa8048000` 是 **8-byte pointer storage**，不是被指向 FDT 的 extent。
3. [USB request 0x41](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1162) 從 `probe_fdt` 讀資料，沒有 `MON_LAUNCH` 禁止 gate。[secondary forever loop](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:780) 在 delegate2 時繼續 `usb_poll()`；[primary return](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1567) 不停 controller、不做 CPU_OFF、不清 FDT pointer。**進 XNU 不是原 FDT／monitor／DMA 的 lifetime end。** `MON_ACTIVE` 或 CPU_ON return code 本身也不是 release token。
4. [loader ADT copy](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:210) 從 embedded payload 到 kernel 後方；[boot_args.deviceTreeP](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:229) 是 Apple ADT 的 VA／length，不是原 Linux FDT 的 relocation 記錄。current source 的 [FDT overlap preflight](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:28) 拒絕 image 與完整 9g bank（current＋scratch），[staging 前](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-loader/loader.c:175) 再驗 profile；仍允許 FDT 位於該 bank 之外，因此沒有回答其是否踩 lower925/30MiB，也不清除任何 persistent owner。StaticOk12G 不是全 owner coverage/admission token。
5. 若後續別的 owning component 實際 relocation，contract 要同時 hold source/destination，直到 last-reader retargeting、copy/hash 與 DMA/CPU lifetime 都有證據；`memcpy` 完成／`dsb`／primary return 均不能單獨解除 source。此條只定義缺證，不修改 relocation 或 release code。

## 可用的最小 report 與下一輪缺口

[probe_info](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:42) 是 19×u64＝152 bytes 的 native little-endian report：FDT address 在 offset72、size 在 offset80。已有 request `0xc0/0x40` 的 producer，不需要為「取 pointer/total」發明新的 shim allocation；下一輪若取得**同 boot／同 phase** 的既有 report，就能把已知 FDT read-window 從 null 收斂為實際 extent，再另核 producer capacity/coverage。不得發布 raw 0x41 DTB。

[monitor ABI](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/monitor.h:3) 是 11×u64；已有 image/end、delegate/active、USB MPIDR、stage、boot_args/entry，沒有 FDT pointer、relocated extent、SP high-water、DMA-drained、source hash 或 boot epoch。host 必須做 provenance 綁定及 coherent phase sampling，不能把不同 boot 的 reports 拼成 clearance。

目前 stored `before.json`（SHA-256 `44ae548d5adcac33b0843a1b08c4ad1452bff5cb016127ef3740d984a49a7da2`）有 delegate2／active1 與 image/end，但 boot_args=0、沒有 FDT address/size；本輪沒有新 runtime capture。**最少仍缺兩組資料：entry-FDT/外部 staging 的實際 ranges＋producer coverage，以及 handoff 後 persistent readers／DMA targets 的同 epoch 證據。** 後者若仍 active，政策是保留已知 owner，不要求本 worker 停 monitor，也不把 quiescence 假造為 true。

不要把所有 USB「report」呼叫都叫唯讀：[0x45](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/probe.c:1181) 可呼叫 CPU_ON；0x46/value1 可 delegate；0x49 可 launch；0x54 會改 deadline。此文件只讀 host artifacts/source，沒有執行任何 USB request。

## Hole exclusion 與 fail-closed

- 固定 context holes：`[0x8b9d00000,0x8b9f00000)`＝2MiB、`[0x8bbd00000,0x8c0000000)`＝67MiB；永不因 image owners 不相交就變成 memory。
- 此 12GB/9g 的 GPU reservation `[0xafe000000,0xb00000000)`＝32MiB 持續排除，[FG owning constants](D:/xiaomi13/fuxi_ios/ios-fuxi/shim/fuxi-probe/gpu-handoff.h:7) 不改、不搬 scratch。
- 所有 owner extent 先 checked uint64 addition，再 16KiB outward rounding；overflow、0-size invalid FDT、missing pointer/capacity/coverage 保持 reject/defer。union 去重 parent/child、相鄰與重疊，保留 reason/owner IDs；不用 owner raw sums 或 772MiB size requests/CMA 作容量相減。
- lower `[0x880000000,0x8b9d00000)`／`[0x8b9f00000,0x8bbd00000)` 在本輪均**不 admitted**；30MiB／1920PFNs 不做 VM release。`pending=69`、`release=0`、`allocatable_bytes=null`、`all_live_owner_coverage=false`。

## 實際唯讀檢查

NDK 已有 LLVM 17.0.2；`llvm-nm`、`llvm-readelf --program-headers --wide`、`llvm-objdump` 直接讀兩個 archived ELF。65 項 host assertions 實際通過：兩 ELF 的 RVA/size、static DMA 全在 BSS、兩 stacks 各32KiB、normal/chain ends、Linux serialized/footprint 差、stored MON_IMAGE/end 綁定、GPI page union、已知 image 與兩 lower banks 不相交。不是 kernel build、native admission helper 或硬體測試。

可重跑的純讀取命令（需要本機既有 ELF，沒有缺檔 skip 或生成映像）：

```powershell
$ErrorActionPreference = 'Stop'
$bin = "$env:LOCALAPPDATA\Android\Sdk\ndk\26.1.10909125\toolchains\llvm\prebuilt\windows-x86_64\bin"
$elf = 'D:\xiaomi13\fuxi_ios\work\boot-chain\chain-v6-ram9g-batfresh\loader.elf'
if (-not (Test-Path -LiteralPath $elf)) { throw 'Required existing ELF missing' }
& "$bin\llvm-nm.exe" --numeric-sort --print-size --defined-only $elf |
    Select-String ' (_head|_bss_start|_bss_end|_stack_top|_secondary_stack_top|_payload_start|_payload_end|_linux_start|_linux_end|_image_end|_end|dma_area|gpi_ring|gpi_evr|gpi_txb|gpi_rxb|probe_fdt|probe_fdt_size)$' |
    ForEach-Object { $_.Line }
if ($LASTEXITCODE -ne 0) { throw 'llvm-nm failed' }
& "$bin\llvm-readelf.exe" --program-headers --wide $elf
if ($LASTEXITCODE -ne 0) { throw 'llvm-readelf failed' }
& "$bin\llvm-objdump.exe" --disassemble --no-show-raw-insn --disassemble-symbols=_start,probe_secondary_entry $elf
if ($LASTEXITCODE -ne 0) { throw 'llvm-objdump failed' }
```

本輪縮小的是 **linker-backed owner geometry** 與可取得 FDT pointer 的既有 report 路徑；持續保留 lifetime、inherited/dynamic owners 及 source-to-runtime 綁定缺口，沒有放行 30MiB 或其餘 lower banks。
