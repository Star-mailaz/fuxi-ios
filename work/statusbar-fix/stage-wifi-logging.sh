#!/bin/sh
set -eu
trap 'echo WIFI_LOGGING_STAGE_FAILED' EXIT
probe_script=/mnt/share/hfs-journal-block-probe.py
[ "$(cat /sys/block/vda/ro)" = 0 ]
[ "$(cat /sys/block/vda/size)" = 41943040 ]
grep -qxE 'enable|disable' /mnt/share/wifi-logging.txt

check() {
  fsck.hfsplus -fn /dev/vda > "/tmp/fsck-$1.txt" 2>&1 || true
  cat "/tmp/fsck-$1.txt"
  if grep -q "appears to be OK" "/tmp/fsck-$1.txt"; then
    echo "FSCK_$1 OK"
    return 0
  fi
  bad=$(grep -E '^[[:space:]]+[^[:space:]]' "/tmp/fsck-$1.txt" | grep -vE 'Executing fsck_hfs|The volume name is|Orphaned open unlinked file' || true)
  [ -z "$bad" ] || { echo "FSCK_$1 NOT_CLEAN"; return 1; }
  echo "FSCK_$1 OK_APART_FROM_ORPHANS"
}

python3 "$probe_script" /dev/vda --apply > /tmp/replay.txt
cat /tmp/replay.txt
grep -qxE 'JOURNAL_REPLAYED|JOURNAL_EMPTY' /tmp/replay.txt
python3 "$probe_script" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check before
python3 "$probe_script" /dev/vda --mark-unmounted
mkdir -p /dst
mount -t hfsplus -o force,rw /dev/vda /dst
grep -q ' /dst hfsplus rw' /proc/mounts
python3 /mnt/share/configure-wifi-logging.py --root /dst --action "$(cat /mnt/share/wifi-logging.txt)"
sync
umount /dst
check after
python3 "$probe_script" /dev/vda --mark-journaled
python3 "$probe_script" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check final
trap - EXIT
echo WIFI_LOGGING_STAGE_SUCCESS
