# Fuxi actual iOS16 Bluetooth ABI audit

日期：2026-11-16。本輪僅新增此文件與 `tools/inspect-fuxi-bluetooth-abi.py`，不重做 FIFO checkpoint、不改既有協定 / snapshot / sync / build，不 patch 或發布 Apple binaries。所有分析在 host 進行，沒有手機操作、鎖、commit 或 push。

## Actual source 與版本

實際 capture 為 `work/statusbar-fix/inspect-radio-assets-20261116-1436/`。manifest 位於該目錄的 `assets.json`，不是 `provenance/assets.json`；`provenance` 是 manifest 的 object。直接核對 `guest.log` 的 `ROOT_VERSION` / `ROOT_FILE_SENT` / `ROOT_ASSETS_INSPECT_SUCCESS`，及本地檔案完整 SHA-256 / size。

manifest 的 actual root version 為 `ProductVersion=16.7.16`、`ProductBuildVersion=20H392`。BuildID 為 `87066E3A-4442-11F1-A14D-F16241AA8750`，SystemImageID 為 `0184D69E-C5E7-4A69-B716-C4E166CD8A97`。兩個 Mach-O 均為 thin little-endian ARM64 / subtype ALL / MH_EXECUTE，不是 sheng 的 arm64e 24A446 binary。

| 本地 actual 檔案 | bytes / SHA-256 | Mach-O UUID |
| --- | --- | --- |
| `files/usr/sbin/BlueTool` | 9760944 / `5eec00a4a2a710688bc5ee453c1f3c875966374258b3d455f4347a7458cbff90` | `1EE7E57C-7DDF-351D-920D-43A8F6F6B8F1` |
| `files/usr/sbin/bluetoothd` | 8948576 / `8b7c0a0bea51544db82269d7f2775ab7996b8740927283428c4753e032df3a8f` | `AA9424E8-0648-34E2-B3CF-E6C793B9D471` |

兩檔 `LC_BUILD_VERSION` 均為 platform=2 / minimum OS=16.7.0 / SDK=16.7.3。這是編譯 metadata，不是 root 的安裝版本，不能用 SDK 值取代 manifest 的 16.7.16 / 20H392。

此 actual 擷取成功的證據取代先前 checkpoint 的「binary 尚未取得」狀態；沒有回寫舊 checkpoint 檔案。clock / rail 實測仍由主代理獨立處理，本文件不把 static binary 結果當作 FIFO 或 native stack 實機通過。

## 唯讀 inspection tool

工具預設讀取上述 manifest，先驗證版本與兩檔 size / SHA-256，才解析 Mach-O。只輸出 stdout，不執行目標 binary、不 patch、不複製 binary、不連網、不保存原始 payload。主代理可自行將 JSON 保存到私有 evidence 目錄；Apple binary 本身不得納入 source / CI artifacts。

```powershell
python -B tools/inspect-fuxi-bluetooth-abi.py --self-test
python -B tools/inspect-fuxi-bluetooth-abi.py --pattern 'uart|skywalk|chipsetID|setChipsetID:' --limit 1000 --window 32
python -B tools/inspect-fuxi-bluetooth-abi.py --pattern 'chipsetID|setChipsetID:' --format selectors --no-code
python -B tools/inspect-fuxi-bluetooth-abi.py --pattern 'uart|skywalk' --format strings --no-code
python -B tools/inspect-fuxi-bluetooth-abi.py --pattern 'uart' --function bluetoothd:0x100067610 --function bluetoothd:0x100067908 --function bluetoothd:0x1000674d0 --function BlueTool:0x10001ca84 --function BlueTool:0x10001da38 --function-limit 1024
```

`--manifest` 可指定同版本的另一個本機 manifest；`--calls` 可指定 import regex；`--objdump` 可指定本機 LLVM executable，額外記錄版本與 Mach-O header。預設 JSON 的 strings / selectors / calls / address references 各自最多 300 筆，有 total count / truncated 欄位；不能把截斷後的缺項當作不存在。

工具功能與界限：

- 驗證 load-command / segment / section / symbol / ULEB bounds，輸出 UUID、build version、dylib imports、section VM / file offsets。
- 僅接受 actual 使用的 thin ARM64 ALL，及 `DYLD_CHAINED_PTR_64_OFFSET=6`。沿真實 page chains 解析 rebase / bind，不以對 raw pointer 隨意 masking 猜 selector address；arm64e、其他 fixup format、fat images 均拒絕。
- strings 僅掃 `__cstring`、`__objc_methname`、`__objc_classname`、`__oslogstring`，不把 BlueTool 的 8 MiB embedded firmware strings 當 host 程式證據。
- selector offsets 同時列出 selector slot VM / file offset、method-name string VM；CFString references 經合法 rebase slot 解析。
- direct BL / tail-B 使用 indirect symbol table 判定 import，保留 call / stub / function-start offsets 與短 disassembly window。有限 straight-line constant recovery 處理 MOV / MOVK / ADD 等，遇 branch 或 call clobber 清除未知值；不執行控制流程、不跟間接呼叫、不做完整 taint / path proof。
- address references 只涵蓋相鄰 ADRP+ADD / LDR。沒有查到 xref 不是「不被使用」；selector 名稱不等於 method handler 或功能已完成。
- `--function BINARY:VM` 最多八個 unslid、4-byte aligned VM 請求，只能選 `BlueTool` / `bluetoothd`，且只可搭配 JSON / code analysis。以 `LC_FUNCTION_STARTS` 找 containing start、next start 與 `__text` 邊界；預設最多 256 instructions，`--function-limit` 可設 1–4096，有完整 count / truncated，不因 instruction 被截斷就宣稱沒有後續行為。
- function windows 額外輸出 direct B/BL callee 的 stub import mapping，以及 incoming B/BL、ADR、相鄰 ADRP+ADD、chained rebase references。B reference 不一律視為函數呼叫，function-pointer reference 也不證明 runtime 選中；不掃 arbitrary byte windows，不跟間接 dispatch。
- `--no-code` 不需要 Capstone；code analysis / self-test 需要 host `capstone`。本機版本為 5.0.7。工具本身不安裝 dependencies。

本機 LLVM 為 Android NDK 26.1.10909125 的 LLVM 17.0.2：

```text
%LOCALAPPDATA%\Android\Sdk\ndk\26.1.10909125\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-objdump.exe
```

已用其 `--macho --indirect-symbols` 核對 imports，並用 generic `--disassemble --start-address=0x100066e50 --stop-address=0x100066fa0` 對 actual bluetoothd 核對下節 instruction window。generic objdump 的最近符號 label 在 stripped executable 上可能誤導；callee 名稱以 indirect symbol table 的 stub mapping 為準。

## 已證實的 bluetoothd UART.SK caller

以下地址均是 **未加 ASLR slide 的 actual VM address**。本次兩檔 `__TEXT` file-backed mapping 的 VM base 為 `0x100000000`，因此以下 text 的 file offset 是 VM 減該 base；不可套用到其他 hash、24A446 或修改後 binary。

actual bluetoothd 的 function start `0x100066bdc` 直接建立 `com.apple.uart.sk.bluetooth` kernel-control connection。這不是只有 strings：同一 function 有 name materialization、socket、CTLIOCGINFO、connect 與後續 get/set option / channel creation 的 instruction 證據。

| call / reference VM | actual caller 行為 | next kernel-side contract |
| --- | --- | --- |
| `0x100066cac` | 取得 `com.apple.uart.sk.bluetooth`，string file offset `0x6d346a` | 對應命名 control；不是 BlueTool 的另一個 control name |
| `0x100066ce4` | `_socket(32, 1, 2)` | `PF_SYSTEM / SOCK_STREAM / SYSPROTO_CONTROL` |
| `0x100066d3c` | `_ioctl(fd, 0xc0644e03, &ctl_info)` | `CTLIOCGINFO`，100 bytes = uint32 id + 96-byte name |
| `0x100066e30` | `_connect(fd, &sockaddr_ctl, 32)` | sc_len=32、family=32、sysaddr=2；id 來自 query，unit 初值 0 |
| `0x100066e70` | `_getsockopt(fd, 2, 0x40487413, buffer, &length)`，length=72 | option 數值匹配 `TIOCGETA_64`；不是對 fd 呼叫 tty ioctl |
| `0x100066e78 / 0x100066e84` | `_cfmakeraw` / `_cfsetspeed` 操作同一 termios buffer | caller 會改寫 termios；baud 來自 runtime register，不能硬填 sheng rate |
| `0x1000671c8` | `_setsockopt(fd, 2, 0x80487414, buffer, 72)` | option 數值匹配 `TIOCSETA_64`；處理 caller 的 raw / speed / flow 設定 |
| `0x100066f44` | `_setsockopt(fd, 2, 0x800c5414, buffer, 12)` | UART.SK private 12-byte option，不能以 tty setter 代替 |
| `0x100066f70` | `_getsockopt(fd, 2, 0x40105412, buffer, &length)`，length=16 | buffer 隨後交給 `uuid_unparse_upper` / channel create，是 nexus UUID 交換證據 |
| `0x100066f90` | `_os_channel_create(uuid, NULL)` | 必須有真實、有效的 kernel nexus / channel，不可回傳假 UUID |

sockaddr 的 header 由 `0x100066cf4` / `0x100066cf8` materialize `0x00022020`，對應 byte32 / byte32 / uint16=2。成功 query 之後 `0x100066e1c` 載入 ctl_id，`0x100066e20` 同時填入 id 與 unit=0。這是 caller 初始值；XNU control manager 是否分配 unit 由註冊策略決定，不可從此推斷 owner 已取得。

`0x800c5414` 的 input 來自 actual readonly data VM `0x100675260`，12 bytes 解為三個 little-endian uint32：`1024, 63, 63`。本輪沒有此 private option 的 owning driver 定義，因此只確定尺寸和值，**不命名成 slot size / RX count / TX count**，也不照搬 iOS27 layout。`0x40105412` 的 16-byte UUID 用途有下游 code 支持。後續 host 延伸已定位下節 TX/RX slot caller，但 owning nexus、daemon H4 producer/parser 與完整 error contract 仍未完成。

公開 XNU8796 的 `user_termios` 是四個 uint64 flags，`c_cc[20]`，padding 後在 offset56 / 64 放 uint64 input / output speed，總長 72 bytes。若做 kernel-control shim，需明確處理 64-bit user layout / length / copy semantics；不能直接 memcpy 到 kernel 的另一個 `struct termios` 或只接受 byte baud。

這條 caller route 存在，不表示當前 kernel 已註冊 control / nexus、不表示它在 Fuxi 的 runtime factory 被選中，也不表示 QCA firmware / controller initialization 成功。

## UART.SK slot / shutdown caller：本次 host 延伸

function windows 對同一 actual bluetoothd hash 得到 writer `0x100067610..0x100067908`（190 instructions）、reader `0x100067908..0x100067b90`（162）、close `0x1000674d0..0x100067610`（80）；上界均 exclusive。它們不同於 PCIe Skywalk reader `0x10005dd04` / writer `0x10005e434`，不可用鄰近「skywalk_read」strings 把兩種 transport 混為一談。

caller 使用 64-byte stack slot properties；公開 XNU8796 `os_channel.h` 的 `slot_prop_t` 有 `sp_len` 在 offset2、`sp_buf_ptr` 在 offset16，符合 actual `[sp,#0x32]` / `[sp,#0x40]`。這是 user slot API layout 的相符證據，**不是 FIFO register 或 private `0x800c5414` 的 field 定義**。

| actual VM | 直接 instruction 證據 | 有界推論 / 接線要求 |
| --- | --- | --- |
| `0x100067654 / 0x100067660` | `os_channel_ring_id(channel,0)` → `os_channel_tx_ring` | 公開 enum 0 = FIRST_TX_RING；channel handle 是 open 存入 `0x1008494e0` 的同一 global |
| `0x100067670 / 0x100067754` | `get_next_slot(ring,NULL,&prop)` | NULL slot 會進入等待，不是 transport 已送完 |
| `0x10006768c` | caller input length 與 4096 比較，過大進入 assertion helper | 這條 writer 的 input 邊界不是 private option 的 1024 語義；length=0 為 no-op |
| `0x100067764..0x100067788` | 取 remaining 與 uint16 `sp_len` 的 min；`memmove(sp_buf_ptr,input+accepted,length)`，再回填 `sp_len` | writer 本身只分段複製 input bytes，沒有在此 routine 插入 H4 type 或自訂 slot header；slot 不等於完整 HCI packet |
| `0x100067798 / 0x1000677ac` | `set_slot_properties`，再用 previous slot 取下一個 | caller 以 accepted offset 跨 slots，不能假設一個 write 恰好一個 slot |
| `0x1000676f8 / 0x100067704`、`0x1000677d4 / 0x1000677e0` | `advance_slot(last_used)` → `os_channel_sync(channel,0)` | 公開 enum 0 = SYNC_TX；這不是 WCN wire completion 或 HCI completion 證據 |
| `0x100067734` | 無 slot 時 `kevent(kq,NULL,0,&event,1,NULL)`；filter 比較 -2 | EVFILT_WRITE readiness；NULL timeout，native loop 沒有 caller-visible finite timeout 證據，不能搬到有界 probe worker |
| `0x1000676b8` | channel global 為 NULL 時改走 `_write(fd,input,length)`，正數 partial 回圈 | fd 為同一 `0x1008441c8` global；不能推成已證實 tty route。zero return 也可能不前進，沒有 bounded contract |
| `0x10006799c / 0x1000679a8` | `ring_id(channel,2)` → `rx_ring` | 公開 enum 2 = FIRST_RX_RING；與上述 writer 使用同一 channel |
| `0x1000679e0 / 0x100067a04` | `kevent(...,NULL timeout)`、filter 比較 -1，然後 `get_next_slot` | EVFILT_READ readiness，仍不是 bounded wait |
| `0x100067a10..0x100067a48` | 使用 `sp_len` / `sp_buf_ptr`，以 downstream 回傳的下一個 chunk budget 呼叫 `0x1000e6958` | slot 可以跨 downstream chunk；`0x1000e6958` 只從 runtime table `0x100844850` 的 offset0x40 做間接跳轉，尚未連到 H4 parser |
| `0x100067a6c / 0x100067a80` | 遍歷 slots 後 `advance_slot(last_used)` | 此 reader 沒有 direct `os_channel_sync(RX)` call；不能據此省略 kernel RX reclaim / readiness contract |
| `0x100067ac0 / 0x100067adc` | 無 channel 時 `_read` → 同一 `0x1000e6958` downstream | 證明兩 route 都交付 byte chunks，不證明 factory 選中或包格式 |

writer 的 chained rebase function-pointer slot 在 `0x100844180`，open / close 在 `0x100844168 / 0x100844178`，並有同表 `POSIX` 名稱。沒有把這個 table 的 struct 或 factory selection 完整定義。reader 不是依 strings 定位：open 在 `0x1000671f0` 用 ADR 取得 `0x100067908`，經 `0x10009ba90` 到 actual `_pthread_create` caller `0x10009baf0` 的 start-routine X2。

shutdown 直接 set stop global `0x1008494e8`，向 TX/RX kqueues 送 EVFILT_USER / NOTE_TRIGGER（`0x100067550 / 0x10006756c`），close control fd（`0x100067574`），等待 reader 置 `0x1008494ec` 後才 destroy channel（`0x1000675a8`）、close kqueues（`0x1000675bc / 0x1000675d4`）。reader 在 `0x100067b04` 設 completion flag、`0x100067b10` 通知。wait helper / loop `0x10006758c..0x100067598` 沒有有限次數或 deadline 證據，**native shutdown 不能當本 helper finite hardware cleanup 的證明**。

因此最小 host contract 需要：byte-stream chunking 而非 packet-per-slot假設、partial TX/slot backpressure、RX slot release / readiness、stop→wakeup→reader退休→channel銷毀順序。H4 type 是否由上層 producer 保留、parser 如何重組跨 slots、QCA IBS / firmware HCI sequence，仍須追 runtime table owner；此處不把 raw FIFO API 直接冒充 Skywalk nexus。

## TTY / ioctl 的兩個重要反例

### `/dev/cu.bluetooth`、`/dev/uart.bluetooth` 不是已證實的 H4 open path

兩個字串位於 bluetoothd file offsets `0x6c70af / 0x6c70c1`。function `0x1000266bc` 在 `0x100026af8 / 0x100026b10` materialize 這些路徑，但實際 callee 是 stub `0x10065ff28 = _access`，不是 `_open`。`0x100026b00 / 0x100026b18` 的第二參數皆為 0，即 F_OK existence checks，並有 fallback branch。這只能證明路徑會參與 probe，不能宣稱此 daemon 已使用 tty read/write 傳 H4。

### `0x80085402` 不是 WCN7850 baud 實測或 UART 初始化證據

bluetoothd `0x100273c80` 的 `_ioctl` request 是 `0x80085402`，可對應公開 IOSerialFamily 的 `IOSSIOSPEED_64`。其 stack argument 是 8-byte speed，附近寫入 `0x300000`，即 3,145,728。可是同一 function start `0x1002739a8` 先在 `0x100273adc` 呼叫 `_openpty`，再有 fcntl / tcgetattr / cfsetspeed / cfmakeraw / tcsetattr。這是 PTY 路徑的 code，不能當作 `/dev/uart.bluetooth`、WCN boot baud 或 firmware-download rate 證據；更不能據此聲稱 driver 支援該 ioctl。

Darwin ARM64 的此 variadic ioctl caller 把第三參數指標放在 `[sp]`：例如 `0x100066d30` 與 `0x100273c74`。request 在 W1；不能只看 X2 當 payload pointer。工具只自動回復確定的 register constants，stack / descriptor 語義由實際 window 與公開 struct 定義核對。

## BlueTool 的另一個 transport / controller interface

BlueTool 的 `BT_UART` / `com.apple.uart.bluetooth` 分別位於 file offsets `0x91b8e8 / 0x91b8f0`，後者在 `0x10001d00c` 被程式取用。helper function `0x10001da38` 有 `_socket(32,1,2)` 於 `0x10001da7c`、CTLIOCGINFO `0xc0644e03` 於 `0x10001dad0`、32-byte connect 於 `0x10001db8c`。不能把 BlueTool 的 `com.apple.uart.bluetooth` 與 bluetoothd 的 `com.apple.uart.sk.bluetooth` 當同一個 endpoint。

本次延伸完成 **此 command handler 的參數鏈**：function `0x10001ca84` 的 opt byte=0x44 路徑，在 `0x10001d080` `_getenv("BT_UART")`；若 environment value 為 NULL，`0x10001d088` 把已 materialize 的 `com.apple.uart.bluetooth` 選入 X22。另一條 byte=0x64 可由 runtime optarg 覆蓋；沒有主張這是 root 的預設啟動命令。speed 未指定時，`0x10001d1e4..0x10001d1ec` 選擇 115200。`0x10001d200 / 0x10001d204 / 0x10001d208` 把 X22 name / X19 speed 傳到 helper；helper `0x10001dab0` 把同一 name 複製進 ctl_info 的 name field，成功 connect 後 `0x10001dba4` 呼叫 speed helper `0x10001dd74`。

speed helper 在 `0x10001ddc8 / 0x10001de10` 對 level2 送 72-byte `0x40487413 / 0x80487414` get/set options，呼叫 cfmakeraw / cfsetspeed。這些 return 值未形成此 helper 的成功分支檢查，最後在 `0x10001de2c` 返回 0；因此 **BlueTool helper 的 0 不能當 kernel 已接受 termios 的驗證**。115200 是此 caller fallback，不是 WCN ROM/live clock 已測值。

connect 後在 `0x10001dbf8 / 0x10001dc00` 把 command-writer `0x10001dee4` 放入 handler table offset0x428，`0x10001dc04 / 0x10001dc0c` 把 reader `0x10001dfb8` 放入 offset0x430。writer 在 `0x10001df18` 先 `_write(fd,&byte1,1)`，再把 caller payload 交 `0x10001e414`；reader `0x10001e014` 讀 type byte、`0x10001e030..0x10001e0ac` 分支處理數值2/3/4，type4 route 讀 2-byte header 後交 `0x10001e5e0` 讀 event payload。這比 strings 更強，是該 control route 的 command/event-prefix caller 證據；仍未證明 root 啟動選到此 route、kernel 消費格式、QCA reply 或完整 H4 recovery。不能將 BlueTool 的 byte1-prefix 行為套到 daemon 的 UART.SK writer（後者只複製上層 input）。

BlueTool 的 `0x10001d938` 另有 `0x4004746a = TIOCMGET`，4-byte output modem bits；本輪只確定 caller / public ioctl 相符，未證明 Fuxi tty 接受它。

另外存在實際 `IOConnectCallMethod` wrappers。下表 selector 與 inputStructCnt 都來自 caller W1 / X5，不是由字串猜測；public IOKitLib.h 定義 X5 對應 input struct 的長度，**不是 response length 或 capability mask**。

| BlueTool call VM | selector / inputStructCnt | 必須避免的誤讀 |
| --- | --- | --- |
| `0x10001a430 / 0x10001a65c` | 0 / 0，1 / 0 | 尚未證明其 binding 與 QCA 語義 |
| `0x10001a84c / 0x10001aa3c` | 8 / 0，9 / 0 | 不依數字猜 reset / power 語義 |
| `0x10001ac40 / 0x10001ae6c` | 2 / 1，3 / 1 | 1-byte input，不是回覆大小 |
| `0x10001b09c` | 4 / 32 | 32-byte input，不是 capabilities output |
| `0x10001b2f0 / 0x10001b50c` | 5 / 4，6 / 4 | 仍須追具體 user-client 與 payload fields |
| `0x10001b894` | 7 / 0 | 不把此 selector 映射成 iOS27 Type0 hook |

另一組 BlueTool wrapper 在 `0x10001e7e0` 送 selector0；其同一 function 有 `AppleBTHci` strings references，但不代表上一組 selector0–9 都屬於同一 service。bluetoothd 也有對應 wrapper groups。下一輪必須把 each family 的 IOServiceOpen type、service matching、connection ownership 與 output fields 逐一連起來，不能合併 selector namespace。

BlueTool 在 `0x100041c68` 呼叫 `_xpc_connection_create_mach_service`，直接 name `com.apple.BlueTool`、flags=1，有 actual instruction 證據。這提供 XPC service 的入口線索，不提供 message dictionary、sandbox、startup / firmware/reset RPC 的完整 ABI。

## Capabilities / factory：已定位，但尚未可用

工具可精確解析以下 actual selector slots：

| selector | slot file / VM offset | method-name string file offset |
| --- | --- | --- |
| `chipsetID` | `0x83e3a8 / 0x10083e3a8` | `0x749ae6` |
| `setChipsetID:` | `0x8401d0 / 0x1008401d0` | `0x74eff4` |

這是 dyld rebase + string identity 證據，沒有宣稱這兩個 selectors 的 method implementation 或 QCA identity 已接通。

已定位 CFString key 的 actual code references：`chipsetManufacturerNameID` 在 `0x1004edd34`，`legacyBCMChipsets / modernBCMChipsets / aciChipsets` 在 `0x1004edfe8 / 0x1004ee03c / 0x1004ee094`。其 caller families 是追 runtime model / chipset configuration 的入口，不是可以直接寫入的 QCA capabilities schema。

function `0x1003a6128` 裡有 virtual dispatch、值 0 / 2 / `0xd5` 的分支與回到 `0x1003a61b8` 的 loop。`Unknown platform/chipset/manufacturer combination, restarting` 在 `0x1003a619c` materialize，值2分支於 `0x1003a6258` 使用該字串。本輪未核定 virtual return 的 enum 語義，**不把 2 / 0xd5 映射成 Bluetooth SIG manufacturer IDs**，也不因存在此字串宣稱 QCA 必定通過或必定被拒。

local-feature callbacks 的 diagnostic xrefs 已定位 `0x10010bea0 / 0x10010bfe0 / 0x10010c118`，而 `supportsDiscoveryScanPrioritization` key 在 `0x100581a40` 有 code reference。這只是下一輪追 HCI supported commands / LMP / LE features 與 scan policy 的入口。profile / remote accessory 的「capabilities」字串很多，不能混為 host controller capabilities，也不能代替真實 HCI completion、factory selection 或 scan result。

## 下一輪最小接線與成功判準

1. 保持已交 FIFO helper / QCA probe 獨立：先由主代理驗證板級 ownership、UART / QCA version 與 finite shutdown，不因找到 native endpoint 就提前解除 bluetoothd gate 或冒充 Apple controller。
2. 若選 UART.SK，先在 host contract harness 驗證 control name、100-byte ctl_info、32-byte sockaddr、72-byte user_termios get/set、private 12-byte option、16-byte UUID / channel lifecycle；缺 owning private semantics 的 option 應明確拒絕，不回傳假成功 / 假 UUID。
3. 已取得 UART.SK slot byte-copy / RX downstream / kqueue / shutdown caller；接著追 `0x100844850` runtime table 的 H4 producer/parser，以及 private nexus / RX reclaim / disconnect。沒有 finite native wait 證據；不能直接把 FIFO raw-byte API 接入 Skywalk slots。
4. BlueTool command-handler→kernel-control→termios 已有 caller 參數鏈及 prefix code；仍分別追 IOKit families、XPC startup / reset-power / firmware RPC。把 caller 與合法 resource owner / QCA firmware sequence 對應；不能把 sheng replacement 24A446 的 instruction addresses 或 capability hooks 套過來。
5. factory / capabilities 成功需 runtime 證據：QCA identity 原值保留、supported commands / LMP / LE feature completion 被正確處理、native factory 真正選到 transport，且 lifecycle shutdown 可核對。掃描 / 配對仍需後續 HCI / userland / firmware integration，這份 static audit 沒有驗證它們。

此輪僅有 inspection tool 的 host integration；不需要增加 kernel build entry 或修改 sync。CI 可先跑 `--self-test`，不提供 Apple binaries。actual-asset audit 由主代理在持有本地 manifest / binaries 的環境執行。

掃描 / 配對剩餘工作粗估（工程工時，非承諾；不把 host 通過算作硬體完成）：板級 ownership / active UART / finite recovery 約16–40小時；WCN7850 firmware/NVM、baud/IBS、HCI identity/features 約24–64小時；iOS16 private native transport/nexus、factory與BlueTool lifecycle 約40–100小時；scan / pair / key persistence及中止恢復驗證約24–60小時。約104–264小時，前提是 owning private ABI 可以合法實現且板級 recovery 有證據；任何缺失都可能超出範圍，手機往返/CI等待未計入。下一個 host checkpoint 只針對 H4 runtime table owner，不表示已可進行掃描。

## 實際執行驗證

- `--self-test` 通過：Mach-O / file / load-command malformed bounds、ASCII offsets、ULEB truncation / overflow、chained offset / bind / reserved bits、MOV+MOVK request / call clobber、ioctl direction / size / group / number。
- 對 actual manifest 執行 JSON audit，Capstone 5.0.7 + LLVM 17.0.2 header cross-check；兩檔均解析 format6，BlueTool rebase/bind=1448/754，bluetoothd=21153/5786，selector / CFString slot unresolved=0。
- 在 `--pattern 'uart|skywalk|chipsetID|setChipsetID:' --limit 1000 --window 32` 下，BlueTool 63 direct imported calls / 7 selected strings / 0 selected selectors / 17 adjacent references；bluetoothd 94 / 15 / 2 / 21，calls / refs 未截斷。
- 額外對 actual JSON 斷言 `_access` 的兩個呼叫、CTLIOCGINFO、四個 UART.SK option requests 與 `chipsetID` slot offset。`strings` / `selectors` stdout formats 都通過。完整分析後再算兩個 SHA-256，原檔未變。
- 已以 LLVM instruction window 核對 native socket-option flow；未實機執行 BlueTool / bluetoothd、未驗證 handler / channel / capabilities，也未 patch binary。
- 本次 function-window self-test 通過：containing start / next-start exclusive bounds、instruction與incoming-reference截斷、import stub、chained function pointer、ADR，以及越界/未對齊/uint64 overflow/非法 binary/超量 requests/零 budget拒絕。
- actual 八個 function windows / incoming references 未截斷：BlueTool command handler534 / control helper171 / speed helper52 / command writer53 / reader159 instructions；daemon TX190 / RX162 / close80。斷言 `_memmove`、`_kevent` callee mapping、writer pointer `0x100844180`、reader ADR `0x1000671f0`、BlueTool getenv→control→speed與prefix讀寫 callees；完整分析後 binary hashes 不變。
- LLVM17 generic disassembly 對 daemon TX190 / RX162、BlueTool speed52 的逐一 instruction-address / count parity 通過，不依 stripped nearest-symbol label 判定 callee。
- 七個 CLI invalid regex / no-code衝突 / 非JSON輸出 / 未對齊 / 零budget / 非text VM / 九個requests案例乾淨拒絕，無 traceback；strings / selectors no-code formats 回歸通過。沒有 ASan/UBSan、native runtime或實機驗證新增 claim。

## Primary sources

actual binaries / `assets.json` / `guest.log` 為本輪 native caller 的 primary evidence。公開 header 僅提供通用 encoding / layout，不能替代 private driver 或本機 runtime 證據。

- [XNU8796 kern_control.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/kern_control.h)：CTLIOCGINFO、ctl_info、sockaddr_ctl；SHA-256 `a6dafa808253f6b59c7b2bf30a393f4a4ccf9d9eb323b870214bdc647fd3b6d6`。
- [XNU8796 ttycom.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/ttycom.h)：TIOCGETA_64 / TIOCSETA_64 / TIOCMGET；SHA-256 `13fbbbe40ede4ac4260d3de9d01f6780a9cf907b98828372dc8d26a26df4463a`。
- [XNU8796 termios.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/termios.h)：NCCS=20、user_termios 64-bit layout；SHA-256 `296b9c3459e120c331183bd6115e4e3f09c78c0a5baa55a62d9f3dfde13dcf83`。
- [XNU8796 ioccom.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/ioccom.h)：IOC direction / 13-bit size / encoding；SHA-256 `b3284ebc39413010e71d77efbae1b5ec71d2cf0b3c9ae9f2095e7fe827976694`。
- [XNU8796 socket.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/socket.h) / [sys_domain.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/sys_domain.h)：PF_SYSTEM、SOCK_STREAM、SYSPROTO_CONTROL / AF_SYS_CONTROL。
- [IOSerialFamily ioss.h](https://github.com/apple-oss-distributions/IOSerialFamily/blob/1c12ee3d9ec665bb53d0151644408d25e54fe012/IOSerialFamily.kmodproj/ioss.h)：IOSSIOSPEED_64，SHA-256 `e63d229b8db32523cb6eceaaab12b2b772a3bce90418f3c5d6a3511b25116d6b`。此公開 revision 不是本輪 actual owning iOS16 driver，僅核對同值 encoding。
- [IOKitUser IOKitLib.h](https://github.com/apple-oss-distributions/IOKitUser/blob/323ead896d04424f87184d8f6ff0cce811aab106/IOKitLib.h)：IOConnectCallMethod argument order；SHA-256 `d97b87a7d557a4281436c1a92e26abf6651242786887f03d6baa6eaff4b20e86`。不以此推導 private selector semantics。
- [dyld fixup-chains.h](https://github.com/apple-oss-distributions/dyld/blob/fd8d0c4d52320ebf64db34f3cb280310d905c5ae/include/mach-o/fixup-chains.h)：format6、36-bit target / high8 / reserved7 / next12 / bind1、4-byte stride；SHA-256 `90bd2b316ada7fc5fe47c2872ea679f0c6cc6d249ed5965dbbdc5bea5afdd21a`。這是 file-format definition pin，不是 root dyld version 的宣稱。
- [XNU8796 os_channel.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/skywalk/channel/os_channel.h)：slot_prop_t、ring/sync enum、next-slot / advance / sync user contract；SHA-256 `90abb4c7e3536e920c940a0953b58c08da61fde56b10ab97dfa6239003a445d6`。
- [XNU8796 os_channel.c](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/libsyscall/wrappers/skywalk/os_channel.c)：TX `sp_len` capacity / RX actual length、slot properties與ring head；SHA-256 `3a0589802919df133a17210170067d893f53bee941e008de5e35fddce39d83a7`。公開 wrapper 不是本次 root libsystem binary或private UART nexus的執行證據。
- [XNU8796 event.h](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/bsd/sys/event.h)：EVFILT_READ/WRITE/USER、NOTE_TRIGGER；SHA-256 `3d5bafa95e84a1528dd16ec18c2c4f2d7d8eda198a2591115f7c992ee69f5f9b`。
