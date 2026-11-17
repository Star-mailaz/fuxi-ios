"""Check any loader against the freshly verified phone mapping, independent of how it was built (args, kernel or ADT variant).

用法：python verify-loader-safety.py <loader 目錄名>
只驗會傷到手機資料的部分：payload／boot.img 與 sha256.txt 相符、payload 內的核心就是 source.txt 第二行 artifact 的核心、
ADT /chosen 的 fuxi-root-extents 等於 verify-native-map.py 剛寫出的手機現況（rootrw=1 ufsrw=1 時寫入落在這些區塊）、
fuxi-root-blocks 為 20 GiB、boot.img 內恰好一份 payload。來源鏈的逐 token 比對由各 prepare 工具在建置時做過。
"""
import os
import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
from pathlib import Path

base = Path(r'D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109')
sys.path.insert(0, str(base / 'kernel-source-979' / 'tools'))
import adt
import mkpayload

sha = lambda b: hashlib.sha256(b).hexdigest()
out = base / sys.argv[1]
src_name, art_name = (out / 'source.txt').read_text().split()[:2]
item = json.loads(Path(r'D:\xiaomi13\fuxi_ios\work\xiaomi13-ios-gpu-20261108\managed-native-map-current.json').read_text())['items'][0]
words = [n // 4096 for logical, physical, length, _ in item['extents'] for n in (logical, physical, length)]
expected = struct.pack('<%dQ' % len(words), *words)
pinned = dict(line.split()[::-1] for line in (out / 'sha256.txt').read_text().splitlines())
payload = (out / 'payload.bin').read_bytes()
loader = (out / 'boot.img').read_bytes()
assert sha(payload) == pinned['payload.bin'] and sha(loader) == pinned['boot.img']
kernel = (base / art_name / 'kernel.development.fuxi').read_bytes()
assert sha(kernel) == pinned['kernel.development.fuxi']
sums = {}
for line in (base / art_name / 'SHA256SUMS').read_text().splitlines():
    digest, fname = line.split(None, 1)
    sums[fname.strip().lstrip('*')] = digest
assert sums['kernel.development.fuxi'] == pinned['kernel.development.fuxi']
assert payload[:8] == b'SWEETXNU'
offset, size = struct.unpack_from('<2Q', payload, 32)
root, end = adt.parse(payload[offset:offset + size])
assert end == size
chosen = next(node for node in root.children if node.name == 'chosen')
physical_sku = chosen.prop('fuxi,ram-sku')
if physical_sku is not None and physical_sku != struct.pack('<I', 12):
    raise AssertionError('loader needs the measured 12GB physical RAM profile')
live_sku = subprocess.check_output(['adb', '-s', os.environ.get('FUXI_ANDROID_SERIAL', ''), 'exec-out',
                                   'su -c "cat /sys/firmware/devicetree/base/memory/ddr_size"'], timeout=30)
if live_sku != struct.pack('>I', 12):
    raise AssertionError('connected device is not the measured 12GB SKU; 8GB requires a separate profile')
physical_base, memory_size = struct.unpack_from('<2Q', payload, 56)
assert physical_base == 0x8c0000000 and memory_size in (0x30000000, 0x40000000, 0x13e000000, 0x23e000000)
assert chosen.prop('dram-base') == struct.pack('<Q', physical_base)
assert chosen.prop('dram-size') == struct.pack('<Q', memory_size)
scratch = 0xafe000000 if memory_size == 0x23e000000 else 0x9fe000000
assert chosen.prop('fuxi-gpu-memory') == struct.pack('<2Q', scratch, 0x2000000)
assert physical_base + memory_size <= scratch
if memory_size == 0x23e000000:
    layout = json.loads((out / 'memory-layout.json').read_text())
    assert layout['layout'] == '9g' and layout['usable'] == memory_size and layout['scratch'] == scratch
    artifact_tree = (base / art_name / 'fuxi.adt').read_bytes()
    artifact_root, _ = adt.parse(artifact_tree)
    artifact_chosen = next(node for node in artifact_root.children if node.name == 'chosen')
    assert artifact_chosen.prop('fuxi-gpu-memory') == chosen.prop('fuxi-gpu-memory')
assert chosen.prop('fuxi-root-extents') == expected, 'ADT root extents differ from the phone mapping'
assert chosen.prop('fuxi-root-blocks') == struct.pack('<Q', 21474836480 // 4096)
# 核心的 Mach-O 內容逐段出現在 payload 中（mkpayload 只搬移區段，不改內容）
m = mkpayload.parse_macho(kernel)
assert m['cputype'] == 0x0100000c
assert loader.count(payload) == 1
args = payload[72:680].split(b'\0', 1)[0].decode('ascii')
rtc_tokens = [argument for argument in args.split() if argument.startswith(('fuxirtc=', 'fuxirtcoffset='))]
if rtc_tokens:
    rtc_spec = importlib.util.spec_from_file_location('rtc_calibration',
        base.parent / 'adsp-battery/rtc-calibration.py')
    rtc_module = importlib.util.module_from_spec(rtc_spec)
    rtc_spec.loader.exec_module(rtc_module)
    rtc_path = out / 'rtc-calibration.json'
    rtc_record = rtc_module.load(rtc_path)
    if rtc_tokens != [f'fuxirtcoffset={rtc_record["offset_seconds"]}']:
        raise ValueError('Loader RTC override differs from the measured calibration')
    if json.loads((out / 'memory-layout.json').read_text())['rtc_calibration_sha256'] != sha(rtc_path.read_bytes()):
        raise ValueError('Loader RTC calibration hash differs')
    rtc_module.verify_live(rtc_record)
    print('RTC calibration and the connected device counter are consistent; temporary boot only')
props = {n: v for n, _, v in chosen.props if n.startswith('fuxi,')}
print('OK:', sys.argv[1], 'contains the verified mapping (', len(words) // 3, 'extents ); kernel from', art_name)
print('physical RAM SKU 12GB confirmed from the connected device; usable layout is checked separately')
print('args', len(args), args)
print('chosen fuxi props', {n: (struct.unpack('<I', v)[0] if len(v) == 4 else v.hex()) for n, v in props.items()})
print('kernel', pinned['kernel.development.fuxi'])
print('payload', pinned['payload.bin'])
print('boot.img', pinned['boot.img'])
