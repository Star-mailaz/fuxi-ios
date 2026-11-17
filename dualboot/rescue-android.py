#!/usr/bin/env python3
"""Return the identified Fuxi to its preserved slot-a Android, without flashing.

Entry is exclusively launch-loader-check.ps1. Reuses phone-check.py's exact
device identity, token locks, verified restore point, Android and mtd checks.
Only the bootloader's existing set_active command changes slot metadata.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time


def getvar(phone, name):
    reply = subprocess.run(['fastboot', '-s', phone.SERIAL, 'getvar', name],
                           capture_output=True, timeout=15)
    text = (reply.stdout + reply.stderr).decode('utf-8', 'replace')
    phone.need(reply.returncode == 0, 'Fastboot getvar failed: ' + name)
    match = re.search(r'(?m)^\s*(?:\(bootloader\)\s*)?' + re.escape(name) + r':\s*(\S+)\s*$', text)
    phone.need(match is not None, 'Missing fastboot variable: ' + name)
    return match.group(1)


def select_original_slot(phone, result, save):
    devices = phone.command('fastboot', 'devices')
    phone.need(any(line.split() == [phone.SERIAL, 'fastboot'] for line in devices.splitlines()),
               'Expected device is not in bootloader Fastboot')
    product = getvar(phone, 'product')
    phone.need(product == 'fuxi', 'Unexpected fastboot product')
    before = getvar(phone, 'current-slot')
    phone.need(before in ('a', 'b'), 'Unexpected current slot')
    result['fastboot_before'] = {'product': product, 'current_slot': before}
    result['metadata_change_requested'] = before != 'a'
    save()
    if before != 'a':
        # No flash/erase command is exposed. This preserves both boot images.
        phone.command('fastboot', '-s', phone.SERIAL, 'set_active', 'a')
    after = getvar(phone, 'current-slot')
    result['fastboot_after_slot'] = after
    save()
    phone.need(after == 'a', 'Slot metadata readback differs; do not reboot')
    phone.say('SLOT_A_READBACK_OK; rebooting original Android')
    phone.command('fastboot', '-s', phone.SERIAL, 'reboot')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-launcher', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.from_launcher != str(os.getppid()) or not re.fullmatch(r'[a-z0-9-]+', args.out):
        raise ValueError('Use launch-loader-check.ps1 with a unique output name')
    spec = importlib.util.spec_from_file_location('rescue_phone', Path(__file__).with_name('phone-check.py'))
    phone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(phone)
    receipt = json.loads(phone.RESTORE_RECEIPT.read_text(encoding='utf-8'))
    restore = Path(receipt['restore_point']).resolve()
    phone.need(restore.is_relative_to(phone.WORKSPACE.parent / 'fuxi_Backup'), 'Unexpected restore point')
    original = json.loads((restore / 'phone/manifest.json').read_text(encoding='utf-8'))
    boot = original['partitions']['boot_a']
    archive = Path(boot['file']).resolve()
    phone.need(archive.is_relative_to(restore) and phone.digest(archive) == boot['file_sha256'],
               'Original boot_a backup changed')
    with gzip.open(archive, 'rb') as stream:
        phone.need(hashlib.file_digest(stream, 'sha256').hexdigest() == boot['raw_sha256'],
                   'Original boot_a backup cannot be restored')
    out = phone.WORKSPACE / 'work/dualboot' / args.out
    out.mkdir(exist_ok=False)
    token = f'Android slot-a rescue pid={os.getpid()} {phone.stamp()}'
    owned = []
    result = {'result': 'IN_PROGRESS', 'started': phone.stamp(), 'restore_point': str(restore),
              'boot_partition_writes': 0, 'root_writes': 0, 'expected_boot_a_sha256': boot['raw_sha256']}
    def save():
        (out / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                                        encoding='utf-8', newline='\n')
    try:
        for path in (*phone.LOCKS, phone.HOLD):
            phone.need(not path.exists(), 'Phone is reserved: ' + str(path))
        for path in phone.LOCKS:
            with path.open('x', encoding='utf-8') as stream:
                stream.write(token)
            owned.append(path)
        phone.require_owned_locks(token)
        phone.say('PHONE_START original Android rescue; no partition flashing')
        select_original_slot(phone, result, save)
        for attempt in range(60):
            phone.require_owned_locks(token)
            try:
                if phone.adb('shell', 'getprop sys.boot_completed', timeout=4) == '1':
                    break
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            if attempt % 5 == 0:
                phone.say('WAITING_FOR_ORIGINAL_ANDROID')
            time.sleep(3)
        else:
            raise RuntimeError('Original Android not yet ready; owned locks retained')
        state = phone.android_state()
        phone.need(state['active_slot'] == '0', 'Android active slot is not a')
        phone.need(phone.rooted('sha256sum /dev/block/by-name/boot_a', timeout=90).split()[0] == boot['raw_sha256'],
                   'Original Android boot_a changed')
        result['android'] = {key: value for key, value in state.items() if key != 'iomem'}
        result['mtd_capture'] = phone.preserve_mtd(out)
        result['result'] = 'ORIGINAL_ANDROID_A_RESTORED'
        phone.say('ORIGINAL_ANDROID_A_RESTORED; stock boot_a hash verified')
    except BaseException as error:
        result['result'] = 'NEEDS_ATTENTION'
        result['error'] = str(error)
        raise
    finally:
        result['finished'] = phone.stamp()
        release = result['result'] == 'ORIGINAL_ANDROID_A_RESTORED'
        result['lock_state'] = 'released' if release else 'retained'
        result['lock_token'] = token
        save()
        if release:
            for path in reversed(owned):
                if path.is_file() and path.read_text(encoding='utf-8') == token:
                    path.unlink()


if __name__ == '__main__':
    main()
