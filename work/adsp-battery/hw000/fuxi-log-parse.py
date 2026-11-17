#!/usr/bin/env python3
# 解析 logdump 分區前 2049 個 4 KiB 區塊（核心 fx_log：獨立開機時把 console 寫進 logdump）。
#   區塊 0：SWEETLOG 標頭（version 2）＋ byte 2048 的 "FUXILOG1 STAMPED"
#   區塊 1..1024：ring（console 最後 4 MiB，第 n 個位元組在 n % 4 MiB）
#   區塊 1025..2048：head（console 開頭 4 MiB，ring 繞圈後就不再寫）
# 用法：fuxi-log-parse.py <area.bin> <out.txt>
import struct
import sys

B = 4096
STAMP = b'FUXILOG1 STAMPED'


def main():
    src, out = sys.argv[1], sys.argv[2]
    d = open(src, 'rb').read()
    if len(d) < B * 2049:
        sys.exit('area too short: %d bytes' % len(d))
    h = d[:B]
    if h[2048:2064] != STAMP:
        sys.exit('no stamp: logdump was rewritten by Android or never stamped')
    if h[:8] != b'SWEETLOG':
        print('stamped, no iOS boot has written a log yet')
        return
    _, ver, size, total, seq, head, boot, secs = struct.unpack_from('<8sIIQQQII', h, 0)
    if ver != 2 or size != 4 << 20:
        sys.exit('unexpected header version %d size %d' % (ver, size))
    ring = d[B:B + size]
    head_area = d[B + size:B + 2 * size]
    print('boot #%d, flush #%d every %d s, %d console bytes, head %d bytes' % (boot, seq, secs, total, head))
    if total <= size:
        text = ring[:total]
    else:
        start = max(total - size, head)
        off = start % size
        tail = (ring + ring)[off:off + (total - start)]
        lost = start - head
        text = head_area[:head] + (b'\n[fuxi-log: %d bytes between head and ring lost]\n' % lost if lost else b'') + tail
    with open(out, 'wb') as f:
        f.write(text)
    print('wrote %s (%d bytes)' % (out, len(text)))


if __name__ == '__main__':
    main()
