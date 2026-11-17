"""Keep xnu/patches/0098-fuxi-native-adreno-abi.patch's embedded copy of bsd/dev/fuxi_gpu_abi_backend.inc
(a whole-file hunk '@@ -0,0 +1,N @@') equal to the mirror xnu/fuxi-adreno/fuxi_gpu_abi_backend.inc.
用法：python tools/sync-abi-backend.py [--check]"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
mirror = root / 'xnu' / 'fuxi-adreno' / 'fuxi_gpu_abi_backend.inc'
patch = root / 'xnu' / 'patches' / '0098-fuxi-native-adreno-abi.patch'
lines = patch.read_bytes().decode('utf-8').split('\n')
head = lines.index('+++ b/bsd/dev/fuxi_gpu_abi_backend.inc')
hunk = head + 1
assert lines[hunk].startswith('@@ -0,0 +1,') and lines[hunk].endswith(' @@')
old_n = int(lines[hunk][len('@@ -0,0 +1,'):-3])
embedded = [l[1:] for l in lines[hunk + 1:hunk + 1 + old_n]]
assert all(l.startswith('+') for l in lines[hunk + 1:hunk + 1 + old_n])
src = mirror.read_bytes().decode('utf-8')
assert src.endswith('\n') and '\r' not in src
new = src[:-1].split('\n')
if '--check' in sys.argv:
    print('in sync' if embedded == new else f'DIFFERENT (embedded {old_n} lines, mirror {len(new)})')
    sys.exit(0 if embedded == new else 1)
out = lines[:hunk] + [f'@@ -0,0 +1,{len(new)} @@'] + ['+' + l for l in new] + lines[hunk + 1 + old_n:]
patch.write_bytes('\n'.join(out).encode('utf-8'))
print(f'0098 embedded copy: {old_n} -> {len(new)} lines')
