import os
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re


DIRECTORY = Path(__file__).resolve().parent
specification = importlib.util.spec_from_file_location('android_wlan_file_export', DIRECTORY / 'fetch-android-wlan-assets.py')
exports = importlib.util.module_from_spec(specification)
specification.loader.exec_module(exports)
phone = exports.phone
MODULE_ROOTS = ('/vendor_dlkm/lib/modules', '/vendor/lib/modules', '/odm/lib/modules')
MODULE_NAME = re.compile(r'(?:cnss[a-z0-9_-]*|wlan|kiwi[a-z0-9_-]*)\.ko')


def fetch(arguments):
    output = Path(arguments.output).resolve()
    if output.parent != phone.ROOT / 'work/adsp-battery' or output.exists():
        raise ValueError('Use a new directory under work/adsp-battery')
    if not re.fullmatch(r'android-wlan-modules-[a-z0-9-]+', output.name):
        raise ValueError('Use a bounded WLAN module capture name')
    output.mkdir()
    files = {}
    with phone.phone_locks(output.name):
        if phone.run(['adb', '-s', arguments.serial, 'shell', 'getprop', 'sys.boot_completed']).strip() != b'1':
            raise RuntimeError('Android is not ready')
        identity = phone.adb(arguments.serial, 'uname -r; cat /proc/modules')
        if not identity or len(identity) > 1024 * 1024:
            raise ValueError('Unexpected kernel module identity report')
        (output / 'kernel-modules.txt').write_bytes(identity)
        listing = phone.adb(arguments.serial, 'find ' + ' '.join(MODULE_ROOTS) + ' -type f -name "*.ko" 2>/dev/null; true')
        if len(listing) > 1024 * 1024:
            raise ValueError('Module listing exceeds the capture bound')
        paths = set()
        for line in listing.decode('ascii').splitlines():
            if any(line.startswith(root + '/') for root in MODULE_ROOTS) and MODULE_NAME.fullmatch(line.rsplit('/', 1)[-1]):
                if not re.fullmatch(r'/[A-Za-z0-9_./-]+', line) or '..' in line.split('/'):
                    raise ValueError('Unsafe module path')
                paths.add(line)
        if len(paths) > 16:
            raise ValueError('Too many matching WLAN modules')
        for index, remote in enumerate(sorted(paths)):
            checksum, size = exports.metadata(arguments.serial, remote)
            contents = phone.adb(arguments.serial, f'cat {remote}')
            if len(contents) != size or hashlib.sha256(contents).hexdigest() != checksum:
                raise ValueError('Module transfer differs from the phone file')
            if exports.metadata(arguments.serial, remote) != (checksum, size):
                raise ValueError('Module file changed during the read-only transfer')
            name = f'{index:02d}-' + remote.rsplit('/', 1)[-1]
            local = output / name
            with local.open('xb') as stream:
                stream.write(contents)
            files[name] = {'sha256': checksum, 'bytes': size, 'host_path': str(local), 'android_path': remote}
            phone.say('WLAN_MODULE_READ_ONLY', name, size, checksum)
    report = {'captured_at': datetime.now().astimezone().isoformat(),
              'method': 'ordinary Android module files with before/after hashes',
              'kernel_modules_sha256': hashlib.sha256(identity).hexdigest(),
              'loaded_module_buffer_identity_verified': False, 'files': files,
              'missing_module_files': not bool(files), 'root_staging_verified': False}
    (output / 'modules.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    phone.say('WLAN_MODULES_CAPTURED', len(files), output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--serial', default=os.environ.get('FUXI_ANDROID_SERIAL', ''))
    fetch(parser.parse_args())
