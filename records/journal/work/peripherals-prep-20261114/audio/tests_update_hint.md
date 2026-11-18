# 合入 0118-fuxi-rpmh-arb-wlan.patch 時的宿主測試同步備忘

`work/kdraws-src/tools/test-fuxi-wlan-m6i.py`（L354）與 `tools/test-fuxi-wlan-rails.py`（L46）
會直接從 `xnu/fuxi-wlan/fuxi_wlan.c` 切片 `#define RH_STRIDE` 到 `#define FUXI_WLAN_XNU` 之間的 `rh_send_request` 程式碼，
並在自家 `PREAMBLE` 環境下編譯。

合入 `0118-fuxi-rpmh-arb-wlan.patch` 修改 `fuxi_wlan.c::rh_send_request` 後，若要執行上述兩個腳本，需在 `test-fuxi-wlan-m6i.py` 的 `PREAMBLE` 中：
1. 加入 `#include "fuxi_rpmh_arb.h"`（路徑 `-I xnu/fuxi-audio`）與 `FuxiRpmhArb fuxi_rpmh_arb = {0};`；
2. 在每次 `fixture()` 重置時同步呼叫 `fuxi_rpmh_arb_init(&fuxi_rpmh_arb);` 清除 `poisoned` 旗標。

本準備包保持 `work/kdraws-src` 完全唯讀不動；`verify_audio_host.py` 會在臨時目錄中驗證 patch 套用與 C 語法編譯。
