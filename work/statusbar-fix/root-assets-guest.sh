#!/bin/sh
set -eu
mkdir -p /dst
echo ROOT_ASSETS_MOUNT_BEGIN
mount -t hfsplus -o ro /dev/vda /dst
echo ROOT_ASSETS_MOUNT_OK
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import urllib.request

root = Path('/dst')
transfer = json.loads(Path('/mnt/share/transfer.json').read_text())
mounts = Path('/proc/mounts').read_text().splitlines()
mount = next(line.split() for line in mounts if line.split()[1] == '/dst')
assert 'ro' in mount[3].split(',') and 'rw' not in mount[3].split(',')
version = root / 'System/Library/CoreServices/SystemVersion.plist'
if version.is_file():
    print('ROOT_VERSION', json.dumps(plistlib.loads(version.read_bytes()), ensure_ascii=True))
paths = []
wlan = root / 'usr/local/share/fuxi/wlan'
print('ROOT_DIRECTORY', json.dumps({'path': '/usr/local/share/fuxi/wlan', 'exists': wlan.is_dir()}))
if wlan.is_dir():
    paths.extend(sorted(path for path in wlan.rglob('*') if path.is_file()))
for name in ('usr/sbin/BlueTool', 'usr/sbin/bluetoothd'):
    path = root / name
    if path.is_file():
        paths.append(path)
    else:
        print('ROOT_MISSING', json.dumps({'path': '/' + name}))
assert len(paths) <= 256
total = 0
for path in paths:
    assert root in path.resolve().parents
    size = path.stat().st_size
    assert 0 <= size <= 32 * 1024 * 1024
    total += size
    assert total <= 96 * 1024 * 1024
    contents = path.read_bytes()
    assert len(contents) == size
    metadata = json.dumps({
        'runtime_path': '/' + path.relative_to(root).as_posix(),
        'bytes': size,
        'sha256': hashlib.sha256(contents).hexdigest(),
    }).encode('utf-8')
    request = urllib.request.Request(
        'http://10.0.2.2:' + str(transfer['port']) + '/asset',
        data=struct.pack('>I', len(metadata)) + metadata + contents,
        headers={'X-Fuxi-Token': transfer['token'], 'Content-Type': 'application/octet-stream'},
        method='POST')
    with urllib.request.urlopen(request, timeout=90) as response:
        assert response.status == 200 and response.read() == b'OK'
    print('ROOT_FILE_SENT', '/' + path.relative_to(root).as_posix(), size, flush=True)
print('ROOT_FILE_COUNT', len(paths))
PY
umount /dst
echo ROOT_ASSETS_INSPECT_SUCCESS
