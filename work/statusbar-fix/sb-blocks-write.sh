#!/system/bin/sh
# 000 狀態欄（手機端）：把少數 4 MiB 區塊寫進 iOS root（mapper），寫前全部比對、寫後逐塊讀回。
# 用法：sh sb-blocks-write.sh <清單> <資料>
#   清單每行：<區塊號> <寫前應有的 sha256> <寫後應有的 sha256>；資料＝各區塊的新內容依清單順序串接（每塊 4 MiB）
#   還原：用備份目錄裡的 statusbar-undo-list.txt＋statusbar-undo.bin 跑同一支（寫前／寫後兩欄已對調）
# 任何一塊的寫前雜湊不符就一塊都不寫（代表拉回後手機又開過 iOS）。
set -eu
list=$1
data=$2
mapper=/dev/block/mapper/codexnative_root_1108b
device=$(readlink -f "$mapper")
case "$device" in /dev/block/dm-[0-9]*) ;; *) echo BAD_DEVICE; exit 10 ;; esac
node=${device##*/}
[ "$(cat /sys/block/$node/dm/name)" = codexnative_root_1108b ]
[ "$(blockdev --getsize64 "$device")" = 21474836480 ]
[ -e "/sys/block/$node/slaves/sda32" ]
if grep -q "^$device " /proc/mounts; then echo MOUNTED; exit 15; fi
count=$(wc -l < "$list")
if [ "$count" -lt 1 ] || [ "$count" -gt 64 ]; then echo "BAD_COUNT $count"; exit 16; fi
[ "$(stat -c %s "$data")" = $((count * 4194304)) ]
bsha() { dd if="$1" bs=4194304 skip="$2" count=1 2>/dev/null | sha256sum | cut -d ' ' -f 1; }
k=0
while read -r i pre post; do
  case "$i" in *[!0-9]*|'') echo "BAD_INDEX $i"; exit 11 ;; esac
  if [ "$i" -ge 5120 ]; then echo "BAD_INDEX $i"; exit 11; fi
  if [ "${#pre}" != 64 ] || [ "${#post}" != 64 ]; then echo "BAD_LINE $i"; exit 11; fi
  [ "$(bsha "$device" "$i")" = "$pre" ] || { echo "PRE_MISMATCH $i"; exit 12; }
  [ "$(bsha "$data" "$k")" = "$post" ] || { echo "DATA_MISMATCH $k"; exit 13; }
  k=$((k+1))
done < "$list"
echo "PRE_OK $count"
k=0
while read -r i pre post; do
  dd if="$data" of="$device" bs=4194304 skip=$k seek=$i count=1 conv=notrunc,fsync 2>/dev/null
  k=$((k+1))
done < "$list"
sync
echo 3 > /proc/sys/vm/drop_caches
while read -r i pre post; do
  [ "$(bsha "$device" "$i")" = "$post" ] || { echo "POST_MISMATCH $i"; exit 14; }
done < "$list"
echo "WRITE_OK $count"
