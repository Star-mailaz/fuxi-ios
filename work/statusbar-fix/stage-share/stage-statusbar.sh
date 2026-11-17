#!/bin/sh
# 000 狀態欄：以「手機拉回的現況」為底，只加一個 UIKit 偏好鍵，不動任何系統檔、不注入程式碼。
#   UIKit（iOS 16）的 _UIStatusBarGetVisualProviderClassForScreen 對內建螢幕會先讀
#   _UIKitUserDefaults()（suite com.apple.UIKit）的 UIStatusBarVisualProviderClassName，
#   是 _UIStatusBarVisualProvider 子類就直接用它（並記 log「Using overridden status bar visual provider class」）。
# 寫入：/var/mobile/Library/Preferences/com.apple.UIKit.plist（原本不存在，新建；還原＝刪檔）
#       /var/mobile/Library/Preferences/.GlobalPreferences.plist 加同一鍵（沙盒 App 一定讀得到全域網域；還原＝刪鍵）
# journal 重播／fsck／標記的順序照 hybrid-driver/stage-test-phonebase.sh。只寫 /dev/vda（qcow2 疊加層）。
set -eu
trap 'echo STATUSBAR_STAGE_FAILED' EXIT
P=/mnt/share/hfs-journal-block-probe.py
CLASS=$(tr -d '\r\n' < /mnt/share/class.txt)
case "$CLASS" in
  _UIStatusBarVisualProvider_Split1080|_UIStatusBarVisualProvider_Split1125|_UIStatusBarVisualProvider_Split1170|_UIStatusBarVisualProvider_DynamicSplit|_UIStatusBarVisualProvider_DynamicSplitMedium|NONE) ;;
  *) echo "bad class $CLASS"; exit 1;;
esac
echo "CLASS $CLASS"
[ "$(cat /sys/block/vda/ro)" = 0 ]
[ "$(cat /sys/block/vda/size)" = 41943040 ]

check() {  # 除了 orphaned open-unlinked 以外的 fsck 問題一律失敗
  fsck.hfsplus -fn /dev/vda > "/tmp/fsck-$1.txt" 2>&1 || true
  cat "/tmp/fsck-$1.txt"
  if grep -q "appears to be OK" "/tmp/fsck-$1.txt"; then echo "FSCK_$1 OK"; return 0; fi
  bad=$(grep -E '^[[:space:]]+[^[:space:]]' "/tmp/fsck-$1.txt" | grep -vE 'Executing fsck_hfs|The volume name is|Orphaned open unlinked file' || true)
  if [ -n "$bad" ]; then echo "FSCK_$1 NOT_CLEAN"; return 1; fi
  echo "FSCK_$1 OK_APART_FROM_ORPHANS $(grep -c 'Orphaned open unlinked' "/tmp/fsck-$1.txt")"
}

echo JOURNAL_BEFORE
python3 "$P" /dev/vda
python3 "$P" /dev/vda --apply > /tmp/replay.txt
cat /tmp/replay.txt
grep -qxE 'JOURNAL_REPLAYED|JOURNAL_EMPTY' /tmp/replay.txt
python3 "$P" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check before
python3 "$P" /dev/vda --mark-unmounted
mkdir -p /dst
mount -t hfsplus -o force,rw /dev/vda /dst
grep -q ' /dst hfsplus rw' /proc/mounts
cat > /tmp/edit.py <<'PY'
import os, plistlib, sys
cls = sys.argv[1]
KEY = 'UIStatusBarVisualProviderClassName'
pref = '/dst/private/var/mobile/Library/Preferences/'
assert os.path.isdir(pref), pref
def write(path, d):
    tmp = path + '.fuxitmp'
    with open(tmp, 'wb') as f:
        plistlib.dump(d, f, fmt=plistlib.FMT_BINARY)
    os.chown(tmp, 501, 501)
    os.chmod(tmp, 0o600)
    os.rename(tmp, path)
# com.apple.UIKit：新建或合併
u = pref + 'com.apple.UIKit.plist'
d = plistlib.load(open(u, 'rb')) if os.path.exists(u) else {}
if cls == 'NONE':
    d.pop(KEY, None)
    if d:
        write(u, d)
    elif os.path.exists(u):
        os.remove(u)
else:
    d[KEY] = cls
    write(u, d)
# 全域網域：只加／刪這一個鍵，其餘保留
g = pref + '.GlobalPreferences.plist'
gd = plistlib.load(open(g, 'rb'))
before = dict(gd)
if cls == 'NONE':
    gd.pop(KEY, None)
else:
    gd[KEY] = cls
assert {k: v for k, v in gd.items() if k != KEY} == {k: v for k, v in before.items() if k != KEY}
write(g, gd)
for p in (u, g):
    if os.path.exists(p):
        st = os.stat(p)
        print('PREF_AFTER', p[len('/dst'):], st.st_uid, st.st_gid, oct(st.st_mode & 0o7777), plistlib.load(open(p, 'rb')).get(KEY))
    else:
        print('PREF_AFTER', p[len('/dst'):], 'absent')
PY
python3 /tmp/edit.py "$CLASS"
sync
umount /dst
check after
python3 "$P" /dev/vda --mark-journaled
python3 "$P" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check final
trap - EXIT
echo STATUSBAR_STAGE_SUCCESS
