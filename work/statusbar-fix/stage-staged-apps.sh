#!/bin/sh
# 000 內建 App（guest 端）：把 iOS 16.7 映像 /private/var/staged_system_apps 的原廠 App（行事曆、備忘錄、時鐘、
# 計算機、地圖、天氣……共 32 個）移進 /Applications，對應的 AppPlaceholders 停放到 AppPlaceholders.fuxi-staged，
# 並把它們的 extension 補進 launchd.plist 的 AppExtensions 快取；最後刪 LaunchServices 資料庫讓 lsd 開機重建。
# 復用 ksrc/tools/sweet-root-tweaks.py 的 --install-staged-apps／--rebuild-launchservices（HackiOS 對 16.x 的做法，
# 已有主機測試 test-sweet-root-tweaks.py），這裡只加 journal／fsck 外框與前後核對。
# 使用者資料：桌面配置 IconState、偏好設定、照片等都不動；placeholder 與 App 的 bundle ID 相同，桌面位置沿用。
# 流程與 stage-launchd-disable.sh 相同：先重播 HFS+ journal、fsck、暫時標成未掛載後 rw 掛載，改完再 fsck 並標回 journaled。
set -eu
trap 'echo STAGED_APPS_STAGE_FAILED' EXIT
P=/mnt/share/hfs-journal-block-probe.py
T=/mnt/share/sweet-root-tweaks.py
[ "$(cat /sys/block/vda/ro)" = 0 ]
[ "$(cat /sys/block/vda/size)" = 41943040 ]
[ -f "$T" ]
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

python3 - <<'PY' > /tmp/before.txt
import glob, os
staged = sorted(os.path.basename(p) for p in glob.glob('/dst/private/var/staged_system_apps/*.app'))
present = [n for n in staged if os.path.exists('/dst/Applications/' + n)]
print('STAGED_BEFORE', len(staged), ','.join(staged))
print('ALREADY_IN_APPLICATIONS', len(present), ','.join(present))
print('APPLICATIONS_BEFORE', len(glob.glob('/dst/Applications/*.app')))
print('ICONSTATE_BEFORE', os.path.exists('/dst/private/var/mobile/Library/SpringBoard/IconState.plist'))
PY
cat /tmp/before.txt
grep -q '^STAGED_BEFORE [1-9]' /tmp/before.txt
sha_icon_before=$(sha256sum /dst/private/var/mobile/Library/SpringBoard/IconState.plist 2>/dev/null | cut -d' ' -f1 || true)

python3 "$T" /dst --only-optional --install-staged-apps --rebuild-launchservices

python3 - <<'PY'
import glob, os, plistlib
before = open('/tmp/before.txt').read().split('\n')
names = before[0].split(' ', 2)[2].split(',')
missing = [n for n in names if not os.path.isfile('/dst/Applications/%s/Info.plist' % n)]
left = sorted(os.path.basename(p) for p in glob.glob('/dst/private/var/staged_system_apps/*.app'))
parked = sorted(os.path.basename(p) for p in glob.glob('/dst/System/Library/AppPlaceholders.fuxi-staged/*.app'))
cache = plistlib.load(open('/dst/System/Library/xpc/launchd.plist', 'rb')).get('AppExtensions', {})
ext = sum(1 for k in cache if any(k.startswith('/Applications/%s/' % n) for n in names))
lsdb = glob.glob('/dst/private/var/mobile/Containers/Data/InternalDaemon/*/Library/Caches/*com.apple.LaunchServices-*.csstore')
print('APPLICATIONS_AFTER', len(glob.glob('/dst/Applications/*.app')))
print('STAGED_LEFT', len(left), ','.join(left))
print('PLACEHOLDERS_PARKED', len(parked))
print('EXTENSION_CACHE_ENTRIES', ext)
print('LS_DATABASES_LEFT', len(lsdb))
assert not missing, ('missing', missing)
assert not lsdb
print('STAGED_APPS_VERIFIED', len(names))
PY
sha_icon_after=$(sha256sum /dst/private/var/mobile/Library/SpringBoard/IconState.plist 2>/dev/null | cut -d' ' -f1 || true)
[ "$sha_icon_before" = "$sha_icon_after" ]
echo "ICONSTATE_UNCHANGED ${sha_icon_after:-absent}"
sync
umount /dst
check after
python3 "$P" /dev/vda --mark-journaled
python3 "$P" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check final
trap - EXIT
echo STAGED_APPS_STAGE_SUCCESS
