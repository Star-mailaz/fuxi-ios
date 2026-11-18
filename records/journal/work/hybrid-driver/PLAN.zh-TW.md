# 混合式 GPU 驅動（CoreAnimation 快速通道）計畫

建立：2026-11-14。狀態：P0 準備中。權威實驗紀錄仍是 `work\xiaomi13-ios-gpu-20261108\continuation.md`（英文、檔尾最新）。

## 1. 目標與判準

- 同樣的畫面（不改外觀、不降解析度、不關特效）下，常用畫面都能跟上面板 120 Hz：設定捲動、開／關 app、主畫面翻頁、控制中心、鎖屏、App 資源庫。
- 不燙手；材質畫面（鎖屏日期／電池、控制中心、App 資源庫、Today、設定 header）要和現在逐像素相同。
- 任何時候不給開機參數（或 `fuxihyb=0`）就完全等於現在的行為，壞了可以只改參數退回。

## 2. 為什麼從這裡下手（已量到的數字）

0024、Settings 甩動腳本（@1）、`native-layout0024-draws-settings-boot-1`：

- backboardd 顯示執行緒每幀 CPU 約 6.5 ms；每個 GPU job 平均 90 筆 draw（p90 136）；**每筆 draw 約 72 µs**（從 CA 到核心全部算進去）。
- 依程式庫分：metal2vulkan 入口約 45%（`nmb_render_draw_indexed` 27%）、Turnip 只有約 6%、memmove 7%、malloc 家族約 8.5%、mach_msg 3.6%、Rust Mutex 2%；CoreAnimation 本身約 5%。
- 預算：TE 週期 8.27 ms；`fuxivsynctoff=6000` 下 heartbeat 到期限約 10.5 ms；一幀 = CPU ＋ GPU（3.7–6 ms）＋ 複製 0.6 ms。設定捲動已到約 119 Hz，開 app／回桌面／翻頁這些重畫面每幀 CPU 仍超過預算。

所以每筆 draw 的成本就是主槓桿：72 µs 降到 15 µs 時，136 筆只要約 2 ms（現在約 9.8 ms）。

metal2vulkan 的 draw 路徑（`metal2vulkan-runtime/src/render.rs` 的 `draw` → `draw_resident`）每一筆都跑完整的 Metal 語意模擬：tessellation／mesh 檢查、extended-range shadow、reroute、primitive restart、pass-start 複製、capture、reformat、`settle_draw`（鎖住 live 狀態）、`instantiate_draw_into`、heap sets、texture table、index bounds／rewrite pass、coverage 記帳；另外每筆都 `function_tables()`（回傳新 Vec）、`collect` storage attachment 清單。CoreAnimation 的 draw 幾乎用不到這些。`settle_draw` 本身每筆也會建 `BTreeSet`（interlocked、stored 聯集）、clone `zeroed_colors`／`dropped_colors`／amplification、組 shape 再用 `settle_shape` 查 variant——對同一個 pipeline、狀態沒變的連續 draw，這些結果都一樣，正是 L1 配方快取要省掉的。

## 3. 架構

```
CoreAnimation (backboardd)
  └─ NativeMetal ObjC 前端 ─ bridge (nmb_*) ─┬─ L1 快速通道（符合條件、配方命中）
                                              │     └─ L2 Turnip 私有入口 → 直接產生 PM4
                                              └─ L0 通用通道（現有）：metal2vulkan → Vulkan → Turnip
                                                         ↓
                                         Turnip（ir3 編譯、A7xx 狀態、GMEM、提交）→ fuxi-adreno 核心
```

- **L0 通用通道**（現有，不動）：所有不符合條件的 draw、所有非 CA 的 app 內容（遊戲、WebGL、Core Image）照舊走這裡。
- **L1 通道記錄器**（在 metal2vulkan runtime 裡）：
  - 建 pipeline 時依「結構」判定（不看 shader 名稱或雜湊，遵守 m2v 的規則）：一般 graphics、沒有 tessellation／mesh／imageblock／storage attachment／shadow stencil／amplification／sample shading／function table／tile memory。第一版**排除 framebuffer fetch**（`input_attachments` 非空）的 pipeline，0003 就是在 fetch 順序上把材質弄壞的；普查之後看它佔多少再決定。
  - encoder 追蹤每個綁定槽的 dirty 位元；符合條件且「配方」快取命中時，跳過 settle／plan／heap sets 等，只寫有變的 descriptor、push data、dynamic state，再 `vkCmdDraw*`。
  - 任何條件不符就走 L0，並讓 L1 的快取失效，狀態一致性交給 m2v 自己的記帳。
- **L2 Turnip 直出**（真正「驅動」的部分）：Turnip 加一個私有入口（暫名 `vkCmdFuxiLaneDrawsFUXI`），一次收一串壓縮過的 draw 記錄（pipeline、descriptor 位址、push data、vertex／index iova、計數、scissor），在 Turnip 內直接寫 PM4（`CP_SET_DRAW_STATE`、`CP_DRAW_INDX_OFFSET`），用 Turnip 自己的 dirty 追蹤。
  - 放在 Turnip 裡面而不是在 Rust 端塞 PM4：GMEM 模式下 draw 是錄進每個 subpass 的 draw_cs、再逐 tile 重播；只有 Turnip 內部能正確接上這套機制並維持它的狀態記錄，不會發生「在 Turnip 背後塞指令讓它狀態失準」。
  - ir3 編譯、A7xx pipeline 狀態、GMEM、同步、提交全部沿用 Turnip。

**順序**：L1 先做（不用重建 Mesa，現有前端 CI 就能出），量 L1 之後剩下的時間有多少在 Vulkan／Turnip，再做 L2。如果 L1 之後 Vulkan＋Turnip 只剩很小一塊，會把 L2 的效益重新估過再報告。

## 4. 階段

| 階段 | 內容 | 驗收 | 估時 |
|---|---|---|---|
| P0 準備 | 本文件；原始碼與建置管線盤點；Turnip 重建 CI；保留資料部署的首跑準備 | 管線都可用 | 本次 |
| P1 普查 | `fuxihyb=1`：每筆 draw 的 pipeline 條件、各 pipeline 佔比、綁定變化型態、各段 µs | 知道 L1 能涵蓋幾成 draw、預期能省多少 | 1–2 天 |
| P2 L1 原型 | `fuxihyb=2` 開快速通道；同映像只換參數做 A/B | 設定捲動／開 app 每幀 CPU 下降；材質畫面逐像素相同 | 1–2 週 |
| P3 L2 Turnip 直出 | Turnip 私有入口＋PM4 | 每筆再降；GMEM 與 sysmem 都正確 | 1–2 週 |
| P4 穩定 | 長時間使用、裝置遺失、記憶體、發熱 | 日常可用 | 約 1 週 |

## 5. P0 盤點結果

- **實際建置的 m2v 原始碼**：`work\m2vb`（git，最新提交 0009；`core.autocrlf=false`）。新補丁在這裡 commit 後 `git diff` 產生 `metal2vulkan-fuxi-00NN-*.patch`。
- **bridge（NativeMetal）原始碼**：`work\nmsrc`。
- **前端 CI**：harness `scyx2611/fuxi-metal-frontend-check-20261108`，分支 `codex/astc-layout-backport`（9eec0c0），workflow `native-metal-check.yml` 只有 workflow_dispatch → `gh workflow run native-metal-check.yml --ref <分支>`；建置 = 上游 ios-fuxi `4b8faded` 的 `tools/ci/build.sh nativemetal`，約 20 分鐘（LTO）。
- **Turnip**：手機上 `libvulkan_freedreno.dylib` sha256 `74670207…`（17878576 bytes），由 Mesa `85fda3b` ＋ UniXNU `fb6aad6a` 的 9 個補丁 ＋ `mesa-fuxi-*` 5 個補丁建出；上游 `tools/ci/build.sh mesa` 是同一套配方。harness 要加 Turnip 重建 workflow，先驗證「只重建、不改程式」能否逐位元重現；不同的話，L2 之前先做一次「只換 Turnip」的實機閘門。
- **部署**：每個 L1／L2 版本都要寫 root 映像。`work\Codex-Xiaomi13-GPU-20261109\delta-pull-hash.py`（只拉回手機上與主機基底不同的 4 MiB 區塊，在手機現況上換檔，保留桌面配置）已寫好，只在小映像測過；P1 的 0026 是第一次實跑。
- **開機參數**：使用者 loader `native-vt6tc-user-loader` 用了 592／607 字元，`fuxihyb=N` 放得下。
- **基準**：0025（bridge LTO＋tcache）A/B 只跑了 vt6 那次、沒分析，vt6tc 沒跑。P1 開機會同時重量基準。
- **參考資料**：UniXNU 的 AdrenoPM4（A740 指令封包與狀態輔助）、AirNir（MIT）只當參考；A7xx 暫存器與封包以 Turnip 本身（Mesa registers xml）為準。

## 6. P1 普查要回答的問題

1. 每幀的 draw 有幾成用的是「結構上可走快速通道」的 pipeline？被排除的主因是什麼（fetch、shader_tests、多重取樣…）？
2. CA 用到多少個不同 pipeline／variant？前 N 個涵蓋幾成 draw？（決定配方快取有多好命中）
3. 兩筆 draw 之間改了哪些綁定（pipeline、vertex bytes、fragment texture、scissor…）？（決定 L1 每筆要寫什麼）
4. 每筆 72 µs 怎麼分：`draw` 入口到 settle、`settle_draw`、`instantiate_draw_into`、其餘（heap sets、pass、Vulkan 錄製）、draw 之後的記帳，以及兩筆 draw 之間（CA＋ObjC＋bridge＋setter）。

輸出：每個執行緒每 10 秒一組 `FUXI HYB` 日誌行；解析腳本放 `work\hybrid-driver\tools\`。

### P1 結果（2026-11-14，0026，`native-layout0026-hyb1-user-boot-1`，使用者手動操作約 11 分鐘）

backboardd 主繪製執行緒 T1：671 秒 353 萬筆 draw（忙碌時每 10 秒 4–13 萬筆）。完整摘要在 `census-0026-user-boot-1.txt`。

1. **可走快速通道 79.0%**。唯一的排除原因是 framebuffer fetch（21%）；shader_tests、多重取樣、tess／mesh 一筆都沒有，執行期步驟（reformat、restart、rewrite、bounds、capture）也完全沒出現。
2. 每 10 秒用到 5–127 個不同 pipeline（variant 與 pipeline 一對一）；前 5 名佔 48%、前 12 名佔 67%。和上一筆同 pipeline 只有 19%。→ 配方快取要放得下約 128 個以上 pipeline，每筆幾乎都要切 pipeline。
3. draw 前改的綁定：vertex buffer 89%、pipeline 75%、fragment texture 44%、fragment buffer 31%、viewport 30%、sampler 20%；最常見的組合是 pipe+vbuf+ftex（16%）、pipe+vbuf（15%）、只有 vbuf（10%）。→ L1 每筆要寫的東西很少。
4. 每筆在 m2v 內 **37.4 µs ＝ 入口 2.5 ＋ settle 5.4 ＋ instantiate 3.7 ＋ 其餘 24.8 ＋ 之後 1.0**，兩筆之間 29.7 µs（合計 67 µs，與先前估的 72 µs 相符）。「其餘」是大宗；對照 0024 的精確位址 profile，draw_resident 裡真正錄 Vulkan 指令的 `Recording::record` 約佔五分之一，其他多是內聯的模擬記帳。

**推估（未實測）**：L1 讓可走的 draw 從約 37 µs 降到約 10 µs，平均每筆省約 21 µs；每幀約 100 筆時，顯示執行緒（每幀約 6.5–7.2 ms）可省約 2 ms。→ 建議照原計畫進 P2。

注意：長的普查行（sets／top）在 boot.log 會被切成片段，解析器已能重組，但 T1 的 top 只讀到 21/54 個視窗；之後的日誌行要短於 250 字元。

## 6b. P2 步驟

1. **細分「其餘」（補丁 0011，只量測）**：「其餘」24.8 µs 涵蓋 instance 判定、binding tables、uses 清單、shadow 檢查、vertex buffers、固定狀態、degrade 公告檢查、pipeline 查找、descriptor bind、錄製；只知道總數就去做快取，可能快取到便宜的部分。0011 在 draw_resident 裡加 9 個標記，每 10 秒多印一行 `rest heap= instance= tables= shadows= fixed= notices= pipe= bind= uses= rec=`。同時根治日誌被切：每行各自一次 write、每行 < 240 字元（sets 與 masks 分行、top 拆兩行）。行為不變，`fuxihyb≥1` 才開。
2. **L1 第一刀（`fuxihyb=2`）**：依 0011 的數字，先對最貴、且結果只取決於「pipeline／variant／pass 形狀／綁定沒變」的步驟做快取或跳過；每一刀都要能用 `fuxihyb=1` 退回、材質畫面要使用者目視。
3. 之後逐刀擴大，直到可走的 draw 接近只剩 descriptor 寫入＋Vulkan 錄製。

## 7. 風險

- **正確性**：L1 必須和 L0 對同一份 encoder 狀態記帳一致。任何動到 fetch／混合順序的改動，都要讓使用者看材質畫面才算數（0003 的教訓）；導覽截圖一律 `--tour-verify`，期間別碰手機。
- **部署成本**：每版 root 映像約 30–60 分鐘；保留資料流程首跑有風險，寫入前會講清楚。
- **L2 依賴 Mesa 重建**：Turnip 若重建不出相同的 dylib，要先單獨驗證。
- **效益不確定**：上面的「72 → 15 µs」是推估，P1 量完會換成實際數字再決定 P2 範圍。

## 8. 量測方法

- 固定負載：觸控腳本 @1（設定甩動）、@3、使用者手動；逐幀 frame log；`fuxivsynctoff=6000` 基準。
- 每次回報：每筆 draw µs、快速通道涵蓋率、顯示執行緒每幀 CPU、各階段 Hz、溫度。
