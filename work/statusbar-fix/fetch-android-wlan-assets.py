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
NAMES = ('amss20.bin', 'amss.bin', 'bd_m3.elf', 'regdb_xiaomi.bin', 'Data20.msc', 'Data.msc')
REMOTE_DIRECTORY = '/vendor/firmware_mnt/image/kiwi'


def metadata(serial, path):
    data = phone.adb(serial, f'sha256sum {path}; stat -c %s {path}').decode('ascii').splitlines()
    if len(data) != 2:
        raise ValueError('Unexpected firmware metadata')
    checksum = data[0].split()[0]
    size = int(data[1])
    if not re.fullmatch('[a-f0-9]{64}', checksum) or not 1 <= size <= 32 * 1024 * 1024:
        raise ValueError('Invalid firmware length or hash')
    return checksum, size


def fetch(arguments):
    output = Path(arguments.output).resolve()
    if output.parent != phone.ROOT / 'work/adsp-battery' or output.exists():
        raise ValueError('Use a new directory under work/adsp-battery')
    if phone.run(['adb', '-s', arguments.serial, 'shell', 'getprop', 'sys.boot_completed']).strip() != b'1':
        raise RuntimeError('Android is not ready')
    output.mkdir()
    files = {}
    names = ('phy_ucode20.elf',) if arguments.m3_only else NAMES
    with phone.phone_locks(output.name):
        for name in names:
            remote = REMOTE_DIRECTORY + '/' + name
            checksum, size = metadata(arguments.serial, remote)
            contents = phone.adb(arguments.serial, f'cat {remote}')
            if len(contents) != size or hashlib.sha256(contents).hexdigest() != checksum:
                raise ValueError('Firmware transfer differs from phone hash')
            if metadata(arguments.serial, remote) != (checksum, size):
                raise ValueError('Firmware changed during read-only transfer')
            local = output / name
            with local.open('xb') as stream:
                stream.write(contents)
            files[name] = {'sha256': checksum, 'bytes': size, 'host_path': str(local), 'android_path': remote}
            phone.say('WLAN_ASSET_READ_ONLY', name, size, checksum)
    manifest = {
        'provenance': {'method': 'read-only Android file transfer with before/after phone hashes',
                       'captured_at': datetime.now().astimezone().isoformat(),
                       'selection_evidence': str(phone.ROOT / 'work/adsp-battery/android-radio-survey-20261116-1447/capability.txt')},
        'root_staging_verified': False, 'files': files,
    }
    (output / 'assets.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    phone.say('WLAN_ASSETS_FETCHED', len(files), output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--serial', default=os.environ.get('FUXI_ANDROID_SERIAL', ''))
    parser.add_argument('--m3-only', action='store_true')
    fetch(parser.parse_args())
