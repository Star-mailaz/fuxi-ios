# Fuxi BT five-clock owner preparation

2026-11-16，SM8550 / QUP2 SE6。此輪只交純值 C lease ledger、host tests與下一板級接點提案。不修改既有 BT / kernel / sync / build、不操作手機，不啟動 GENI engine、WCN、pins、rails或RCG。

## 明確 defer：沒有 native owner，不生成 MMIO callback

鎖定 Linux source 已核定五個 shared-vote clocks與common clock framework的prepare/enable refcount及serialization。但本機 `fuxi_bt_xnu.c` 只有faultable唯讀snapshot mapping；在此次核對的BT、shared RPMh與WLAN接點中，沒有找到涵蓋這五條clock及其他consumers的XNU lease provider。`fuxi_rpmh_shared` / audio arb介面是RPMh服務，不是GCC clock ownership。WLAN raw clock vote路徑也不是可供BT取得/撤回單一reference的clock owner。

因此 `fuxi_bt_clock_ledger_survey()` 永遠回傳 `DEFER`，即使五個成功lease events皆已記錄。C檔沒有read/write/acquire/release callbacks、physical地址、volatile MMIO、睡眠、mutex或kernel啟動入口。`opt_in=1`只啟用host bookkeeping，**不啟用clock或授權硬體讀取**；`opt_in=0`停用，所有state須先zero-init。

五clock source對照（GCC offsets相對`0x100000`，僅供主代理核對provider，不是raw寫入配方）：

| ledger ID | provider clock name | branch | shared `0x52010` bit |
| --- | --- | --- | --- |
| CORE | `gcc_qupv3_wrap2_core_clk` | `0x233d4` | 0 |
| S_AHB | `gcc_qupv3_wrap_2_s_ahb_clk` | `0x233d0` | 1 |
| M_AHB | `gcc_qupv3_wrap_2_m_ahb_clk` | `0x233cc` | 2 |
| CORE_2X | `gcc_qupv3_wrap2_core_2x_clk` | `0x23004` | 3 |
| SE6 | `gcc_qupv3_wrap2_s6_clk` | `0x1e754` | 10 |

五條均是`BRANCH_HALT_VOTED`；M/S AHB另有HWCG bit1。SE6 parent為`gcc_qupv3_wrap2_s6_clk_src`且`CLK_SET_RATE_PARENT`。不能以OR mask加票後恢復整個舊`0x52010`、不能清除其他consumer新增vote，或僅依CLK_OFF判定ownership；這些不是等價refcount。不能臨時寫HWCG、RCG mux/DFS、GPLL0或rails來讓讀取「成功」。

## Ledger contract / bounded failure

`begin(ledger,opt_in,now_us)`、`acquire(ledger,id,result,token,now_us)`、`tick()`、`release_begin()`、`next_release()`、`release()`只處理caller送入的完成event。任意五ID acquisition順序均可，release依實際成功順序倒序；這是bookkeeping順序，**不是已驗證的板級clock enable order**。

- `attempted`記錄所有完成acquire事件；`acquired`記錄明確取得過的refs；`owned`為尚未明確released的known refs；`released`是本輪已確認撤回的refs。
- `uncertain`表示possible lease / unknown write effect / 缺token；`retained = owned | uncertain`。token必須是provider可精準撤回此clock本輪reference的非零opaque cookie，不是raw vote值。
- acquire failure分NONE、HELD、AMBIGUOUS。HELD有token仍列入acquired，可在獨立cleanup budget撤回；AMBIGUOUS或缺token保留所有相關dependency refs，survey defer，不自動retry或release其餘clocks。
- release failureHELD / AMBIGUOUS立即停止自動unwind，保留尚未撤回refs；不可繼續關掉其parent / bus dependencies。需要provider另行有證據的reconciliation；本版本不提供強制清帳或reset。
- acquisition與release各20,000us / 32steps上限；time倒退拒絕，固定時間以steps耗盡。每個函數至多遍歷五ID，不等待。deadline檢查前先記錄完成event，因此「取得/撤回成功但晚返回」不丟失effect或再次release。
- `error`與`cleanup`分離；release成功不覆蓋原始acquire錯誤。`release_complete`只代表已確認撤回own refs，不代表clock register、engine、pins或rails已restore。超時即使最後一個release已完成仍不宣稱cleanup成功，但`released/owned`仍如實記錄。
- serialized、synchronous event delivery是前置條件。caller必須在操作前檢查ledger state / budget / ID未attempted，操作後直接送完成event；不可在in-flight provider operation期間tick、重開ledger、並發release，或丟棄返回的HELD event。此helper沒有async reservation/cancel能力，不能用來中斷不返回的硬體callback。

`next_release()`僅回傳release候選與token，沒有執行release。`CLOSED`時返回OK且clock=COUNT/token=0；`AGAIN`才是一個有效候選。terminal retained state不可reset成空ledger冒充已釋放；`begin()`拒絕有owned/uncertain refs的重入。

## 下一個實際 provider / 唯讀 survey 接點提案

主代理暫不接此ledger到手機。下一版必須先交付明確provider source與owner contract：

1. 取得SE6 / wrapper access獨占或serialized lease；共用clock manager管理上表五條clock、parent references、CX/MX / interconnect / runtime power與其他consumers。持有每個成功lease的token；clock rate與DFS不在本輪修改範圍。
2. provider需有bounded acquire與known NONE/HELD/UNKNOWN結果，以及只釋放own ref的release / retention證據。不能把Linux`clk_disable_unprepare()`的void return改解讀成Fuxi一定可finite完成或原snapshot值會完全相等。
3. 在provider證明安全bus access、device-memory ordering、fault recovery及clock穩定之前，不讀wrapper/engine。off_mask=0只是必要觀察，不是access安全或power-domain ownership的充分條件。
4. 只在上述lease持續有效時，未來readonly callback先記五branch、vote與SE6 RCG/DFS，然後wrapper version `0x8c0004`；SE6只讀`0x898064` IF_DISABLE、`0x898068` FW/protocol、`0x898040` active、M/S IRQ `0x898610/640`、DMA `0x898258`、GSI events `0x898e18`、geometry `0x898e24/28`。此版本不實作這些reads，也不讀有consume effect的RX FIFO `0x898780`、不ACK IRQ、不發command。
5. 任一clock/access/engine read不確定，停止新read並交由owner決定retained resources；不因讀取failure就盲目關掉bus或解除mapping。確認沒有本輪engine修改且access已停止，才依provider合法依賴順序撤回own leases。
6. before / held / after-release evidence應包含每clock acquired/released/retained/token、branch值、時間、provider錯誤、engine_read、read faults及ledger原始/cleanup狀態。其他consumer的refs/votes在測試期間可增加，after raw registers不一定等於before；restore成功應是own lease帳務撤回且其他consumer aggregate保持，而非覆蓋舊raw snapshot。

成功判準：actual owner證據、全部必需lease持續有效、零read fault、取得實際wrapper/protocol/IF_DISABLE/DMA/GSI/geometry、未寫engine/WCN，以及own refs完整合法釋放且其他consumers不受損。本版host fake refs不能滿足此判準。IF_DISABLE bit0=1只拒絕後續FIFO，不能自行切DMA。

## Host checkpoint / CI

```sh
python3 tools/test-fuxi-bt-clock.py
python3 tools/test-fuxi-bt-clock.py --sanitize
```

只編譯本目錄C與test內的provider mock，不需要XNU link。test沿用既有host compiler discovery，沒有修改該工具。`--sanitize`需Clang/GCC ASan+UBSan；MSVC時明確拒絕該選項。此worker只宣稱本機非sanitizer結果，Ubuntu sanitizer結果由主代理owned harness提供。

覆蓋120個acquire排列×8種外部ref baseline=960組；全部own refs按倒序撤回、外部refs不變。另35組acquire/release故障位置與before/after ambiguity effect，default-off、re-entry/duplicate/out-of-range/out-of-order/double release、elapsed/frozen/backwards time、late acquire/release effect、缺token及NONE與非零token矛盾。沒有硬體MMIO、engine survey或restore實測。

另100,000個deterministic API/state transitions混入非法ID/result、time rollback、重入與錯誤state；逐步核對owned/released disjoint、known ref conservation、retained包含uncertain及CLOSED release_complete條件。

## Primary source pins

同一Linux pin `ianchb/sm8550-mainline@1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c`，本輪重新讀取並驗證：

- [gcc-sm8550.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/clk/qcom/gcc-sm8550.c)，SHA256 `292630e2c5825ab947c9a649d8c4ec43303f17c5670dbda4062c13c35775b7d4`，五clock/bit/HWCG/parent。
- [qcom-geni-se.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/soc/qcom/qcom-geni-se.c)，SHA256 `993154d7a1045914bc464cb985518d3e7a7ec06769ff245f20c7435c879a0977`，bulk clocks / SE references、partial acquire unwind。完整resources_on/off含pinctrl；不得直接套用於本輪clock-only survey。
- [clk.c](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/drivers/clk/clk.c)，SHA256 `9d92dcd1dbeeca41bf518415f217810d60fca95c81545289cf6b1579d5c43fce`，prepare/enable reference counts及enable_lock。
- [geni-se.h](https://github.com/ianchb/sm8550-mainline/blob/1fb56e66091e71160d7c7f8e13b065d5b6ab8b8c/include/linux/soc/qcom/geni-se.h)，FIFO checkpoint已核定SHA256 `e4bd79c0b3f21dafa1a6f58db8958b811605bec9cf8b6ca92fcfe076dac21a25`，readonly survey候選的GENI offsets；UART DMA offset另由同pin的`qcom_geni_serial.c`核對。physical SE/wrapper bases來自既有Fuxi live DT/snapshot，不由Linux QRD地址或sheng board猜測。

本機既有BT snapshot、共享RPMh介面及WLAN source只用來查核native接點缺口，不當primary Linux driver的替代品；沒有宣稱本機已具備等價CCF或安全engine access。
