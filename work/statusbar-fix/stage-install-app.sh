#!/bin/sh
# 000 第三方 App（guest 端）：把 resign-app-adhoc.py 重簽好的 App（唯讀磁碟 /dev/vdc 上的 tar）裝進 /Applications，
# 實際安裝在 install-app-guest.py（主機測試：install-app-guest.py self-test）；這裡只做 journal／fsck 外框與前後核對，
# 外框與 stage-staged-apps.sh 相同：先重播 HFS+ journal、fsck、暫時標成未掛載後 rw 掛載，改完再 fsck 並標回 journaled。
# 使用者資料：桌面配置 IconState、偏好設定、照片等都不動；新 App 由 SpringBoard 自己排到最後一頁。
set -eu
trap 'echo INSTALL_APP_STAGE_FAILED' EXIT
P=/mnt/share/hfs-journal-block-probe.py
T=/mnt/share/sweet-root-tweaks.py
G=/mnt/share/install-app-guest.py
[ "$(cat /sys/block/vda/ro)" = 0 ]
[ "$(cat /sys/block/vda/size)" = 41943040 ]
[ -b /dev/vdc ]
[ "$(cat /sys/block/vdc/ro)" = 1 ]
[ -f "$T" ] && [ -f "$G" ]
(cd /mnt/share && sha256sum -c tweaks-sha256.txt)

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

python3 "$P" /dev/vda --apply > /tmp/replay.txt
cat /tmp/replay.txt
grep -qxE 'JOURNAL_REPLAYED|JOURNAL_EMPTY' /tmp/replay.txt
python3 "$P" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check before
python3 "$P" /dev/vda --mark-unmounted
mkdir -p /dst
mount -t hfsplus -o force,rw /dev/vda /dst
grep -q ' /dst hfsplus rw' /proc/mounts

echo "APPLICATIONS_BEFORE $(ls -d /dst/Applications/*.app | wc -l)"
sha_icon_before=$(sha256sum /dst/private/var/mobile/Library/SpringBoard/IconState.plist 2>/dev/null | cut -d' ' -f1 || true)

python3 -I "$G" install /dst /dev/vdc /mnt/share

echo "APPLICATIONS_AFTER $(ls -d /dst/Applications/*.app | wc -l)"
sha_icon_after=$(sha256sum /dst/private/var/mobile/Library/SpringBoard/IconState.plist 2>/dev/null | cut -d' ' -f1 || true)
[ "$sha_icon_before" = "$sha_icon_after" ]
echo "ICONSTATE_UNCHANGED ${sha_icon_after:-absent}"
df -k /dst | tail -1
sync
umount /dst
check after
python3 "$P" /dev/vda --mark-journaled
python3 "$P" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check final
trap - EXIT
echo INSTALL_APP_STAGE_SUCCESS
