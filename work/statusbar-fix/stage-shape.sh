#!/bin/sh
set -eu
trap 'echo STATUSBAR_STAGE_FAILED' EXIT
P=/mnt/share/hfs-journal-block-probe.py
[ "$(cat /sys/block/vda/ro)" = 0 ]
[ "$(cat /sys/block/vda/size)" = 41943040 ]
(cd /mnt/share && sha256sum -c shape-sha256.txt)

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
python3 - <<'PY'
import hashlib
import os
import plistlib
from pathlib import Path

root = Path('/dst')
source = Path('/mnt/share/libfuxi-sb.dylib')
expected = Path('/mnt/share/shape-sha256.txt').read_text().split()[0]
assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
target = root / 'usr/local/lib/fuxi/libfuxi-sb.dylib'
target.parent.mkdir(parents=True, exist_ok=True)
temporary = target.with_suffix('.fuxitmp')
temporary.write_bytes(source.read_bytes())
os.chown(temporary, 0, 0)
os.chmod(temporary, 0o755)
temporary.replace(target)
assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
print('SHAPE_INSTALLED', target, expected)

key = 'UIStatusBarVisualProviderClassName'
preferences = root / 'private/var/mobile/Library/Preferences'
assert preferences.is_dir()
for name in ('com.apple.UIKit.plist', '.GlobalPreferences.plist'):
    path = preferences / name
    if not path.exists():
        continue
    before = plistlib.loads(path.read_bytes())
    after = dict(before)
    after.pop(key, None)
    assert after == {name: value for name, value in before.items() if name != key}
    if after == before:
        continue
    if not after and path.name == 'com.apple.UIKit.plist':
        path.unlink()
    else:
        stat = path.stat()
        temporary = path.with_suffix('.fuxitmp')
        temporary.write_bytes(plistlib.dumps(after, fmt=plistlib.FMT_BINARY))
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.chmod(temporary, stat.st_mode & 0o7777)
        temporary.replace(path)
        assert plistlib.loads(path.read_bytes()) == after
    print('PROVIDER_OVERRIDE_REMOVED', path)
PY
sync
umount /dst
check after
python3 "$P" /dev/vda --mark-journaled
python3 "$P" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check final
trap - EXIT
echo STATUSBAR_STAGE_SUCCESS
