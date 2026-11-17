"""組 KSU 模組 fuxi_ios_boot：把 b 槽分流器的雜湊、TWRP 的雜湊、手機現在的 FIEMAP（須等於分流器內建的 root extents）放進模組並打包。

用法：python build-module.py <分流器目錄名，例 chain-v1>    （手機要在 Android、adb 可用、iOS 映像未對應）
分流器目錄在 D:\\xiaomi13\\fuxi_ios\\work\\boot-chain\\ 下（build-chain.py 產生，內含 boot.img、sha256.txt）。
輸出：D:\\xiaomi13\\fuxi_ios\\work\\ksu-ios-entry\\fuxi_ios_boot-<分流器>.zip
"""
import os
import hashlib
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

here = Path(__file__).resolve().parent
mod = here / 'fuxi_ios_boot'
root = Path(r'D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109')
helpers = Path(r'D:\xiaomi13\fuxi_ios\work\xiaomi13-ios-gpu-20261108')
sys.path.insert(0, str(root / 'kernel-source-979' / 'tools'))
import adt

serial = os.environ.get('FUXI_ANDROID_SERIAL', '')
img = '/data/gsi/codexnative1108b/codexnative_root_1108b.img.0000'
name = sys.argv[1]
loader = Path(r'D:\xiaomi13\fuxi_ios\work\boot-chain') / name
boot = (loader / 'boot.img').read_bytes()
pinned = dict(line.split()[::-1] for line in (loader / 'sha256.txt').read_text().splitlines())
assert hashlib.sha256(boot).hexdigest() == pinned['boot.img']
# recovery_b 必須是 TWRP（2026-11-07 備份），否則從 b 槽回不來
TWRP_SHA = '7d589d3c09553328530bd2c19ba87c0a27a2c77621486ad57efa3f1898a64ac1'

# 分流器內建的 root extents（4 KiB 為單位的 logical, physical, length 三元組）；payload 取自分流器 build.txt 記的 loader
# （chain-v1＝native-auto-cool-loader，chain-v2＝native-dly1-user-loader）
payload_name = next(l.split()[-1] for l in (loader / 'build.txt').read_text().splitlines() if l.startswith('payload from '))
payload = (root / payload_name / 'payload.bin').read_bytes()
assert hashlib.sha256(payload).hexdigest() == pinned['payload.bin'] and payload in boot
offset, size = struct.unpack_from('<2Q', payload, 32)
tree, end = adt.parse(payload[offset:offset + size])
chosen = next(node for node in tree.children if node.name == 'chosen')
raw = chosen.prop('fuxi-root-extents')
want = [tuple(struct.unpack_from('<3Q', raw, i)) for i in range(0, len(raw), 24)]

# 手機現在的 FIEMAP（用模組要帶的同一支工具）
def sh(cmd):
    # adb shell 會把參數接成一行字串，整段指令要包在 su -c 的引號裡
    return subprocess.run(['adb', '-s', serial, 'shell', f"su -c '{cmd}'"], check=True, capture_output=True, text=True).stdout

subprocess.run(['adb', '-s', serial, 'push', str(helpers / 'inspect-fiemap'), '/data/local/tmp/fuxi-inspect-fiemap'], check=True, capture_output=True)
out = sh('chmod 755 /data/local/tmp/fuxi-inspect-fiemap && /data/local/tmp/fuxi-inspect-fiemap ' + img).replace('\r\n', '\n').rstrip('\n')
lines = out.split('\n')
have = [tuple(int(x) // 4096 for x in line.split()[:3]) for line in lines[1:-1]]
assert lines[0].startswith('size=21474836480 ') and 'flags=0x800000' in lines[0], lines[0]
assert have == want, 'phone FIEMAP differs from the loader ADT root extents'

(mod / 'expected-fiemap.txt').write_text(out + '\n', newline='\n')
(mod / 'loader.sha256').write_text(pinned['boot.img'] + '\n', newline='\n')
(mod / 'loader.size').write_text(f'{len(boot)}\n', newline='\n')
(mod / 'twrp.sha256').write_text(TWRP_SHA + '\n', newline='\n')
for src, dst in ((helpers / 'inspect-fiemap', 'inspect-fiemap'), (helpers / 'check-pin-readonly', 'check-pin')):
    (mod / 'bin' / dst).write_bytes(src.read_bytes())

zpath = here / f'fuxi_ios_boot-{name}.zip'
with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(mod.rglob('*')):
        if f.is_file():
            data = f.read_bytes()
            if f.suffix in ('.sh', '.prop', '.txt', '.sha256', '.size') or f.name in ('loader.sha256', 'loader.size'):
                data = data.replace(b'\r\n', b'\n')
            info = zipfile.ZipInfo(f.relative_to(mod).as_posix())
            info.external_attr = (0o755 if f.parent.name == 'bin' or f.suffix == '.sh' else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
print('extents', len(want), 'match the loader ADT')
print('loader', name, pinned['boot.img'], len(boot))
print('module', zpath)
