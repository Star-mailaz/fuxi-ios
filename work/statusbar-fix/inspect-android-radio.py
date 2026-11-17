import os
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
specification = importlib.util.spec_from_file_location('phone_readthrough', DIRECTORY / 'phone-readthrough.py')
phone = importlib.util.module_from_spec(specification)
specification.loader.exec_module(phone)

COMMANDS = {
    'identity': 'getprop ro.product.device; getprop ro.build.fingerprint; getprop ro.boot.hardware.sku; '
                'getprop ro.boot.hardware; uname -a',
    'firmware': 'find /vendor/firmware /vendor/firmware_mnt/image /odm/firmware /vendor/etc/wifi '
                '/odm/etc/wifi -maxdepth 4 -type f 2>/dev/null | '
                'grep -i -E "(bdwlan|board|regdb|amss|m3\\.bin|kiwi|hmt|hmtnv)" | head -200',
    'driver': 'ls /sys/module/wlan/parameters /sys/bus/platform/devices 2>/dev/null | '
              'grep -i -E "(fw|bdf|board|kiwi|wlan|cnss)"; '
              'dmesg | grep -i -E "(wcn7850|kiwi|cnss|bdwlan|bdf|board.id|firmware.version|fw.version)" | tail -160',
    'capability': 'dmesg | grep -i -E "(board.?id|chip.?id|chip.?family|soc.?id|bdf|bdwlan|fw.?version|'
                  'firmware.?version|fw.?build|amss|regdb|m3[_ .]|target.?version|hw.?version)" | head -200',
    'firmware_links': 'ls -ld /vendor/firmware/kiwi /vendor/firmware/kiwi_v2 /vendor/firmware_mnt/image/kiwi '
                      '/odm/firmware/kiwi 2>/dev/null; '
                      'find /vendor/firmware_mnt/image /vendor/firmware /odm/firmware -maxdepth 5 '
                      '-iname "*m3*" 2>/dev/null | head -60; '
                      'ls /sys/kernel/debug/cnss* /sys/kernel/debug/ieee80211 2>/dev/null',
}


def inspect(arguments):
    output = Path(arguments.output).resolve()
    expected = phone.ROOT / 'work/adsp-battery'
    if output.parent != expected or output.exists():
        raise ValueError('Use a new directory under work/adsp-battery')
    if phone.run(['adb', '-s', arguments.serial, 'shell', 'getprop', 'sys.boot_completed']).strip() != b'1':
        raise RuntimeError('Android is not ready')
    output.mkdir()
    records = {}
    with phone.phone_locks(output.name):
        for name, command in COMMANDS.items():
            contents = phone.adb(arguments.serial, command)
            if len(contents) > 1024 * 1024:
                raise ValueError('Unexpected survey output length')
            path = output / (name + '.txt')
            path.write_bytes(contents)
            records[name] = {'command': command, 'bytes': len(contents),
                             'sha256': hashlib.sha256(contents).hexdigest(), 'host_path': str(path)}
            phone.say('READ_ONLY_SURVEY', name, len(contents))
    (output / 'manifest.json').write_text(json.dumps({
        'captured_at': datetime.now().astimezone().isoformat(), 'method': 'read-only Android shell',
        'records': records,
    }, indent=2) + '\n', encoding='utf-8', newline='\n')
    phone.say('RADIO_SURVEY_SAVED', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--serial', default=os.environ.get('FUXI_ANDROID_SERIAL', ''))
    inspect(parser.parse_args())
