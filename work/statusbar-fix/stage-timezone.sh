#!/bin/sh
# 000 時間（guest 端）：把 iOS root 的 /private/var/db/timezone/localtime 改指到 zone.txt 指定的時區。
# 流程與 stage-shape.sh 相同：先重播 HFS+ journal、fsck、暫時標成未掛載後 rw 掛載，改完再 fsck 並標回 journaled。
set -eu
trap 'echo TIMEZONE_STAGE_FAILED' EXIT
P=/mnt/share/hfs-journal-block-probe.py
[ "$(cat /sys/block/vda/ro)" = 0 ]
[ "$(cat /sys/block/vda/size)" = 41943040 ]
grep -qxE '[A-Za-z_]+/[A-Za-z_]+' /mnt/share/zone.txt

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
import os
from pathlib import Path, PurePosixPath

root = Path('/dst')
zone = Path('/mnt/share/zone.txt').read_text().strip()


def inside(path, depth=0):
    """Resolve an iOS absolute path inside the mounted root, following symlinks the way iOS would."""
    assert depth < 16
    current = root
    parts = PurePosixPath(path).parts[1:]
    for index, part in enumerate(parts):
        assert part not in ('.', '..')
        candidate = current / part
        if candidate.is_symlink():
            target = os.readlink(candidate)
            base = PurePosixPath('/' + str(candidate.parent.relative_to(root)))
            absolute = target if target.startswith('/') else str(base / target)
            rest = '/'.join(parts[index + 1:])
            return inside(absolute + ('/' + rest if rest else ''), depth + 1)
        current = candidate
    return current


link = root / 'private/var/db/timezone/localtime'
assert link.is_symlink()
before = os.readlink(link)
print('TIMEZONE_BEFORE', before)
prefix = '/var/db/timezone/zoneinfo/'
assert before.startswith(prefix)
data = inside(prefix + zone)
assert data.is_file() and data.read_bytes()[:4] == b'TZif', data
print('TIMEZONE_DATA', data.relative_to(root), data.stat().st_size)
after = prefix + zone
if before != after:
    information = link.lstat()
    temporary = link.with_name('localtime.fuxitmp')
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    os.symlink(after, temporary)
    os.lchown(temporary, information.st_uid, information.st_gid)
    os.replace(temporary, link)
assert os.readlink(link) == after
print('TIMEZONE_AFTER', after)
PY
sync
umount /dst
check after
python3 "$P" /dev/vda --mark-journaled
python3 "$P" /dev/vda | grep -q '^JOURNAL_EMPTY$'
check final
trap - EXIT
echo TIMEZONE_STAGE_SUCCESS
