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
SERIAL = os.environ.get('FUXI_ANDROID_SERIAL', '')
COMMANDS = {
    'identity': 'getprop ro.product.device; getprop ro.boot.ddr_size',
    'iomem': 'cat /proc/iomem',
    'meminfo': 'cat /proc/meminfo',
    'memblock-memory': 'if [ -r /sys/kernel/debug/memblock/memory ]; then cat /sys/kernel/debug/memblock/memory; else echo MISSING_READ_ONLY_INTERFACE; fi',
    'memblock-reserved': 'if [ -r /sys/kernel/debug/memblock/reserved ]; then cat /sys/kernel/debug/memblock/reserved; else echo MISSING_READ_ONLY_INTERFACE; fi',
}


def capture(arguments):
    output = Path(arguments.output).resolve()
    if output.parent != phone.ROOT / 'work/adsp-battery' or output.exists():
        raise ValueError('Use a new directory under work/adsp-battery')
    if not re.fullmatch(r'android-memory-[a-z0-9-]+', output.name):
        raise ValueError('Use a safe android-memory capture name')
    output.mkdir()
    records = {}
    with phone.phone_locks(output.name):
        if phone.run(['adb', '-s', SERIAL, 'shell', 'getprop', 'sys.boot_completed']).strip() != b'1':
            raise RuntimeError('Android is not ready')
        for name, command in COMMANDS.items():
            contents = phone.adb(SERIAL, command)
            if not contents or len(contents) > 4 * 1024 * 1024:
                raise ValueError(f'Unexpected capture length: {name}')
            if name == 'identity' and contents.splitlines()[0] != b'fuxi':
                raise ValueError('The connected phone is not Fuxi')
            target = output / (name + '.txt')
            with target.open('xb') as stream:
                stream.write(contents)
            checksum = hashlib.sha256(contents).hexdigest()
            records[name] = {'host_path': str(target), 'bytes': len(contents),
                             'sha256': checksum, 'command': command,
                             'interface_missing': contents.strip() == b'MISSING_READ_ONLY_INTERFACE'}
            phone.say('MEMORY_READ_ONLY', name, len(contents), checksum)
    manifest = {'method': 'passive read-only Android memory ownership interfaces',
                'captured_at': datetime.now().astimezone().isoformat(),
                'serial': SERIAL, 'records': records,
                'xnu_admission_verified': False,
                'persistent_owner_clearance_verified': False}
    (output / 'memory.json').write_text(json.dumps(manifest, indent=2) + '\n',
                                      encoding='utf-8', newline='\n')
    phone.say('MEMORY_CAPTURED', len(records), output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Capture passive Android memory maps without changing kernel settings or reading physical memory.')
    parser.add_argument('--output', required=True)
    capture(parser.parse_args())
