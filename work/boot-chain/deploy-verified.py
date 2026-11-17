import argparse
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import traceback


MODULE_METADATA = ('loader.sha256', 'loader.size', 'expected-fiemap.txt', 'module.prop', 'action.sh')
HOST_MODULE_FILES = MODULE_METADATA + ('twrp.sha256', 'bin/inspect-fiemap', 'bin/check-pin')


parser = argparse.ArgumentParser()
parser.add_argument('previous')
parser.add_argument('next')
parser.add_argument('--version', type=int, required=True)
parser.add_argument('--menu-entry', action='store_true',
                    help='Label the KSU entry for an already built dualboot menu; keep slot/recovery guards.')
parser.add_argument('--skip-full-boot-backup', action='store_true',
                    help='Recover the same-length prefix from the verified previous host artifact; retain the small module-state record.')
arguments = parser.parse_args()
if arguments.version < 5 or not all(re.fullmatch(r'chain-[a-z0-9-]+', name) for name in (arguments.previous, arguments.next)):
    raise ValueError('Deployment requires version >= 5 and safe chain names')
workspace = Path(__file__).resolve().parents[2]
serial = os.environ.get('FUXI_ANDROID_SERIAL', '')
module_path = '/data/adb/modules/fuxi_ios_boot'
stock_a = '3d957296bb0db5596067ff1795ce521070f3dff5f5552834c2622bfeaa42d145'
boot_a_sha = None  # 部署開始時讀到的 boot_a；整趟（含失敗還原）都要求它不變


def allowed_boot_a():
    # 2026-11-18 起 boot_a 可能是已驗證的常駐 dualboot 選單；名單沿用 dualboot/phone-check.py，
    # 只接受安裝紀錄為 INSTALLED_ANDROID_VERIFIED 的整分區雜湊。
    import importlib.util
    spec = importlib.util.spec_from_file_location('dualboot_phone_check', workspace / 'dualboot/phone-check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {stock_a} | module.installed_boot_a_shas()
backup = workspace.parent / 'fuxi_Backup' / (
    'boot_b-' + arguments.previous + '-before-' + arguments.next + '-' +
    datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
locks = [workspace / 'work/PHONE-LOCK-000', workspace / 'work/hybrid-driver/HOLD-PHONE']
pause = workspace / 'work/adsp-battery/hw000/HOLD'
token = f'000 deploy {arguments.next} pid={os.getpid()} {datetime.datetime.now().isoformat()}'
owned = []


def say(message):
    print(datetime.datetime.now().strftime('%H:%M:%S'), message, flush=True)


def adb(*command):
    return subprocess.check_output(['adb', '-s', serial, *command], text=True, encoding='utf-8').strip()


def rooted(command):
    assert "'" not in command
    return adb('shell', f"su -c '{command}'").replace('\r', '')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pinned_image(name):
    directory = checked_local_path(Path(__file__).resolve().parent / name, workspace)
    checks_file = checked_local_path(directory / 'sha256.txt', workspace)
    checks = {filename.strip(): checksum for checksum, filename in (
        line.split(maxsplit=1) for line in checks_file.read_text().splitlines())}
    image = checked_local_path(directory / 'boot.img', workspace)
    assert digest(image) == checks['boot.img'], f'{name} host hash mismatch'
    return image, checks['boot.img']


def checked_local_path(path, root):
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    if root.resolve() != root or path.resolve() != path or not path.is_relative_to(root):
        raise ValueError(f'Recovery path leaves or redirects its named root: {path}')
    return path


def checked_file(path, root, checksum, byte_count):
    path = checked_local_path(path, root)
    if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size != byte_count or digest(path) != checksum:
        raise ValueError(f'Recovery preimage hash, size or file type differs: {path}')
    return path


def verify_device_capacity():
    values = rooted('od -An -t u1 /sys/firmware/devicetree/base/memory/ddr_size').split()
    if values != ['0', '0', '0', '12']:
        raise ValueError(f'Deployment requires DDR SKU bytes [0, 0, 0, 12]; unknown or 8GB rejected: {values}')


def error_details(error):
    return {'type': type(error).__name__, 'message': str(error),
            'traceback': ''.join(traceback.format_exception(type(error), error, error.__traceback__))}


def recovery_notice(message):
    try:
        say(message)
    except BaseException:
        pass


def recovery_event(report, event, **details):
    try:
        journal = checked_local_path(report['journal'], workspace.parent / 'fuxi_Backup')
        with journal.open('r+', encoding='utf-8', newline='\n') as stream:
            if json.loads(stream.readline())['token'] != token:
                raise ValueError('Recovery journal no longer belongs to this deployment')
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps({'event': event, 'token': token, **details}, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        return True
    except BaseException as failure:
        report['diagnostic_errors'].append(error_details(failure))
        return False


def new_recovery_report(error, suffix=''):
    report = {'token': token, 'original_error': error_details(error) if error else None,
              'previous': arguments.previous, 'next': arguments.next,
              'previous_image': str(previous_image), 'previous_sha256': previous_sha,
              'prefix_bytes': size, 'backup': str(backup), 'host_preimages': host_saved_hashes,
              'unresolved_remote_write': pending_write, 'steps': {}, 'diagnostic_errors': [],
              'recovery_verified': False, 'lock_state_at_report': 'held_before_finalization'}
    try:
        backup_root = workspace.parent / 'fuxi_Backup'
        directory = checked_local_path(backup, backup_root)
        tag = hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]
        name = 'recovery-' + tag + ('-' + suffix if suffix else '')
        directory = directory / name if backup_created else directory.with_name(directory.name + '-' + name)
        directory = checked_local_path(directory, backup_root)
        directory.mkdir(parents=True)
        report['journal'] = str(directory / 'recovery-journal.jsonl')
        report['report'] = str(directory / 'recovery-report.json')
        with Path(report['journal']).open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps({'event': 'recovery_begin', 'token': token,
                                     'original_error': report['original_error']}, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as failure:
        report['diagnostic_errors'].append(error_details(failure))
    return report


def save_recovery_report(report):
    try:
        path = checked_local_path(report['report'], workspace.parent / 'fuxi_Backup')
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        return True
    except BaseException as failure:
        report['diagnostic_errors'].append(error_details(failure))
        return False


def restore_boot():
    if not re.fullmatch(r'chain-[a-z0-9-]+', arguments.previous) or not 0 < size <= 201326592:
        raise ValueError('Invalid previous boot recovery identity')
    verify_device_capacity()
    image = checked_file(previous_image, workspace, previous_sha, size)
    tag = hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]
    remote = f'/data/local/tmp/fuxi-restore-{arguments.previous}-{tag}.img'
    adb('push', str(image), remote)
    if int(rooted(f'stat -c %s {remote}')) != size or rooted(f'sha256sum {remote}').split()[0] != previous_sha:
        raise ValueError('Uploaded previous boot recovery image differs')
    rooted(f'dd if={remote} of=/dev/block/by-name/boot_b bs=4194304 conv=fsync && sync')
    rooted('echo 3 > /proc/sys/vm/drop_caches')
    if rooted(f'head -c {size} /dev/block/by-name/boot_b | sha256sum').split()[0] != previous_sha:
        raise ValueError('Previous boot prefix recovery readback differs')
    if not boot_a_sha or rooted('sha256sum /dev/block/by-name/boot_a').split()[0] != boot_a_sha:
        raise ValueError('boot_a differs after recovery')
    if adb('shell', 'getprop ro.boot.slot_suffix') != '_a':
        raise ValueError('Phone is not in Android slot a after recovery')


def restore_module():
    if module_path != '/data/adb/modules/fuxi_ios_boot' or not archive_sha:
        raise ValueError('Module recovery identity or archive pin is missing')
    verify_device_capacity()
    archive = checked_local_path(backup / 'fuxi_ios_boot-module.tar', workspace.parent / 'fuxi_Backup')
    archive = checked_file(archive, workspace.parent / 'fuxi_Backup', archive_sha, archive.stat().st_size)
    members = {}
    with tarfile.open(archive) as saved:
        for member in saved:
            name = member.name.rstrip('/')
            if (not re.fullmatch(r'fuxi_ios_boot(?:/[A-Za-z0-9_.-]+)*', name) or
                    any(part in ('.', '..') for part in name.split('/')) or
                    name in members or not (member.isfile() or member.isdir())):
                raise ValueError(f'Unsafe or duplicated module recovery member: {member.name}')
            checksum = hashlib.file_digest(saved.extractfile(member), 'sha256').hexdigest() if member.isfile() else None
            members[name] = (member, checksum)
        for name in MODULE_METADATA:
            if f'fuxi_ios_boot/{name}' not in members or not members[f'fuxi_ios_boot/{name}'][0].isfile():
                raise ValueError(f'Module recovery archive lacks {name}')
        if saved.extractfile('fuxi_ios_boot/loader.sha256').read().decode().strip() != previous_sha:
            raise ValueError('Module recovery loader pin differs')
        if int(saved.extractfile('fuxi_ios_boot/loader.size').read()) != size:
            raise ValueError('Module recovery prefix length differs')
    tag = hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]
    remote = f'/data/local/tmp/fuxi-module-restore-{tag}.tar'
    adb('push', str(archive), remote)
    if rooted(f'sha256sum {remote}').split()[0] != archive_sha:
        raise ValueError('Uploaded module recovery archive differs')
    rooted(f'tar -xf {remote} -C /data/adb/modules && sync')
    for name, (member, checksum) in members.items():
        target = '/data/adb/modules/' + name
        if member.isdir():
            rooted(f'test -d {target}')
        elif rooted(f'sha256sum {target}').split()[0] != checksum:
            raise ValueError(f'Module recovery readback differs: {name}')
        metadata = rooted(f'stat -c "%a %u %g" {target}').split()
        if (int(metadata[0], 8), int(metadata[1]), int(metadata[2])) != (member.mode & 0o7777, member.uid, member.gid):
            raise ValueError(f'Module recovery permissions or ownership differ: {name}')


def restore_host_module():
    if set(host_saved_hashes) != set(HOST_MODULE_FILES):
        raise ValueError('Host module recovery preimages are incomplete')
    failures = []
    for name in HOST_MODULE_FILES:
        try:
            record = host_saved_hashes[name]
            source = checked_file(backup / 'host-module-before' / name, workspace.parent / 'fuxi_Backup',
                                  record['sha256'], record['bytes'])
            target = checked_local_path(local_module / name, workspace / 'work/ksu-ios-entry/fuxi_ios_boot')
            if not stat.S_ISREG(target.lstat().st_mode):
                raise ValueError(f'Host module recovery target is not a regular file: {target}')
            shutil.copyfile(source, target)
            checked_file(target, workspace, record['sha256'], record['bytes'])
        except BaseException as failure:
            failures.append(f'{name}: {type(failure).__name__}: {failure}')
    if failures:
        raise RuntimeError('Host module recovery failures: ' + '; '.join(failures))


def recover_deployment(error):
    report = new_recovery_report(error)
    interrupted = isinstance(error, (KeyboardInterrupt, SystemExit, subprocess.TimeoutExpired))
    report['interrupted'] = interrupted
    journal_ok = not report['diagnostic_errors']
    actions = (('boot', boot_changed, restore_boot), ('module', module_changed, restore_module),
               ('host_module', host_changed, restore_host_module))
    for name, required, action in actions:
        step = {'required': required, 'attempted': False, 'verified': not required}
        report['steps'][name] = step
        if not required:
            continue
        journal_ok = recovery_event(report, 'restore_begin', step=name) and journal_ok
        step['attempted'] = True
        try:
            if pending_write and name != 'host_module':
                raise RuntimeError(f'Remote writer completion is unknown: {pending_write}; manual recovery required')
            action()
            step['verified'] = True
        except BaseException as failure:
            step['error'] = error_details(failure)
        journal_ok = recovery_event(report, 'restore_end', step=name, result=step) and journal_ok
    report['recovery_verified'] = all(step['verified'] for step in report['steps'].values()) and not pending_write and not interrupted
    journal_ok = recovery_event(report, 'recovery_verification', verified=report['recovery_verified']) and journal_ok
    durable = save_recovery_report(report)
    authorized = report['recovery_verified'] and durable and journal_ok and not report['diagnostic_errors']
    if authorized:
        authorized = recovery_event(report, 'recovery_confirmed')
    return authorized, report


def finish_deployment(authorized, report):
    if not authorized:
        if report:
            recovery_event(report, 'locks_held', locks=[str(path) for path in owned])
        recovery_notice(f'MANUAL_RECOVERY_REQUIRED; owned token locks retained; report={report.get("report", "unavailable") if report else "unavailable"}')
        return False
    statuses = {}
    try:
        expected = {workspace / 'work/PHONE-LOCK-000', workspace / 'work/hybrid-driver/HOLD-PHONE'}
        for path in owned:
            path = checked_local_path(path, workspace)
            if path not in expected:
                raise ValueError(f'Unexpected owned phone lock path: {path}')
            if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError(f'Phone lock is not a regular file: {path}')
        if report and not recovery_event(report, 'lock_release_authorized'):
            raise RuntimeError('Cannot durably journal token lock release')
        for path in owned:
            path = checked_local_path(path, workspace)
            if not path.exists():
                statuses[str(path)] = 'missing'
            elif path.read_text(encoding='utf-8') != token:
                statuses[str(path)] = 'foreign_token_retained'
            else:
                before = path.stat()
                if path.read_text(encoding='utf-8') != token or path.stat() != before:
                    statuses[str(path)] = 'changed_lock_retained'
                    raise RuntimeError(f'Token lock changed during release precondition: {path}')
                path.unlink()
                statuses[str(path)] = 'own_token_removed'
                if report and not recovery_event(report, 'own_lock_removed', path=str(path)):
                    raise RuntimeError('Cannot durably journal token lock removal')
        if report and not recovery_event(report, 'lock_release_finished', locks=statuses):
            raise RuntimeError('Cannot durably journal final token lock status')
        retained = any(status.endswith('_retained') for status in statuses.values())
        recovery_notice('OWN_PHONE_LOCKS_RELEASED; foreign or changed locks retained' if retained else 'PHONE_RELEASED')
        return True
    except BaseException as failure:
        if report is None:
            report = new_recovery_report(failure, 'locks')
            report['deployment_verified'] = True
            save_recovery_report(report)
        recovery_event(report, 'lock_release_failed', error=error_details(failure), locks=statuses)
        recovery_notice(f'MANUAL_RECOVERY_REQUIRED; token lock release uncertain; report={report.get("report", "unavailable")}')
        return False


previous_image, previous_sha = pinned_image(arguments.previous)
next_image, next_sha = pinned_image(arguments.next)
if arguments.menu_entry:
    menu_record = json.loads((next_image.parent / 'menu-build-report.json').read_text(encoding='utf-8'))
    if menu_record['result'] != 'ok' or menu_record['candidate']['sha256'] != next_sha:
        raise ValueError('Menu entry requires the matching successful menu build report')
assert previous_image.stat().st_size == next_image.stat().st_size
size = next_image.stat().st_size
assert size <= 201326592
for path in [*locks, pause]:
    assert not path.exists(), f'Phone is reserved: {path}'
assert adb('shell', 'getprop sys.boot_completed') == '1'
assert adb('shell', 'getprop ro.boot.slot_suffix') == '_a'
# 2026-11-18 起手機上的 KSU 模組已移除：boot_a 常駐 dualboot 選單，重開即可選 iOS。
# 本工具會更新並重裝模組；模組不在就停在這裡，不拿鎖、不動手機。
if rooted(f'[ -d {module_path} ] && echo present || echo absent').strip() != 'present':
    raise SystemExit('KSU module fuxi_ios_boot was removed on 2026-11-18; deploy-verified would reinstall it and is retired')
boot_changed = False
module_changed = False
host_changed = False
backup_created = False
archive_sha = None
host_saved_hashes = {}
pending_write = None
release_allowed = False
failure_report = None
local_module = workspace / 'work/ksu-ios-entry/fuxi_ios_boot'
try:
    for path in locks:
        checked_local_path(path, workspace)
        with path.open('x', encoding='utf-8') as stream:
            stream.write(token)
        owned.append(path)
    assert not pause.exists()
    say(f'PHONE_START {arguments.previous} -> {arguments.next}')
    boot_a_sha = rooted('sha256sum /dev/block/by-name/boot_a').split()[0]
    assert boot_a_sha in allowed_boot_a(), f'boot_a is neither stock nor a verified dualboot install: {boot_a_sha}'
    verify_device_capacity()
    assert rooted(f'head -c {size} /dev/block/by-name/boot_b | sha256sum').split()[0] == previous_sha
    assert rooted(f'cat {module_path}/loader.sha256') == previous_sha
    assert 'mapped=true' not in rooted(
        'CLASSPATH=/data/local/tmp/codex-managed-native-image.jar app_process /system/bin ManagedNativeImage status')
    checked_local_path(backup, workspace.parent / 'fuxi_Backup')
    backup.mkdir(parents=True)
    backup_created = True
    archive = backup / 'fuxi_ios_boot-module.tar'
    with archive.open('wb') as stream:
        subprocess.run(['adb', '-s', serial, 'exec-out',
                        f'su -c "tar -c -C /data/adb/modules fuxi_ios_boot"'], stdout=stream, check=True)
    with tarfile.open(archive) as saved:
        assert saved.extractfile('fuxi_ios_boot/loader.sha256').read().decode().strip() == previous_sha
    archive_sha = digest(archive)
    backup_checks = [f'{archive_sha}  {archive.name}\n']
    saved_boot_state = f'boot_b_recovery_source={previous_image}\nboot_b_prefix_size={size}\n'
    if not arguments.skip_full_boot_backup:
        whole_b = rooted('sha256sum /dev/block/by-name/boot_b').split()[0]
        boot_backup = backup / 'boot_b.img.gz'
        reader = subprocess.Popen(['adb', '-s', serial, 'exec-out',
                                   'su -c "cat /dev/block/by-name/boot_b"'], stdout=subprocess.PIPE)
        checksum = hashlib.sha256()
        total = 0
        with gzip.open(boot_backup, 'wb', compresslevel=1) as compressed:
            while chunk := reader.stdout.read(1024 * 1024):
                checksum.update(chunk)
                total += len(chunk)
                compressed.write(chunk)
        assert reader.wait() == 0 and total == 201326592 and checksum.hexdigest() == whole_b
        with gzip.open(boot_backup, 'rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == whole_b
        backup_checks.append(f'{digest(boot_backup)}  {boot_backup.name}\n')
        saved_boot_state += f'boot_b_full_sha256={whole_b}\nboot_b_full_size={total}\n'
    (backup / 'SHA256SUMS').write_text(''.join(backup_checks), newline='\n')
    (backup / 'state.txt').write_text(
        f'previous={arguments.previous}\nprevious_prefix_sha256={previous_sha}\n'
        f'{saved_boot_state}'
        f'next={arguments.next}\nnext_prefix_sha256={next_sha}\nboot_a_sha256={boot_a_sha}\n', newline='\n')
    local_saved = backup / 'host-module-before'
    local_saved.mkdir()
    for name in HOST_MODULE_FILES:
        source = checked_local_path(local_module / name, workspace)
        target = checked_local_path(local_saved / name, workspace.parent / 'fuxi_Backup')
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {'sha256': digest(source), 'bytes': source.stat().st_size}
        shutil.copyfile(source, target)
        checked_file(target, workspace.parent / 'fuxi_Backup', record['sha256'], record['bytes'])
        host_saved_hashes[name] = record
    properties = (local_module / 'module.prop').read_text(encoding='utf-8')
    properties = re.sub(r'^version=.*$', f'version=v{arguments.version}', properties, flags=re.M)
    properties = re.sub(r'^versionCode=.*$', f'versionCode={arguments.version}', properties, flags=re.M)
    if arguments.menu_entry:
        properties = re.sub(r'^name=.*$', 'name=雙系統選單（小米 13）', properties, flags=re.M)
        properties = re.sub(r'^description=.*$',
            'description=按「執行」：檢查映像、boot_b 與 TWRP，再進 dualboot 選單。音量鍵選擇 Android／iOS，短按電源確認。回 Slot A 可用 TWRP。',
            properties, flags=re.M)
    host_changed = True
    (local_module / 'module.prop').write_text(properties, encoding='utf-8', newline='\n')
    if arguments.menu_entry:
        action_file = local_module / 'action.sh'
        action_text = action_file.read_text(encoding='utf-8')
        action_text = action_text.replace('重開進 iOS（約 30 秒）', '重開進雙系統選單（音量鍵選擇，短按電源確認）')
        action_file.write_text(action_text, encoding='utf-8', newline='\n')
    subprocess.run([sys.executable, str(workspace / 'work/ksu-ios-entry/build-module.py'),
                    arguments.next], check=True)
    remote_image = f'/data/local/tmp/fuxi-{arguments.next}.img'
    adb('push', str(next_image), remote_image)
    assert rooted(f'sha256sum {remote_image}').split()[0] == next_sha
    say(f'BACKUP_OK {backup}')
    boot_changed = True
    pending_write = 'deploy boot_b'
    rooted(f'dd if={remote_image} of=/dev/block/by-name/boot_b bs=4194304 conv=fsync && sync')
    pending_write = None
    rooted('echo 3 > /proc/sys/vm/drop_caches')
    assert rooted(f'head -c {size} /dev/block/by-name/boot_b | sha256sum').split()[0] == next_sha
    assert rooted('sha256sum /dev/block/by-name/boot_a').split()[0] == boot_a_sha
    say('BOOT_B_READBACK_OK')
    module_changed = True
    for name in MODULE_METADATA:
        temporary = '/data/local/tmp/fuxi-mod-' + name
        adb('push', str(local_module / name), temporary)
        pending_write = 'deploy module/' + name
        mode = '755' if name.endswith('.sh') else '644'
        rooted(f'cp {temporary} {module_path}/{name} && chmod {mode} {module_path}/{name}')
        pending_write = None
        assert rooted(f'sha256sum {module_path}/{name}').split()[0] == digest(local_module / name)
    action = rooted(f'cat {module_path}/action.sh')
    preflight, marker, unused = action.partition('echo "[4/5]')
    assert marker and '[3/5]' in preflight and 'bootctl set-active' not in preflight and '\nreboot\n' not in preflight
    preflight = re.sub(r'^case "\$0".*?esac$', f'MODDIR={module_path}', preflight, flags=re.M)
    preflight += '\necho MODULE_PREFLIGHT_OK\n'
    preflight_file = backup / 'module-preflight.sh'
    preflight_file.write_text(preflight, encoding='utf-8', newline='\n')
    adb('push', str(preflight_file), '/data/local/tmp/fuxi-module-preflight.sh')
    output = rooted('sh /data/local/tmp/fuxi-module-preflight.sh')
    assert 'MODULE_PREFLIGHT_OK' in output
    assert rooted(f'cat {module_path}/loader.sha256') == next_sha
    assert adb('shell', 'getprop ro.boot.slot_suffix') == '_a'
    say(output)
    say(f'DEPLOY_DONE {arguments.next} {next_sha}')
    release_allowed = True
except BaseException as deployment_failure:
    try:
        release_allowed, failure_report = recover_deployment(deployment_failure)
    except BaseException as recovery_failure:
        release_allowed = False
        try:
            failure_report = new_recovery_report(deployment_failure, 'unexpected')
            failure_report['unexpected_recovery_error'] = error_details(recovery_failure)
            save_recovery_report(failure_report)
        except BaseException:
            recovery_notice('MANUAL_RECOVERY_REQUIRED; recovery diagnostics unavailable; owned token locks retained')
    raise
finally:
    try:
        finish_deployment(release_allowed, failure_report)
    except BaseException as finalization_failure:
        try:
            finalization_report = new_recovery_report(finalization_failure, 'finalization')
            save_recovery_report(finalization_report)
        except BaseException:
            pass
        recovery_notice('MANUAL_RECOVERY_REQUIRED; finalization uncertain; owned token locks retained')
