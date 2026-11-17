# Fuxi iOS 16 音訊研究準備

日期為 2026-11-16，目標 kernel source 為 `work/adsp-battery/ksrc`，iOS 路線為 16.7.16 / XNU 8796.141.3。本輪產物為 host 協定 helper、host tests 與接線計畫，執行結果來自 Windows host。硬體狀態引用既有記錄。

## 1. 可驗證的起點

- `work/adsp-battery/hw000/native-amp3-user-loader-run-1.log` 第 40、45 行記錄 B@0x40 與 T@0x42 的 DEVID `0x35a40`、REVID `0xb2`，reset GPIO 183、182 的輸入讀值 low/high `0/1`。IRQ1_STATUS3 為 `0x20000000`，STATUS4 為 `0x3`，該 probe 最後還原 pins/votes。此結果支持 I2C、晶片識別與 reset 控制的可達性。功放 DSP firmware、保護、TDM 收樣與聲學輸出仍待驗收。
- 同一記錄第 78 行附近的 ADSP 統計包含 `unknown_opens ... adsp_apps ...`。DSP 已提出 GPR channel OPEN，下一個可做的音訊步驟是為此 channel 註冊 client。
- `native-adsp2b-user-loader-run-1.log` 第 52、53 行記錄 battmgr 32、59 個回答，timeouts/errors 為 0。APM/SPF 音訊服務的 readiness 另有專屬查詢與回覆。
- 本機 DT `work/hw-survey/fuxi-live-20261116.dtb` 的 GPR node 明列 `qcom,glink-channels = adsp_apps`、`qcom,intents = <0x200 0x14>`，即 512-byte、20 個 RX intent。此值與 Sheng `AudioProbe.cpp` 第 70 行一致。
- 同一 DT 的 secondary TDM active pin nodes 明列 gpio121/SCK、gpio123/WS、gpio122/data0、gpio124/data1，功能為 `i2s1_*`。`sec_tdm_pinctrl` 引用 sleep phandles 0x387/389/38b/38d 與 active 0x388/38a/38c/38e。
- T 功放 DT 的 `rcv_gpio_high/low` 對應 gpio68。B/T 的 boost 元件值為 15 μF、1000 nH、4000 mA peak，這些是板級配置輸入，音量與安全輸出限值需要校正資料。
- WCD938x TX slave 的實際 DT 路徑是 `spf_core_platform/lpass-cdc/va-macro@6D44000/va_swr_master/wcd938x-tx-slave`。reset node 是 gpio108，codec 有四個 2750 mV micbias 設定與 RX/TX SoundWire port maps。實體麥克風到 AMIC/ADC/decimator 的對應仍需 fuxi mixer 與板級路由資料。

DT 可用既有純 host 工具重現讀取。

```powershell
python work/hw-survey/fdtgrep.py work/hw-survey/fuxi-live-20261116.dtb '(cs35l41|adsp_apps|wcd938|sec_tdm_pinctrl)' --all-props
python work/hw-survey/fdtgrep.py work/hw-survey/fuxi-live-20261116.dtb '(tdm1_|rcv_gpio)' --all-props
```

DT SHA256 為 `2d7e97ea52bf67a79ef7b99487131a41bd87fc0ab774983ce62bfb9fa79fb9fa`。

## 2. 來源與證據邊界

本機直接讀取的實作包括 `ksrc/xnu/fuxi-adsp/{fuxi_adsp.c,ShengAdsp.h,QcomGlink.h}`、既有 `ksrc/xnu/fuxi-audio/fuxi_gpr.*`、`ksrc/tools/fuxi-audio/{FuxiAudio.c,Info.plist}`、`work/ref-sheng/UniXNU-sheng/package/{ShengGpr.*,ShengAudioReach.h,AudioProbe.cpp,ShengAudioService.cpp,ShengAudioAbi.h}` 與其 `hal/ShengAudioPlugIn.c`。

本機 Linux primary source `work/adsp-battery/ref-linux/pinctrl-sm8550.c` 支持 pinmux 與 eGPIO 定義。此次搜尋涵蓋 ksrc、ref-sheng、工作區 research/prototype 目錄與舊檔位置，完整 Qualcomm downstream GPR/TDM headers、fuxi mixer/ACDB 內容尚未找到。為交叉核對 GPR，另直接讀取 Linux v6.12 primary source 的固定 tag，HTTP 429 後改用 kernel.googlesource 鏡像。下列 SHA256 是解碼後原始檔案的內容 hash。

| Primary source | 本輪讀取位置 | SHA256 |
| --- | --- | --- |
| Linux `include/linux/soc/qcom/apr.h` | 79–113，GPR header/basic result | `79a8f8408031a1503e10605f7b0007e651fa926ce0fcc95e9735de3b9fa462cf` |
| Linux `include/dt-bindings/soc/qcom,gpr.h` | 8–16，ADSP/APPS domain、APM instance | 固定 tag v6.12 |
| Linux `sound/soc/qcom/qdsp6/audioreach.h` | 33–39、341–348，SPF opcodes、APM command header | `2047e57f89967b15470498e72772515c802b341b39ac95cfe43026724155287a` |
| Linux `sound/soc/qcom/qdsp6/audioreach.c` | 205–268，GPR/APM framing | `929e6d07e27671405a7f517325158ad0f6585482e58c9e7ecdcad504d9d4dc76` |
| Linux `sound/soc/qcom/qdsp6/q6apm.c` | 149–161、778–784，SPF request/state 回覆 | `0410986834522af36ef9e5691b9f70e9f31ab5a7d225aa30bc975451890e68a1` |
| Linux `sound/soc/codecs/cs35l41.c` | DSP preload/audio events、ASP/DSP source mux | `38e509e98063404ef80402dff6d2b91de79cb8b4dd74e36b6c82c6533b62617b` |
| Linux `include/sound/cs35l41.h` | 687–710，short/temperature/OTP status | `b61ba86f014f327551dc0c2b1092f15b92089718e00dc10c7adb5611b5becedc` |

GPR layout、保留欄位與基本回覆定義可直接追溯。[Linux GPR header](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v6.12/include/linux/soc/qcom/apr.h) · [Domain / APM IDs](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v6.12/include/dt-bindings/soc/qcom,gpr.h)

SPF command framing 與 state 回覆可直接追溯。[AudioReach header](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v6.12/sound/soc/qcom/qdsp6/audioreach.h) · [Packet allocation](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v6.12/sound/soc/qcom/qdsp6/audioreach.c) · [APM readiness](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v6.12/sound/soc/qcom/qdsp6/q6apm.c)

功放 DSP 與 fault definitions 可直接追溯。[CS35L41 codec driver](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v6.12/sound/soc/codecs/cs35l41.c) · [CS35L41 definitions](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/refs/tags/v6.12/include/sound/cs35l41.h)

本機 ShengGpr.h / ShengGpr.c SHA256 分別為 `a274dded1f4d1e2709b9f966759bcb1f57d12747ee0f57743dea1fa97d95d23e`、`c4f498f07e2cb601b593e64a8d32474a21d6a87375618e1a67b99d52c5d3160e`。Sheng 文件 `UniXNU/docs/devices/sheng.md` 第 563 行記錄播放 155 periods sent / 151 returned，第 565 行記錄音樂與 Voice Memos 的另一輪結果。這些是 Sheng 的實驗記錄。Fuxi 的 codec 型號、功放數量、TDM、firmware、mic route 與 iOS 16 ABI 需要各自驗收。

## 3. 本輪可使用的協定 helper

新增 `xnu/fuxi-audio-prep/fuxi_audio_prep_gpr.{h,c}`，API 使用固定寬度欄位、顯式 little-endian byte 存取與 caller-owned buffer。執行只會讀寫呼叫者提供的 RAM，依賴 `memmove`，沒有裝置傳輸 callback。

| API | 契約 |
| --- | --- |
| `fuxi_audio_prep_gpr_encode` | 生成 version 0、24-byte GPR header，domain 必須在 u8 範圍，payload 可與 output 重疊 |
| `fuxi_audio_prep_gpr_decode` | 驗證完整 GLINK message，成功回傳借用 input 的 payload view |
| `fuxi_audio_prep_spf_query` | 生成 ADSP domain 2 / APPS domain 3、dst APM port 1 的 GET_SPF_STATE 查詢 |
| `fuxi_audio_prep_spf_reply` | 驗證雙向 domain、src APM port、dst local port、token、opcode 與精確 payload 長度 |

GPR header 第一個 u32 的 version 為 bits 3:0、header words 為 7:4、packet bytes 為 31:8。第二個 u32 的 dst/src domain 為 bits 7:0/15:8，16:31 為 reserved。之後依序是 src port、dst port、token、opcode 四個 u32。

三個已核對的命令值為 `GET_SPF_STATE = 0x01001021`、`SPF_STATE_REPLY = 0x02001007`、`BASIC_RESULT = 0x02001005`。State payload 為單一 u32，state 1 是 readiness 判準。Basic result payload 為 `{original_opcode, status}`，status 0 只會回報 `SpfAccepted`，owner 繼續等待 SPF state。

### Framing 決策

Linux v6.12 `q6apm_get_apm_state()` 呼叫帶 APM command header 的 allocator。這個 header 有 address lsw/msw、mem_map_handle、payload_size 四個 u32，無附加 payload 時全為 0。新 helper 依此生成 40 bytes，local_port/token 由 caller 指定。預設 APM local port 可採 Linux 的 1，其他 port 由註冊與回覆路由一起管理。

本機 Sheng 與既有 fuxi helper 的 readiness query 為 24 bytes。兩個 framing 都有具名實作可追溯，fuxi 當前 firmware 的接受情況尚待下一階段實測。這輪選擇 Linux 的 40-byte framing，golden vector 固定驗證這個選擇。Owner 若需要評估 Sheng framing，應各自記錄 firmware、送出 bytes、回覆與 timeout。

### 邊界與生命週期

- Packet 上限設為 560 bytes，對齊當前 `ShengAdsp.h` 的 `SHENG_ADSP_MAX_MESSAGE`。這是本 helper 的 transport 限制，GPR wire size 欄位本身是 24 bits。RX owner 仍以實際 intent size 為額外上限。
- Decoder 接受 version 0 的 6–15 words header，延伸 header bytes 當作 opaque 資料，payload 起點使用已驗證的 header size。
- Decoder 要求 packet size 等於收到的完整 message length，reserved bits 為 0。這是本 helper 的嚴格接收規則，可在 firmware 出現合法差異時依具體 capture 修訂。
- 每個失敗返回都保持 caller 的 output、written、view/reply 原值，成功才發佈結果。有效 payload 的 extent 由 caller 保證，metadata 與 written/view/reply 的儲存區應與 packet buffer 分開。
- 解碼 view 的生命週期跟隨 input。GLINK callback buffer 僅在 callback 內有效，跨 thread 處理需先複製完整 message。
- Token 採原值比對。Pending query、重試次數、timeout、斷線後 generation 與晚到回覆由 owner 管理。

## 4. 最小實作路徑與現有接點

### A. GPR / SPF 的無聲接線

1. 重用 `fuxi_adsp.c` 已存在的單一 ADSP owner，於其啟動後用 `sheng_adsp_channel("adsp_apps", 512, 20, 0, ...)` 註冊一個 client。`FA_CLIENTS = 4`、`FA_QUEUE = 8`，整合者先核對同輪 client 數量。`gStarted` 是註冊前置條件。
2. RX/state callbacks 只複製必要 message 與狀態，喚醒 audio worker。`fuxi_adsp.c` 的 callback 契約禁止 blocking 與 reentrant send，worker 使用既有 `sheng_adsp_send()` 排入 owner queue。
3. Channel up 後生成一個 SPF query，只有 queue 接受才開始 pending 計時。Query 上限、answer deadline 與 retry delay 應做有界設定，建議初輪最多三次、每次 2–5 秒並列於測試記錄。
4. 全路由匹配且 state 1 才發佈 `spf_ready`，記錄 raw state/basic status。Channel down、ADSP fatal、queue refusal、timeout 都使該輪 pending 失效，下一 generation 更新 token。
5. 驗收需要成功 state reply、錯誤路由/late reply 的忽略計數、timeout 恢復，以及 battmgr 持續成功。這會建立 DSP 音訊服務的可用性證據。

### B. AudioReach / LPASS TDM / buffer

接著用 fuxi TDM endpoint 建立 device graph，PCM write-shmem endpoint、decoder/converter 與連接形成 stream graph，依來源規格執行 open/configure/prepare/start/stop/close。Graph/subgraph/module instance IDs 是選定 topology 與 client allocator 的共同輸入。Sheng 的 `0x400x/0x60xx` 配置需以 fuxi topology 重建。

目前直接取得的 upstream v6.12 AudioReach headers 包含 I2S 與 codec DMA endpoint。Secondary TDM 的 module/parameter ID、wire layout、interface/LPAIF selector、slot mask、slot width、frame format、clock attribute 要從符合 fuxi firmware 的 Qualcomm downstream audio-kernel headers 與 vendor route 資料補齊。這輪 helper 的已核對常數僅涵蓋 GPR 與 SPF。

Playback buffer 採具名保留區、alignment、DSP addressability、map handle 與完成 token 管理。要查清實際 IOMMU/VM ownership、stream IDs、cache maintenance 與 32/64-bit address encoding。Sheng 的低 DRAM PA 與 stream-index 高字規則是該版 firmware 的實驗結果。Fuxi 可用 PA 必須以當前 ADT/reserved-memory、RAM 與 hypervisor 資料驗證。

當前 owner 每個 send 最多 560 bytes，未來較大的 graph/config packet 需要先確認合法 graph 分批方式或擴充 owner queue。GLINK remote intent 4 KiB 的能力與 AP send queue 的上限需一併處理。Playback write-done 的證據需搭配 DSP buffer address/status、TDM clock/frame 與實際 rendered timeline。

### C. CS35L41 保護與設定

先建立 fuxi/REVID b2 專用的 OTP/trim、boost 元件、ASP/TDM、PLL、DSP preload、WMFW/coefficient 與保護啟動順序，確認每個依賴的來源與錯誤回復。既有 ID probe 的 STATUS3/4 用於 OTP 狀態讀取。Audio session 還需要 PLL lock、short/overtemp faults、保護 DSP mailbox/狀態、IV/temperature feedback 與每顆喇叭 calibration。

功放設定及發聲測試進入使用者另行批准的硬體階段。Receiver gpio68、amp resets、boost、PCM Source、DSP mode 與音量的操作都由該階段統一管理。Protected playback 的安全輸出值由原機保護/校正資料與測量決定。

### D. iOS 16 userland / driver

最短接點是既有 `tools/fuxi-audio/FuxiAudio.c` 的 AudioServerPlugIn。它已有 Speaker/Hawking/Codec 等物件、`start_io`、`stop_io`、`get_zero_time_stamp`、`do_io_operation` 與 system HAL 安裝入口。第 958–978 行的輸出目前累計 frames，input 使用靜音資料。後續可讓 Speaker 的 WriteMix 與 Codec 的 ReadInput 接到 kernel shared rings。

Kernel 端可用 IOService + IOUserClient，提供 control page、output ring、input ring 的 `clientMemoryForType`，以 `externalMethod` 排入 start/stop 請求。`ShengAudioService.cpp` 第 75–126 行與 `ShengAudioAbi.h` 提供現成介面範例，整合時重用其記憶體/時間線設計並核對 iOS 16 ABI、sandbox hook 與 caller 權限。要處理 client close、server crash、DSP reset、pending buffer completion 與多 client start/stop 的一致性。

Userland chain 為 AVAudioSession / AudioQueue / AudioUnit → mediaserverd audio HAL → AudioServerPlugIn → IOUserClient rings → audio worker → GPR/AudioReach。HAL bundle 的 factory UUID、code signature/trustcache、arm64/arm64e target、載入路徑與 VirtualAudio route properties 需要對當前 iOS 16 image 驗證。Sheng Info.plist 的 MinimumOSVersion 是 17.0，其 Thunderbolt transport 經驗留作實驗輸入。

時間戳必須同時校驗 `mach_timebase_info`、CoreAudio `AudioGetHostClockFrequency`、counter Hz、sample rate、zero timestamp seed、safety offset 與 ring lead。Sheng 使用 19.2 MHz timer，曾在 CoreAudio 的 24 MHz 常數造成 pacing 差異，該修補位址與指令辨識需要按 iOS 16 image 重做。

另一個接點是該 iOS image 的 `IOAudio2Device` / user client。`docs-lanes/audio.md` 第 86–116 行留下 kernelcache/dyld strings 的早期分析，selector、memory layout 與方法簽名仍需當前 binary 驗證。AudioServerPlugIn 路徑已有本機源碼，可先推進 rings 與普通 PCM 播放/錄音。

## 5. 必需 firmware、topology、保護資料

| 資料 | 已有證據與用途 | 尚需確認 |
| --- | --- | --- |
| `adsp.mdt`、實際 `.bNN` segments，`adsp_dtb.mdt/.bNN` | 既有 owner 從 modem FAT 讀取並啟動 ADSP | 固定目前可用版本與 hash，確認 audio PD / SPF readiness |
| Qualcomm matching downstream GPR/APM/PRM/TDM headers | Linux/Sheng 支持 generic GPR 與 SPF | TDM module/param、LPASS resource、PRM clock IDs 與命令語義 |
| fuxi `mixer_paths*`、`resourcemanager_kalama_mtp.xml`、`card-defs.xml`、`usecaseKvManager.xml`、audio policy | `docs-lanes/audio.md` 記錄 speaker → `TDM-LPAIF-RX-SECONDARY`、T slot 0/B slot 1 | 取得 XML primary content，核對 slots、格式、speaker/receiver/mic route |
| ACDB/workspace/topology | 舊 lane 記錄 `Tutu_acdb_cal.acdb`、`Tutu_workspaceFileXml.qwsp` | 確認 fuxi 的實際 SKU/firmware 檔案，抽出 module、KVs、calibration 與連接 |
| CS35L41 `.wmfw/.bin` | 舊 lane 列 `cs35l41-dsp1-spk-prot.wmfw`、`cs35l41-dsp1-spk-cali.wmfw` 與 B/T 各自的 prot/cali `.bin` | DSP revision、WMFW loader、係數對應、mailbox/狀態與板級保護流程 |
| B/T fast-switch profiles | 本輪 DT 明列 B-music/B-handfree、T-music/T-handset/T-handfree `.txt` | 原始檔內容、fast-switch 格式與 receiver 增益限制 |
| per-device speaker calibration | 每顆喇叭需要正確 resistance/temperature/保護係數 | 原機 persist/audio 資料、校正版本與有效旗標，必要時原機 calibration 流程 |
| DSP 動態 modules | 舊 lane 列 `capi_cirrus_sp.so` 與 rfsa/adsp/module firmware | 實際 AMDB module 可用性、FastRPC/servreg 依賴與載入紀錄 |
| WCD938x / mic route | 本輪 DT 有 codec、supplies、SoundWire port maps、micbias | AMIC/ADC、decimator、micbias 與 DMIC/secondary mic selection |

Vendor filenames 中只有 fast-switch `.txt` 名稱由本輪 DT 直接核對，其餘專有檔名沿用既有 lane 的研究索引，內容與所在 SKU 尚待確認。若固件已有所需靜態 modules，簡單 PCM graph 可依公開規格自行構造。完整 ACDB-dependent processing 與 speaker protection 仍需匹配資料。應先以 SPF/module 回覆與原機 service 記錄判定動態載入依賴。

## 6. 下一階段硬體測試條件

第一輪無聲 GPR 測試需要主代理核准並整合 opt-in client，使用當前可用 ADSP firmware，讓 amp session 維持既有停用狀態。觀察 channel up、SPF state、token/domain/port、queue refusal 與 timeout，同時記錄 battmgr 與 ADSP fatal/crash reason。

LPASS/功放設定與實際播放需要另一階段授權，並準備以下條件。

1. TDM module/param、格式、slot mask、clock 與合法 buffer PA 有 primary evidence，先核對 clock/frame 與全零 PCM。
2. fuxi CS35L41 b2 的 init、OTP、boost、保護 firmware、每顆 calibration 與 fault rollback 已評審，輸出起始狀態為 mute。
3. 能量測 SCK/WS/data 與每顆 amp 的 PLL、DSP mailbox、faults、temperature/current。保護或 clocks 失效要在 timeout 與 stop 路徑確實 mute/停 session。
4. 測試由低輸出、單顆、短 session 漸進，數位幅度、音量與時間由保護規格及台架量測設定，每步記錄 rendered frames、faults 與聲學輸出。
5. Kernel/userland start/stop、client death、ADSP reset、buffer completion、熱態與長時間播放各有可觀察計數與回復結果。

Capture 階段需要另外確認 codec supplies、gpio108 reset、SoundWire master/slave ownership、micbias 與 input route，驗證實際 buffer bytes/offset、短回覆、單調時間戳、靜音與可控外部聲源的對照。

## 7. 播放、麥克風與語音的剩餘關卡

| 能力 | 剩餘關卡 | 驗收證據 |
| --- | --- | --- |
| 一般播放 / 系統提示音 | GPR/SPF → fuxi TDM graph → shmem/clock → CS35L41 protection/config → HAL rings / default route / volume | T/B 指定 channel 實際聲音、buffer/timestamp/PLL/faults、開始停止與重複播放、iOS app 與系統提示音 |
| 麥克風錄音 | SPF → LPASS VA/TX resources → WCD938x supplies/SoundWire → 實體 mic/micbias/ADC/decimator → capture graph → input HAL / permission | 受控聲源錄音、buffer bounds、短 period、DC/noise/clipping、route/channel、Voice Memos 保存與重播 |
| VoIP / 雙向語音 | 播放與錄音 → AVAudioSession PlayAndRecord / VoiceChat、receiver gpio68/profile、低延遲 duplex、AEC/NS/AGC 與 interruption | 真正遠端通話、聽筒與 speakerphone 切換、回音/延遲、mute、背景與鎖屏、插拔與音訊中斷 |
| 蜂巢語音 | AudioReach voice/VCPM/modem endpoints、modem service/telephony stack、voice calibration、iOS 通話 route | 真實蜂巢雙向通話與切換，依 modem/telephony 可用程度排程 |

播放與麥克風完成後，VoIP 才能進入完整 duplex 驗收。蜂巢語音另依賴 modem/telephony 工作的結果。

## 8. 粗估工時

以下是工程人時，假設一名熟悉現有 XNU/GLINK 的工程師，主代理提供可用建置/觀察流程與匹配 firmware/topology/calibration。等待資料、設備授權與排隊時間另計，來源缺口或私有 ABI 逆向會擴大範圍。

| 工作 | 實作人時 | 驗收人時 |
| --- | --- | --- |
| 無聲 GPR client / SPF / timeout / reset | 8–16 | 4–8 |
| TDM endpoint、graph、buffer、clock | 24–48 | 8–16 |
| CS35L41 loader/init/protection/calibration 接線 | 32–64 | 16–32 |
| iOS16 HAL/IOUserClient/rings/clock/default route | 24–48 | 12–24 |
| 麥克風額外工作 | 32–64 | 16–32 |
| VoIP/receiver/VoiceProcessing 額外工作 | 48–96 | 24–48 |

一般播放合計約 88–176 小時實作加 40–80 小時驗收，即 128–256 人時。麥克風在共用音訊基礎上再加 48–96 人時，VoIP 再加 72–144 人時。蜂巢語音在 modem/telephony 已可用的前提下暫估另加 120–320 人時，當前依賴狀態使信心偏低。

## 9. Host 驗證與交付

新增檔案為此文件、`xnu/fuxi-audio-prep/fuxi_audio_prep_gpr.h`、`xnu/fuxi-audio-prep/fuxi_audio_prep_gpr.c`、`xnu/fuxi-audio-prep/test_gpr.c` 與 `tools/test-fuxi-audio-prep.py`。

在 workspace root 可執行以下兩個命令。

```powershell
python work/adsp-battery/ksrc/tools/test-fuxi-audio-prep.py
python work/adsp-battery/ksrc/tools/test-fuxi-audio-prep.py --sanitize
```

兩輪都通過 `PASS fuxi-audio-prep GPR: 26005 checks`。本機 compiler 為 MSVC 14.50，C11 `/W4 /WX`。`--sanitize` 在本機使用 AddressSanitizer，Clang/GCC 路徑則設定 ASan + UBSan。本輪 UBSan 尚未執行。

測試包含獨立 hard-coded wire golden vectors、全部 0–536 bytes payload roundtrip、256 組 domain、32-bit port/token、24–60 bytes header、所有截斷長度的精確 heap buffer、尾隨資料、reserved/version/size、SIZE_MAX、output 前後 canary、兩個方向的 payload overlap，以及 SPF 假路由/過期 token/錯 opcode/短長 payload/basic acknowledgement/remote error。另逐一變異 header 的每個 byte 的 256 個值，檢查成功 view 的 extent 與 SPF 接收條件。

尚待下一階段驗證的部分為 kernel build 接線、GPR 在 fuxi firmware 的 40-byte query 接受情況、hardware audio、iOS HAL load 與實際 app 路由。
