#!/usr/bin/env python3
"""Reboot into the resident boot_a dualboot menu through the shared phone launcher.

2026-11-18 起 boot_a 常駐 dualboot 選單，KSU 模組 fuxi_ios_boot 已移除：開 iOS 就是重開，
在選單用音量鍵選 iOS、短按電源確認。這裡只做重開前的唯讀檢查（a 槽、boot_a 是這條 chain
的已驗證選單、TWRP、iOS 根映像區塊表與 pin），先保存上一趟 mtd 紀錄，再重開。
不寫分區、不切槽、不要求重置期限。獨立開機沒有 USB，iOS 的 console 由下一趟
launcher 執行時從 mtd 取回。檢查沿用 phone-check.py 的鎖、mtd 保存與 Android 狀態檢查。
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-launcher', required=True)
    parser.add_argument('--chain', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.from_launcher != str(os.getppid()):
        raise ValueError('Use launch-loader-check.ps1')
    if not re.fullmatch(r'chain-[a-z0-9-]+', args.chain) or not re.fullmatch(r'[a-z0-9-]+', args.out):
        raise ValueError('Invalid chain/output name')
    spec = importlib.util.spec_from_file_location('daily_phone_check', Path(__file__).with_name('phone-check.py'))
    phone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(phone)
    workspace = phone.WORKSPACE
    chain = workspace / 'work/boot-chain' / args.chain
    report = json.loads((chain / 'menu-build-report.json').read_text(encoding='utf-8'))
    expected = report['candidate']['sha256']
    phone.need(report['result'] == 'ok' and phone.digest(chain / 'boot.img') == expected,
               'Menu image changed')
    out = workspace / 'work/dualboot' / args.out
    out.mkdir(exist_ok=False)
    token = f'daily menu reboot {args.chain} pid={os.getpid()} {phone.stamp()}'
    owned = []
    result = {'result': 'FAILED', 'chain': args.chain, 'started': phone.stamp(),
              'boot_sha256': expected, 'boot_partition_writes': 0, 'root_writes': 0,
              'slot_changes': 0, 'reset_deadline_requested': False}
    try:
        for path in (*phone.LOCKS, phone.HOLD):
            phone.need(not path.exists(), 'Phone is reserved: ' + str(path))
        for path in phone.LOCKS:
            with path.open('x', encoding='utf-8') as stream:
                stream.write(token)
            owned.append(path)
        phone.require_owned_locks(token)
        reboot_to_menu(phone, chain, expected, token, out, result)
        result['result'] = 'REBOOTED_TO_MENU_FOR_USER'
        phone.say('REBOOTED_TO_MENU; choose iOS with the volume keys and short-press Power; '
                  'the iOS console is saved from mtd on the next launcher run')
    except BaseException as error:
        result['error'] = str(error)
        raise
    finally:
        result['finished'] = phone.stamp()
        (out / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
        for path in reversed(owned):
            if path.is_file() and path.read_text(encoding='utf-8') == token:
                path.unlink()


def reboot_to_menu(phone, chain, expected, token, out, result):
    before = phone.android_state()
    phone.need(before['active_slot'] == '0', 'Expected active slot a')
    result['before'] = {k: v for k, v in before.items() if k != 'iomem'}
    size = (chain / 'boot.img').stat().st_size
    phone.need(phone.rooted(f'head -c {size} /dev/block/by-name/boot_a | sha256sum', timeout=120).split()[0] == expected,
               'boot_a does not hold this chain menu')
    full = phone.rooted('sha256sum /dev/block/by-name/boot_a', timeout=120).split()[0]
    phone.need(full in phone.installed_boot_a_shas(), 'boot_a is not a verified resident menu install')
    result['boot_a_full_sha256'] = full
    twrp = (phone.IOS_ENTRY / 'twrp.sha256').read_text(encoding='utf-8').strip()
    phone.need(phone.rooted('sha256sum /dev/block/by-name/recovery_a', timeout=60).split()[0] == twrp,
               'recovery_a is not the expected TWRP')
    result['ios_root'] = phone.verify_ios_root()
    result['previous_mtd'] = phone.preserve_mtd(out)
    phone.require_owned_locks(token)
    phone.say('REBOOT_TO_MENU')
    reboot = subprocess.run(['adb', '-s', phone.SERIAL, 'reboot'], capture_output=True, timeout=30)
    result['reboot_exit'] = reboot.returncode
    phone.need(reboot.returncode == 0, 'adb reboot failed: ' + reboot.stderr.decode('utf-8', 'replace')[-500:])


if __name__ == '__main__':
    main()
