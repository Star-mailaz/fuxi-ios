# 全新受控 W18 短測 profile

## 工具與目前 checkpoint

主機工具位於 `work/adsp-battery/prepare-wlan-w18-loader.py`，提供 `inspect`、
`build`、`self-test` 三個入口。預設核心目錄是
`work/Codex-Xiaomi13-GPU-20261109/kernel-adsp-iter2-ram9g-artifact`。
2026-11-16 最初準備時此 artifact 尚待主代理下載；1436 capture 交接後的
主機 `inspect` 已核對此核心 hash、9G ADT、W18/MODE/joint-guard markers。
核心 SHA-256 為 `b4ecbf79d7fc69113023452b1c4d038a13e5615657916edc0548fab320049d6b`。

此 profile 使用有雜湊紀錄的 `native-dly-ram9g-sb127-user-loader` 私有 ADT、
既有 RAM9G 主機建置流程，以及 W10 文件的 WLAN transport recipe。
W18 選定單一分階段診斷。try16 的原始 boot log 與完整參數仍缺。

```powershell
python D:\xiaomi13\fuxi_ios\work\adsp-battery\prepare-wlan-w18-loader.py self-test
python D:\xiaomi13\fuxi_ios\work\adsp-battery\prepare-wlan-w18-loader.py inspect
```

`inspect` 以 JSON 列出來源、精確命令列 template、移除的 tokens、ADT 設定、
資產驗證狀態及缺口。BDF 尚未選定時，`command_line` 為 null，template 的
`BDF_FROM_MANIFEST` 是待補的資產名稱。

主代理取得核心與有來源證據的 BDF manifest 後，可由同一個 `build` 入口產生
`native-wlan-w18-ram9g-sb127-loader`。`--bdf` 取值必須對應 manifest 的確切檔名，
`--assets-manifest` 指向其本機 JSON。`--artifact` 可明確指定另一個已下載目錄。

```powershell
python D:\xiaomi13\fuxi_ios\work\adsp-battery\prepare-wlan-w18-loader.py build --bdf $w18Bdf --assets-manifest $w18AssetsManifest
```

`$w18Bdf` 與 `$w18AssetsManifest` 由主代理的已核對資產紀錄設定。
已取得 1436 root capture manifest，但它沒有 BDF record；仍缺有選擇證據的
`--bdf` 與適合建置的 WLAN 資產 manifest。工具會做核心與 BDF record 來源檢查。
其他 runtime 資產或其 root 關聯缺口會保留在生成的 profile JSON，讓主代理
完成 root staging 與裝置測試前的核對。

## 已核對的來源與佈局

| 項目 | 本機證據 |
| --- | --- |
| Source loader | `native-dly-ram9g-sb127-user-loader` |
| Source payload SHA-256 | `c71f997c564a89d04e9411216f61c6eda0292278fa75aeb90830998f4377acc1` |
| Source boot SHA-256 | `40c2bfa7f9eee6122520e1cecee18653ebfabdcd9df52b002954126629acec85` |
| RAM base / usable size | `0x8c0000000` / `0x23e000000` |
| GPU scratch base / size | `0xafe000000` / `0x02000000` |
| Statusbar ADT | `fuxi,sbshape=300127`、`fuxi,inject=2` |
| FDT capture | `work/hw-survey/fuxi-live-20261116.dtb` |
| FDT SHA-256 | `2d7e97ea52bf67a79ef7b99487131a41bd87fc0ab774983ce62bfb9fa79fb9fa` |
| Recorded native root | `/data/gsi/codexnative1108b/codexnative_root_1108b.img.0000` |
| Root size / inode | `21474836480` bytes / `199819` |
| Recorded map time | `2026-11-16T13:53:00+0800` |
| Root extents | 39 條、連續 logical coverage、4 KiB 對齊 |
| ADT extent SHA-256 | `806fa0b19839f88c036f856c2f270fdeb7f60dc4ff40cecccf2225c5f3aad6d2` |

`managed-native-map-current.json` 中的 pin check 記錄為 `pin_rc=0 moved=0`，
檔案 flags 有 `0x800000`。工具逐條核對 FIEMAP 與 39 個 DM linear targets，
再與 source ADT 的 `fuxi-root-extents`、20 GiB `fuxi-root-blocks` 比較。
這些檢查使用既有主機快照，裝置現況由主代理的手機流程確認。

RAM 範圍也經既有 `mkadt-fuxi.py` 的 FDT reservations、GIC、UFS、splash
檢查。Loader C、assembly、linker script 及其餘 shim source 的雜湊，對照
source loader 的 `source-input-sha256.txt`。編譯使用 NDK LLVM 與
`FUXI_RAM_9G=1`，沿用 `prepare-ram9g-loader.py` 的編譯／封裝方法。

## 精確控制值

WLAN 與 ADSP 的新增命令列為以下七個 tokens。

```text
fuxiadsp=0 fuxiwlan=1 fuxiwlanclk=1 fuxiwlanprobe=civac fuxiwlanseq=cycle,parf,dbi,eq,hostirq,msi,por,prefix fuxiwlanqrtr=5 fuxiwlanw18=1
```

BDF 資產確定後，再加入 `fuxiwlanbdf=` 與其確切 basename。
來源經縮減後，這七個 tokens 與 bootstrap 共 564 bytes，BDF basename 還有
30 bytes 空間。`build` 按實際字串驗證 607-byte 上限與 BDF basename 規則。

| 設定 | 此 profile 的值與來源 |
| --- | --- |
| ADSP | 命令列 `fuxiadsp=0`，ADT `fuxi,adsp=0` |
| Independent peripherals | ADT `fuxi,amp=0`、`fuxi,pmic=0`、`fuxi,haptic=0` |
| RAM test | ADT `fuxi,ramtest=0`，RAM layout 為 9G |
| WLAN steps | `fuxiwlan=1`，執行至 step 28 的 WLFW conversation |
| Clock / initial DMA | `fuxiwlanclk=1`、`fuxiwlanprobe=civac`，取自 W10 recipe |
| Sequence | `cycle,parf,dbi,eq,hostirq,msi,por,prefix`，取自 W10 recipe |
| WLAN milestone | `fuxiwlanqrtr=5`，INI → CFG → MODE → 2 秒 indication observation |
| W18 | `fuxiwlanw18=1` |
| W16 / W15 | source 預設值 0，16-entry IPCR 與完整 CFG shadow-v3 |
| MLO / P17 | source 預設值 0 |
| Extra rail experiment | `fuxiwlanrails` 預設值 0，正常路徑有六條外部 rail votes |
| Completion handling | `fuxiwlankeep`、`fuxiwlanstop22` 預設值 0 |
| Other WLAN transport switches | `oldiova=0`、`aspm=0`、`icc=1`，其餘 variants 取 source 預設值 |

目前 QRTR 5 的 entry point 在 MODE 成功後記錄 `stop before CE/HTC`，
完成 observation 與 containment。工具檢查下載核心的 W18、此 milestone，
以及 ADSP/WLAN joint guard 的字串標記。Joint guard 與共用 RPMh 鎖由已整合
核心的實作控制。

來源的 root/bootstrap、GPU ABI、`fuxigpuncimport=2405960`、雙／三 scanout
buffer、120 Hz panel、GPU level 24、idle 1000 與 backlight 4 tokens 會進入
新命令列。為加入 WLAN 的字串空間，此 profile 明確移除以下十個來源 tokens。

```text
debug=12
fuxivsynctoff=6000
sweetlog=0
sweetfb_noconsole=1
sweetnull=backboardd,SpringBoard,peakpowermanagerd
fuxiswapwait=0
fuxiperf=2
fuxicores=0x7c
fuxitudebug=nocb
fuxitcache=1
```

`serial=3` 與 ADT `fuxi,log=1` 提供短測紀錄路徑。
這份縮減命令列還需要新一趟裝置驗證。移除項目的效能、console 或使用者空間
行為差異列入本 profile 的實驗條件。工具也移除來源的 taps/tour 控制，
並清掉 `fuxi,tapcmd` ADT command。

## WLAN runtime 資產清單與缺口

WLAN 從 root filesystem 的 `/usr/local/share/fuxi/wlan/` 讀取檔案。
Loader 內的 embedded firmware 是 GPU firmware。

| Runtime filename | 使用方式 | 本輪來源狀態 |
| --- | --- | --- |
| `amss20.bin` | Endpoint `TCSR_SOC_HW_VERSION` major 2 的 AMSS | 1436 guest WLAN 目錄不存在，未 staging |
| `amss.bin` | Endpoint 其他 major 的 AMSS | 1436 guest WLAN 目錄不存在，未 staging |
| `regdb_xiaomi.bin` | W14 固定 regulatory database filename | 1436 guest WLAN 目錄不存在，未 staging |
| BDF basename 待定 | 由 `--bdf` 與 manifest 明確指定 | 缺有來源證據的 Fuxi BDF 選擇 |
| `m3.bin` | W14 M3_INFO 的 host DMA image | 1436 guest WLAN 目錄不存在，未 staging |

主代理的成功唯讀盤點為
`work/statusbar-fix/inspect-radio-assets-20261116-1436/assets.json`，SHA-256
`8935a695c4ced61a125f33bb0342b3c694a9afedf28b67dbef6772ad4a62125c`。
其 guest log 明確記錄 WLAN `ROOT_DIRECTORY exists=false`，只有 BlueTool／
bluetoothd 兩個 file receipts。這是 1436 該 root 的 staging 缺席實證，不是
missing host filename 推測。BDF parser 尚未讀到真正 WLAN 實物；Android firmware
與 actual selection/ID evidence 仍待主代理交接。Endpoint major 不能以 host CAP
SoC ID 推定；目前兩個 AMSS 分支都保留待補，不擅自選定其中一個。

已有主機檢查：

```powershell
python D:\xiaomi13\fuxi_ios\work\adsp-battery\prepare-wlan-w18-loader.py inspect --assets-manifest D:\xiaomi13\fuxi_ios\work\statusbar-fix\inspect-radio-assets-20261116-1436\assets.json
```

此檢查核心通過、root 關聯相符，但 `ready_to_build=false`，仍缺 BDF 選擇與
所有 WLAN file records。`inspect` 的 `missing_manifest_entry` 僅是 manifest
欄位狀態；guest 目錄缺席的獨立證據見 `wlan-bdf-provenance.md` 的 receipt-only 檢查。

`work/ref-sheng/UniXNU-sheng/firmware/wcn7850/manifest.json` 記錄了 sheng 的
`amss.bin`、299660-byte `m3.bin` 與 `board-2.bin` 雜湊及比對日期。
它的 provenance 指向 sheng 的 installed WFW1。Fuxi 的 AMSS/BDF/regdb/M3
組合、BDF calibration 適用性與 native-root 安裝證據仍待補齊。

Asset manifest 採現有 `files` object 形式，每個 filename 有 `sha256` 與 `bytes`。
完整 runtime 路徑也可作為 key。另有以下欄位供工具核對。

| 欄位 | 內容 |
| --- | --- |
| `provenance` | 可追溯的來源、擷取／比對紀錄或紀錄路徑 |
| `root_path` | 與此次 pinned native root 的關聯 |
| `files[filename].sha256` | 64 位十六進位 SHA-256 |
| `files[filename].bytes` | 實際檔案大小 |
| `files[filename].host_path` | 可選的本機檔案路徑，供直接雜湊與大小核對 |

`manifest_recorded` 表示有來源紀錄的 metadata，`local_hash_verified` 表示實際
本機檔案亦通過比對。root 關聯與各 required filename 的缺口另外列出。
工具的 `ready_to_build` 使用已驗證核心與明確 BDF record/provenance，
`runtime_assets_recorded_for_root` 使用全部 runtime 清單與 root 關聯的檢查結果。

### 最小 manifest 交接

主代理可對既有 native root 做唯讀檔名／大小／SHA-256 盤點，將結果填入
`files`。BDF 必須另外有 Fuxi 板型／校正或既有載入紀錄的選擇證據；僅找到
一個檔案或參考 sheng 的 `board-2.bin`，不足以替這個 profile 決定 `--bdf`。
不要求本工具接觸手機，也不因資產尚缺而延後工具 checkpoint。

最小可接受的建置輸入是頂層非空 `provenance`，及 `files` 中與 `--bdf`
完全同名的 record，內含實際 64 位 SHA-256 與正整數 `bytes`。
以下只是欄位骨架，所有尖括號內容需以唯讀盤點／選擇證據替換，並將
`bytes` 換成 JSON 整數，不能直接拿骨架建置。

```json
{
  "provenance": "<Fuxi BDF 選擇依據及唯讀盤點紀錄路徑>",
  "root_path": "/data/gsi/codexnative1108b/codexnative_root_1108b.img.0000",
  "files": {
    "<確定的 BDF basename>": {
      "sha256": "<唯讀盤點的實際 SHA-256>",
      "bytes": "<實際正整數大小>"
    }
  }
}
```

這個最小輸入只能解除 loader 建置的 BDF gate，不代表可進行 WLAN 短測。
短測前還需要 AMSS 分支、`regdb_xiaomi.bin`、`m3.bin` 的同格式 record，
以及對此次 pinned root 的 staging 關聯；未知道 endpoint major 時保留兩個
AMSS 分支的缺口。`host_path` 可省略，省略時只驗證 manifest 格式／來源
紀錄，不宣稱已在主機讀到 runtime 檔案。

## GPU embedded 資產

| 主機檔案 | SHA-256 |
| --- | --- |
| `firmware/gmu_gen70200.bin` | `1a2a419c39046d3141fc5fed5aa7f971de2db40cc7a1d89693c3e26fad64dd98` |
| `firmware/a740_sqe_sheng.fw` | `6d38046654333a6a5a4ee77ab67abc24e3c0c5c68237513afe98e94da8fc9fcc` |
| `work/xiaomi13-ios-gpu-20261108/a740-zap-active-odm.mbn` | `cad0dcb2daaa382eebc94ef65f3285b91b045c8976781f6a80910ca21c933a05` |

這三個檔案已在本機核對，也會在 loader Image 中逐一驗證單份嵌入。

## 主機檢查與輸出

已執行 `self-test` 與預設 `inspect`。Host checks 包含命令列上限、重複參數、
非法／過長 BDF、ADSP/WLAN selector、ADT round trip、recorded pin/FIEMAP/DM
一致性、失敗注入與本機資產 hash/size 變更拒絕。預設 `inspect` 成功列出
39 條相符的 root extents、9G/statusbar127、GPU 資產及 pending kernel/WLAN 缺口。

`build` 在暫存目錄生成 private ADT、payload、loader ELF、Image、Android v4
boot image，驗證 RAM、命令列、ADT 與 embedded 資產。C object 會檢查
`R_AARCH64_ABS` relocation。輸入雜湊在完成時再核對，最後將已驗證輸出
搬入新的 loader 目錄。

交接輸出包含 `boot.img`、`payload.bin`、`private.adt`、`source.txt`、
`sha256.txt`、`memory-layout.json`、`source-input-sha256.txt` 及
`wlan-w18-profile.json`。核心下載與 BDF 證據齊備後，主代理可執行這個入口。
核心已通過主機檢查；此次仍待有來源的 BDF/WLAN staging、完整 loader 建置與裝置驗證。
