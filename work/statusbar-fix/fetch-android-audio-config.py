"""從手機 Android 端唯讀取回音訊拓撲設定（ACDB、usecaseKvManager、resourcemanager、mixer_paths、card-defs）。

復用 fetch-android-wlan-assets.py 的做法：phone-readthrough.py 的三鎖、每檔傳輸前後各算一次手機端 SHA-256、
主機收到的內容須與手機雜湊相符；只讀不寫。用途：docs-lanes/audio.md Blockers 1／5（喇叭 TDM 圖的 subgraph／
module instance id、麥克風 AMIC／micbias）。檔案只放工作區，不進 git。
"""
import os
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re

DIRECTORY = Path(__file__).resolve().parent
specification = importlib.util.spec_from_file_location('phone_readthrough', DIRECTORY / 'phone-readthrough.py')
phone = importlib.util.module_from_spec(specification)
specification.loader.exec_module(phone)
SEARCH_ROOTS = ('/vendor/etc', '/odm/etc', '/vendor/odm/etc')
PATTERN = re.compile(r'(?i)(acdb|\.qwsp$|usecasekvmanager|resourcemanager|mixer_paths|card-defs|audio_effects|'
                     r'audio_policy_configuration|kvh2xml|backend_conf|audio_platform_info)')
SAFE_PATH = re.compile(r'/[A-Za-z0-9_./+-]+')
LIMIT = 64 * 1024 * 1024


def metadata(serial, path):
    data = phone.adb(serial, f'sha256sum {path}; stat -c %s {path}').decode('ascii').splitlines()
    if len(data) != 2:
        raise ValueError('Unexpected file metadata')
    checksum = data[0].split()[0]
    size = int(data[1])
    if not re.fullmatch('[a-f0-9]{64}', checksum) or not 1 <= size <= LIMIT:
        raise ValueError(f'Invalid length or hash: {path}')
    return checksum, size


def discover(serial):
    found = []
    for root in SEARCH_ROOTS:
        listing = phone.adb(serial, f'find {root} -type f 2>/dev/null').decode('utf-8', 'replace').splitlines()
        for path in listing:
            path = path.strip()
            if PATTERN.search(path.rsplit('/', 1)[-1]) and SAFE_PATH.fullmatch(path) and path not in found:
                found.append(path)
    return sorted(found)


def fetch(arguments):
    output = Path(arguments.output).resolve()
    if output.parent != phone.ROOT / 'work/adsp-battery' or output.exists():
        raise ValueError('Use a new directory under work/adsp-battery')
    if phone.run(['adb', '-s', arguments.serial, 'shell', 'getprop', 'sys.boot_completed']).strip() != b'1':
        raise RuntimeError('Android is not ready')
    output.mkdir()
    files = {}
    with phone.phone_locks(output.name):
        paths = discover(arguments.serial)
        phone.say('AUDIO_CONFIG_FOUND', len(paths))
        if not 1 <= len(paths) <= 200:
            raise ValueError(f'Unexpected number of audio config files: {len(paths)}')
        for remote in paths:
            checksum, size = metadata(arguments.serial, remote)
            contents = phone.adb(arguments.serial, f'cat {remote}')
            if len(contents) != size or hashlib.sha256(contents).hexdigest() != checksum:
                raise ValueError('Transfer differs from phone hash: ' + remote)
            if metadata(arguments.serial, remote) != (checksum, size):
                raise ValueError('File changed during read-only transfer: ' + remote)
            local = output / remote.lstrip('/')
            local.parent.mkdir(parents=True, exist_ok=True)
            with local.open('xb') as stream:
                stream.write(contents)
            files[remote] = {'sha256': checksum, 'bytes': size, 'host_path': str(local)}
            phone.say('AUDIO_CONFIG_READ_ONLY', remote, size, checksum[:16])
    manifest = {
        'provenance': {'method': 'read-only Android file transfer with before/after phone hashes',
                       'captured_at': datetime.now().astimezone().isoformat(),
                       'search_roots': SEARCH_ROOTS, 'pattern': PATTERN.pattern},
        'files': files,
    }
    (output / 'audio-config.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    phone.say('AUDIO_CONFIG_FETCHED', len(files), output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--serial', default=os.environ.get('FUXI_ANDROID_SERIAL', ''))
    fetch(parser.parse_args())
