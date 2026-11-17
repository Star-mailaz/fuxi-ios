"""000 狀態欄（主機端）：從客體 log 讀出改動的區塊，用 qemu-img dd 由疊加層取出，做成寫入／還原兩組資料。

用法：python -I sb-extract.py <guest.log> <overlay.qcow2> <還原點目錄> <底檔 raw> <輸出目錄>
  還原點目錄＝hw000-delta-backup.py 的 --keep-delta（有 phone-blocks.txt、diff-blocks.txt、pull.bin）
輸出：<輸出目錄>/sb-new.bin＋sb-list.txt（區塊號 寫前 寫後）
      <還原點目錄>/statusbar-undo.bin＋statusbar-undo-list.txt（寫前寫後對調，用 sb-blocks-write.sh 可直接還原）
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from root_layers import SnapshotReader, load_layers

B = 4194304
QIMG = r'D:\xiaomi13\fuxi_ios\candidates\vm-tools\qemu\qemu-img.exe'
log, overlay, rp, base, out = map(Path, sys.argv[1:6])
text = log.read_text(encoding='utf-8', errors='replace')
assert 'SB_GUEST_SUCCESS' in text and 'GUEST_OK' in text
changed = [(int(i), h) for i, h in re.findall(r'^CHANGED (\d+) ([0-9a-f]{64})\s*$', text, re.M)]
assert 1 <= len(changed) <= 64, changed
new_whole = re.search(r'^NEW_WHOLE ([0-9a-f]{64})\s*$', text, re.M).group(1)
phone = (rp / 'phone-blocks.txt').read_text().split()
diff = list(map(int, (rp / 'diff-blocks.txt').read_text().split()))
assert len(phone) == 5120
pos = {idx: n for n, idx in enumerate(diff)}
layers = load_layers(rp)
out.mkdir(parents=True, exist_ok=True)


def pre_block(idx):
    """手機現況的區塊：差異區塊在 pull.bin，其餘等於底檔。"""
    with SnapshotReader(base, layers) as snapshot:
        blk = snapshot.block(idx)
    assert len(blk) == B and hashlib.sha256(blk).hexdigest() == phone[idx], f'pre block {idx}'
    return blk


new_lines, undo_lines = [], []
with (out / 'sb-new.bin').open('wb') as nf, (rp / 'statusbar-undo.bin').open('wb') as uf:
    for idx, h in changed:
        tmp = out / f'blk-{idx}.bin'
        tmp.unlink(missing_ok=True)
        # 這版 qemu-img dd 的 count 是「讀到第幾塊為止」（含 skip），count=1 配 skip>0 會得到空檔
        subprocess.run([QIMG, 'dd', '-f', 'qcow2', '-O', 'raw', f'bs={B}', f'skip={idx}', f'count={idx + 1}',
                        f'if={overlay}', f'of={tmp}'], check=True, capture_output=True, timeout=300)
        blk = tmp.read_bytes()
        assert len(blk) == B and hashlib.sha256(blk).hexdigest() == h, f'extracted block {idx}'
        tmp.unlink()
        nf.write(blk)
        uf.write(pre_block(idx))
        new_lines.append(f'{idx} {phone[idx]} {h}')
        undo_lines.append(f'{idx} {h} {phone[idx]}')
(out / 'sb-list.txt').write_text('\n'.join(new_lines) + '\n', newline='\n')
(rp / 'statusbar-undo-list.txt').write_text('\n'.join(undo_lines) + '\n', newline='\n')
with (rp / 'README.txt').open('a', encoding='utf-8') as f:
    f.write(f'狀態欄改動（UIStatusBarVisualProviderClassName）寫入 {len(changed)} 個區塊後整份 sha256 {new_whole}\n'
            f'還原狀態欄：adb push statusbar-undo-list.txt、statusbar-undo.bin 與 work\\statusbar-fix\\sb-blocks-write.sh，\n'
            f'  mapper 已 map 時 su -c "sh sb-blocks-write.sh <list> <bin>"（寫前比對改後雜湊，寫後回到拉回時的整份 sha256）。\n')
print('EXTRACTED', len(changed), 'blocks', [c[0] for c in changed], 'new_whole', new_whole)
