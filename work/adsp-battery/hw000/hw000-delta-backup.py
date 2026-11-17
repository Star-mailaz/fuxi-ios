"""000 線（硬體適配）上機前的還原點：把手機 iOS root 現況「只讀」拉回，存成相對固定基底的差異備份。

用法：python -I hw000-delta-backup.py --backup-base <fuxi_Backup 裡不會再變的 raw> --backup-base-sha <sha256>
          --name <手機暫存檔名稱> --keep-delta <新的備份目錄>

和 001 線的 delta-pull-inplace.py 的差別：那支會就地改寫 --target（上一版部署的映像，001 下一輪要用），
這支不碰任何主機映像，只寫新的備份目錄，所以不會和 001 衝突，也不多佔 20 GiB。
還原方式：base 再把 diff-blocks.txt 列的 4 MiB 區塊依序換成 pull.bin 即得整份（README.txt 有整份 sha256）。
前提：mapper 已 map 且已通過 verify-native-map.py；本腳本只讀 mapper，絕不寫入手機的 iOS root。
驗證：每個拉回的區塊都要等於手機回報的雜湊；最後以「基底＋pull.bin」重組整份，逐塊比對手機雜湊並算整份 sha256。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'statusbar-fix'))
from root_layers import SnapshotReader, digest_file, load_layers

SIZE = 21474836480
BLOCK = 4194304
COUNT = SIZE // BLOCK

ap = argparse.ArgumentParser()
ap.add_argument('--backup-base', type=Path, required=True)
ap.add_argument('--backup-base-sha', required=True)
ap.add_argument('--name', required=True)
ap.add_argument('--keep-delta', type=Path, required=True)
ap.add_argument('--serial', default=os.environ.get('FUXI_ANDROID_SERIAL', ''))
ap.add_argument('--mapper', default='/dev/block/mapper/codexnative_root_1108b')
ap.add_argument('--parent-snapshot', type=Path)
ap.add_argument('--ntfs-compress', action='store_true')
ap.add_argument('--resume-download', action='store_true')
a = ap.parse_args()
assert re.fullmatch(r'[a-z0-9-]{3,40}', a.name)
assert re.fullmatch(r'[0-9a-f]{64}', a.backup_base_sha)
assert a.backup_base.stat().st_size == SIZE
if a.resume_download:
    assert a.keep_delta.is_dir() and (a.keep_delta / 'phone-blocks.txt').is_file()
    assert not (a.keep_delta / 'diff-blocks.txt').exists()
    assert not (a.keep_delta / 'README.txt').exists()
else:
    assert not a.keep_delta.exists()
HASHER = f'/data/local/tmp/codex-{a.name}-blockhash.sh'
PACKER = f'/data/local/tmp/codex-{a.name}-pack.sh'
DELTA = f'/data/local/tmp/codex-{a.name}-pull.bin'


def say(*x):
    print(*x, flush=True)


def adb(*args, timeout=60):
    return subprocess.run(['adb', '-s', a.serial, *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout,
                          check=True).stdout.strip()


def su(cmd, timeout=60):
    assert "'" not in cmd
    return adb('shell', "su -c '" + cmd + "'", timeout=timeout)


def push_script(text, remote):
    local = a.keep_delta / ('.' + Path(remote).name)
    local.write_bytes(text.encode())
    subprocess.run(['adb', '-s', a.serial, 'push', str(local), remote], check=True, capture_output=True, timeout=120)
    assert su('sha256sum ' + remote).split()[0] == hashlib.sha256(text.encode()).hexdigest()
    local.unlink()


# 1. 手機檢查（只讀）
assert adb('get-state') == 'device' and adb('shell', 'getprop', 'sys.boot_completed') == '1' and su('id -u') == '0'
device = su('readlink -f ' + a.mapper)
assert re.fullmatch(r'/dev/block/dm-\d+', device), device
assert su('blockdev --getsize64 ' + a.mapper) == str(SIZE)
assert su(f'grep -c "^{device} " /proc/mounts; true').split()[0] == '0'
for path in (HASHER, PACKER, DELTA):
    if a.resume_download:
        assert su(f'test -f {path} && echo present') == 'present', path
    else:
        assert su(f'test ! -e {path} && echo absent') == 'absent', path
say('PHONE_OK', device)
if not a.resume_download:
    a.keep_delta.mkdir(parents=True)
if a.ntfs_compress:
    assert os.name == 'nt', 'NTFS compression requires Windows'
    subprocess.run(['compact.exe', '/C', '/I', '/Q', str(a.keep_delta)], check=True, capture_output=True)
    import ctypes
    attributes = ctypes.windll.kernel32.GetFileAttributesW(str(a.keep_delta.resolve()))
    assert attributes != 0xffffffff and attributes & 0x800, 'Backup directory is not NTFS compressed'
    say('NTFS_COMPRESSED_DIRECTORY', a.keep_delta)

# 2. 手機回報每個區塊的雜湊
push_script(f'#!/system/bin/sh\nset -u\ni=0\nwhile [ $i -lt {COUNT} ]; do\n'
            f' dd if={a.mapper} bs={BLOCK} skip=$i count=1 2>/dev/null | sha256sum\n i=$((i+1))\ndone\necho HASH_DONE\n', HASHER)
lines = su('sh ' + HASHER, timeout=1800).splitlines()
assert len(lines) == COUNT + 1 and lines[-1] == 'HASH_DONE', len(lines)
phone = [line.split()[0] for line in lines[:-1]]
assert all(re.fullmatch(r'[0-9a-f]{64}', x) for x in phone)
manifest = a.keep_delta / 'phone-blocks.txt'
if a.resume_download:
    assert manifest.read_text(encoding='utf-8').split() == phone, 'phone changed since interrupted backup'
else:
    manifest.write_text('\n'.join(phone) + '\n', encoding='utf-8')
say('PHONE_HASHES', len(phone))

# 3. 基底逐區塊雜湊（同時驗基底整份 sha），找出差異
whole, base = hashlib.sha256(), []
with a.backup_base.open('rb') as f:
    for _ in range(COUNT):
        block = f.read(BLOCK)
        assert len(block) == BLOCK
        whole.update(block)
        base.append(hashlib.sha256(block).hexdigest())
assert whole.hexdigest() == a.backup_base_sha, 'backup base sha mismatch'
parent_layers = []
if a.parent_snapshot:
    parent_layers = load_layers(a.parent_snapshot)
    base = parent_layers[-1]['hashes']
    parent = {
        'snapshot': str(a.parent_snapshot.resolve()),
        'phone_manifest_sha256': digest_file(a.parent_snapshot / 'phone-blocks.txt'),
    }
    parent_path = a.keep_delta / 'parent.json'
    if a.resume_download:
        assert json.loads(parent_path.read_text(encoding='utf-8')) == parent, 'backup parent changed'
    else:
        parent_path.write_text(json.dumps(parent, indent=2) + '\n', encoding='utf-8')
else:
    assert not (a.keep_delta / 'parent.json').exists()
diff = [i for i in range(COUNT) if base[i] != phone[i]]
assert 0 <= len(diff) <= 2000, f'{len(diff)} differing blocks'
say('DIFF', len(diff), 'blocks', len(diff) * BLOCK // 1024**2, 'MiB')

# 4. 手機把差異區塊依序打包（只讀 mapper），拉回主機直接當 pull.bin，逐塊驗證
packer_text = ('#!/system/bin/sh\nset -eu\n: > ' + DELTA + '\n' +
               ''.join(f'dd if={a.mapper} bs={BLOCK} skip={index} count=1 2>/dev/null >> {DELTA}\n'
                       for index in diff) + 'sync\necho PACK_DONE\n')
if a.resume_download:
    assert su('sha256sum ' + PACKER).split()[0] == hashlib.sha256(packer_text.encode()).hexdigest()
else:
    push_script(packer_text, PACKER)
    assert su('sh ' + PACKER, timeout=1800).splitlines()[-1] == 'PACK_DONE'
assert su('stat -c %s ' + DELTA) == str(len(diff) * BLOCK)
pull = a.keep_delta / 'pull.bin'
download = subprocess.run(['adb', '-s', a.serial, 'pull', DELTA, str(pull)],
                          capture_output=True, timeout=3600)
if download.returncode:
    say(download.stdout.decode('utf-8', errors='replace'))
    say(download.stderr.decode('utf-8', errors='replace'))
    download.check_returncode()
ph = hashlib.sha256()
with pull.open('rb') as f:
    for index in diff:
        block = f.read(BLOCK)
        assert len(block) == BLOCK and hashlib.sha256(block).hexdigest() == phone[index], f'block {index} mismatch'
        ph.update(block)
    assert f.read(1) == b''
say('PULLED_VERIFIED', len(diff))

# 5. 以基底＋pull.bin 重組整份（只在記憶體裡串流），逐塊比對手機雜湊、算整份 sha256
position = {index: n for n, index in enumerate(diff)}
whole = hashlib.sha256()
with SnapshotReader(a.backup_base, parent_layers) as snapshot, pull.open('rb') as p:
    for index in range(COUNT):
        if index in position:
            p.seek(position[index] * BLOCK)
            block = p.read(BLOCK)
        else:
            block = snapshot.block(index)
        assert hashlib.sha256(block).hexdigest() == phone[index], f'block {index} differs from the phone'
        whole.update(block)
whole_phone = whole.hexdigest()
(a.keep_delta / 'diff-blocks.txt').write_text(' '.join(map(str, diff)) + '\n', encoding='utf-8')
(a.keep_delta / 'README.txt').write_text(
    f'000 線（硬體適配）上機前還原點：手機 iOS root（{a.mapper}），hw000-delta-backup.py --name {a.name} 只讀拉回\n'
    f'= 基底 {a.backup_base}（sha256 {a.backup_base_sha}）把 diff-blocks.txt 列的 {len(diff)} 個 4 MiB 區塊\n'
    f'  依序換成 pull.bin（sha256 {ph.hexdigest()}）。\n'
    f'整份 sha256 {whole_phone}\n', encoding='utf-8')
if a.parent_snapshot:
    with (a.keep_delta / 'README.txt').open('a', encoding='utf-8') as stream:
        stream.write(f'本還原點為增量層；重建時先套父還原點 {a.parent_snapshot.resolve()}，再套本層。\n')
su(f'rm -f {DELTA} {HASHER} {PACKER}')
say('DELTA_KEPT', a.keep_delta, 'blocks', len(diff), 'sha256', whole_phone)
