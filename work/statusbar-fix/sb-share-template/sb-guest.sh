#!/bin/sh
# 000 狀態欄（客體端）：vda = qcow2 疊加層（底檔 native-layout0043-root.img 只讀），vdb = 唯讀分享。
#   1. 把手機拉回的差異區塊（pull.bin＋diff-blocks.txt）寫進疊加層，整份逐塊比對 phone-blocks.txt＝手機現況
#   2. 跑 stage-statusbar.sh（只加 UIStatusBarVisualProviderClassName 一個鍵）
#   3. 再逐塊算雜湊，印出和手機現況不同的區塊（CHANGED <區塊號> <sha256>），主機端照這份清單取出、寫回手機
set -eu
trap 'echo SB_GUEST_FAILED' EXIT
S=/mnt/share
B=4194304
[ "$(cat /sys/block/vda/ro)" = 0 ]
[ "$(cat /sys/block/vda/size)" = 41943040 ]
if [ -f "$S/restore-preloaded.txt" ]; then
  echo SNAPSHOT_BACKING_READY
else
# vdc＝pull.bin（唯讀 raw 磁碟），大小必須剛好是差異區塊數 × 4 MiB
[ "$(cat /sys/block/vdc/ro)" = 1 ]
nd=$(wc -w < $S/diff-blocks.txt)
[ "$(cat /sys/block/vdc/size)" = $((nd * 8192)) ]
n=0
# diff-blocks.txt 是 Windows 上的 Python 寫的，結尾是 CRLF；先去掉 CR，否則最後一個數字 dd 會判成無效
for i in $(tr -d '\r' < $S/diff-blocks.txt); do
  case "$i" in *[!0-9]*|'') echo "BAD_INDEX $i"; exit 1 ;; esac
  dd if=/dev/vdc of=/dev/vda bs=$B skip=$n seek=$i count=1 conv=notrunc 2>/dev/null
  n=$((n+1))
done
sync
[ "$n" = "$nd" ]
echo "APPLIED $n"
fi
cat > /tmp/blocks.py <<'PY'
import hashlib, sys
mode = sys.argv[1]
B = 4194304
phone = open('/mnt/share/phone-blocks.txt').read().split()
assert len(phone) == 5120
whole = hashlib.sha256()
changed = []
with open('/dev/vda', 'rb', buffering=0) as f:
    for i in range(5120):
        blk = f.read(B)
        assert len(blk) == B, i
        whole.update(blk)
        h = hashlib.sha256(blk).hexdigest()
        if h != phone[i]:
            changed.append((i, h))
if mode == 'verify':
    assert not changed, 'differs from the phone at blocks %s' % [c[0] for c in changed[:20]]
    print('PHONE_STATE_VERIFIED', whole.hexdigest())
else:
    assert 1 <= len(changed) <= 64, len(changed)
    for i, h in changed:
        print('CHANGED', i, h)
    print('NEW_WHOLE', whole.hexdigest())
PY
echo 3 > /proc/sys/vm/drop_caches
python3 /tmp/blocks.py verify
sh $S/stage-statusbar.sh > /tmp/stage.txt 2>&1 || true
cat /tmp/stage.txt
grep -q '^STATUSBAR_STAGE_SUCCESS$' /tmp/stage.txt
sync
echo 3 > /proc/sys/vm/drop_caches
python3 /tmp/blocks.py changed
trap - EXIT
echo SB_GUEST_SUCCESS
