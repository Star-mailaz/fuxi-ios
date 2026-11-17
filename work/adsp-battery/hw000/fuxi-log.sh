#!/usr/bin/env bash
# 獨立開機（b 槽，沒有 USB）的 iOS console 紀錄：核心 fx_log 把 console 每 10 秒寫進 mtdblk 分區前（小米 13 沒有 logdump；mtdblk 全空、Android 不用） 2049 個 4 KiB 區塊，
# 前提是 Android 先在區塊 0 的 byte 2048 蓋上 "FUXILOG1 STAMPED"（沒蓋章核心一個位元組都不寫）。手機要在 Android（a 槽、root）。
#   survey  只讀：mtdblk 的實體裝置、LUN、大小、前 8 MiB 有沒有資料
#   stamp   先把整個 mtdblk 備份到 D:\xiaomi13\fuxi_Backup\mtdblk-<日期>\（第一次才備份），再把區塊 0 換成蓋章區塊
#   pull    拉回前 2049 區塊到 work\adsp-battery\fuxilog\<時間>\，解析成 console.txt
set -euo pipefail
export MSYS_NO_PATHCONV=1
S=${FUXI_ANDROID_SERIAL:?set FUXI_ANDROID_SERIAL to the adb serial of the phone}
W=/d/xiaomi13/fuxi_ios/work
H=$W/adsp-battery/hw000
LOCK=$W/PHONE-LOCK-000
DEV=/dev/block/by-name/mtdblk
AREA=2049
say() { echo "$(date +%H:%M:%S) $*"; }
su_sh() { adb -s $S shell "su -c '$1'" | tr -d '\r'; }
MODE=${1:?survey|stamp|pull}

[ -e "$LOCK" ] && { say "STOP: lock exists"; exit 2; }
[ "$(adb -s $S shell getprop sys.boot_completed | tr -d '\r')" = 1 ] || { say "STOP: android not up"; exit 2; }
echo "000 硬體適配線 fuxi-log.sh $MODE pid $$ 自 $(date '+%F %T') 起讀寫 mtdblk（約 1 分鐘，手機留在 Android），結束自動刪除" > "$LOCK"
trap 'rm -f "$LOCK"; adb -s $S shell "su -c \"rm -f /data/local/tmp/fuxilog-*\"" >/dev/null 2>&1 || true' EXIT

real=$(su_sh "readlink -f $DEV")
[ -n "$real" ] && [ "$real" != "$DEV" ] || { say "STOP: no mtdblk partition"; exit 3; }
bytes=$(su_sh "blockdev --getsize64 $real")
say "mtdblk -> $real, $bytes bytes ($((bytes / 4096)) blocks)"
[ "$bytes" -ge $((AREA * 4096)) ] || { say "STOP: mtdblk smaller than the log area"; exit 3; }

case $MODE in
survey)
  su_sh "ls -l /dev/block/by-name/ | grep -i -E \"log|dump\""
  su_sh "dd if=$DEV bs=4096 count=$AREA 2>/dev/null | od -A d -t x1 | head -12"
  nz=$(su_sh "dd if=$DEV bs=4096 count=$AREA 2>/dev/null | tr -d \"\\\\000\" | wc -c")
  say "non-zero bytes in the first $AREA blocks: $nz"
  su_sh "dd if=$DEV bs=1 skip=2048 count=16 2>/dev/null"; echo
  ;;
stamp)
  B=/d/xiaomi13/fuxi_Backup/mtdblk-$(date +%Y%m%d)
  if [ ! -e "$B/mtdblk.img" ]; then
    mkdir -p "$B"
    su_sh "dd if=$DEV of=/data/local/tmp/fuxilog-backup.img bs=1048576 2>/dev/null; sha256sum /data/local/tmp/fuxilog-backup.img" | tee "$B/phone-sha256.txt"
    adb -s $S pull /data/local/tmp/fuxilog-backup.img "$(cygpath -m "$B/mtdblk.img")" | tail -1
    want=$(cut -d' ' -f1 "$B/phone-sha256.txt")
    got=$(sha256sum "$B/mtdblk.img" | cut -d' ' -f1)
    [ "$want" = "$got" ] || { say "STOP: backup hash differs ($want vs $got)"; exit 4; }
    echo "$got  mtdblk.img ($real, $bytes bytes, $(date '+%F %T'))" > "$B/SHA256SUMS"
    say "backup $B/mtdblk.img $got"
  else
    say "backup already at $B/mtdblk.img"
  fi
  python - "$(cygpath -m "$H/fuxilog-stamp.bin")" <<'EOF'
import sys
b = bytearray(4096)
b[2048:2064] = b'FUXILOG1 STAMPED'
open(sys.argv[1], 'wb').write(b)
EOF
  adb -s $S push "$(cygpath -m "$H/fuxilog-stamp.bin")" /data/local/tmp/fuxilog-stamp.bin | tail -1
  su_sh "dd if=/data/local/tmp/fuxilog-stamp.bin of=$DEV bs=4096 count=1 conv=notrunc,fsync 2>/dev/null; sync"
  a=$(su_sh "dd if=$DEV bs=4096 count=1 2>/dev/null | sha256sum" | cut -d' ' -f1)
  [ "$a" = "$(sha256sum "$H/fuxilog-stamp.bin" | cut -d' ' -f1)" ] || { say "STOP: stamp read-back differs"; exit 5; }
  rm -f "$H/fuxilog-stamp.bin"
  say "STAMPED $DEV block 0"
  ;;
pull)
  O=$W/adsp-battery/fuxilog/$(date +%Y%m%d-%H%M%S)
  mkdir -p "$O"
  su_sh "dd if=$DEV of=/data/local/tmp/fuxilog-area.bin bs=4096 count=$AREA 2>/dev/null"
  adb -s $S pull /data/local/tmp/fuxilog-area.bin "$(cygpath -m "$O/area.bin")" | tail -1
  python -I "$(cygpath -m "$H/fuxi-log-parse.py")" "$(cygpath -m "$O/area.bin")" "$(cygpath -m "$O/console.txt")"
  say "PULLED $O"
  ;;
*) say "unknown mode $MODE"; exit 1 ;;
esac
