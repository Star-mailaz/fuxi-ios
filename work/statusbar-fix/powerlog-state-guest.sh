#!/bin/sh
set -eu
trap 'echo POWERLOG_STATE_FAILED' EXIT
modprobe hfsplus
blockdev --setro /dev/vda
[ "$(cat /sys/block/vda/ro)" = 1 ]
[ "$(cat /sys/block/vda/size)" = 41943040 ]
mkdir -p /dst
mount -t hfsplus -o ro /dev/vda /dst >/tmp/powerlog-mount.log 2>&1
python3 - <<'PY'
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import sys

ROOT = Path('/dst')
MAX_JSON = 65536
MAX_ENTRIES = 128
MAX_SCAN = 4096
MAX_PLIST = 1024 * 1024
PLIST_KEYS = ('Label', 'Program', 'ProgramArguments', 'Disabled', 'RunAtLoad', 'KeepAlive')


def target(value):
    return isinstance(value, str) and (value.lower() in ('com.apple.timed', 'com.apple.powerd')
        or 'powerlog' in value.lower() or 'perfpowerservices' in value.lower())


def checked(path):
    current = ROOT
    information = current.lstat()
    if not stat.S_ISDIR(information.st_mode):
        raise ValueError('invalid_root')
    for component in Path(path).parts[1:]:
        if component in ('.', '..'):
            raise ValueError('invalid_path')
        current = current / component
        try:
            information = current.lstat()
        except FileNotFoundError:
            return current, None
        if stat.S_ISLNK(information.st_mode):
            raise ValueError('symlink_not_followed')
    return current, information


def metadata(path):
    record = {'path': path}
    try:
        physical, information = checked(path)
        record['exists'] = information is not None
        if information is not None:
            record.update(size=information.st_size, mtime_ns=information.st_mtime_ns,
                          kind='directory' if stat.S_ISDIR(information.st_mode) else
                          'file' if stat.S_ISREG(information.st_mode) else 'other')
    except (OSError, ValueError):
        record.update(exists=None, error='path_unavailable_or_symlink')
    return record


def timezone_link(path):
    record = {'path': path}
    try:
        parent, information = checked(str(Path(path).parent))
        if information is None:
            record['exists'] = False
            return record
        physical = parent / Path(path).name
        information = physical.lstat()
        record['exists'] = True
        record['kind'] = 'symlink' if stat.S_ISLNK(information.st_mode) else 'other'
        if stat.S_ISLNK(information.st_mode):
            destination = os.readlink(physical)
            if len(destination) > 512:
                raise ValueError('timezone_target_limit')
            record['target'] = destination
    except FileNotFoundError:
        record['exists'] = False
    except (OSError, ValueError):
        record.update(exists=None, error='timezone_link_unavailable')
    return record


def read_plist(path):
    physical, information = checked(path)
    if information is None:
        return None
    if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= MAX_PLIST:
        raise ValueError('plist_size_or_type')
    with physical.open('rb') as stream:
        contents = stream.read(MAX_PLIST + 1)
    if len(contents) != information.st_size:
        raise ValueError('plist_read_size')
    value = plistlib.loads(contents)
    if not isinstance(value, dict):
        raise ValueError('plist_not_dictionary')
    return value


def selected(value, depth=0):
    if type(value) in (bool, int) or value is None:
        return value
    if isinstance(value, str) and len(value) <= 256:
        return value
    if depth < 2 and isinstance(value, list) and len(value) <= 24:
        return [selected(item, depth + 1) for item in value]
    if depth < 2 and isinstance(value, dict) and len(value) <= 16:
        return {key: selected(item, depth + 1) for key, item in value.items()
                if isinstance(key, str) and len(key) <= 128}
    return {'unknown': 'unsupported_or_over_limit'}


def names(path):
    physical, information = checked(path)
    if information is None:
        return []
    if not stat.S_ISDIR(information.st_mode):
        raise ValueError('not_directory')
    result = []
    with os.scandir(physical) as entries:
        for entry in entries:
            if len(result) == MAX_SCAN:
                raise ValueError('directory_scan_limit')
            if len(entry.name) > 256:
                raise ValueError('filename_limit')
            result.append(entry.name)
    return sorted(result)


def wifi_summary(value):
    fields = ('SSID_STR', 'SSID', 'AutoJoin', 'AutoLogin', 'Disabled', 'HIDDEN_NETWORK',
              'Hidden', 'Secure', 'SecurityMode', 'IsPersonalHotspot', 'JoinedByUser',
              'WasCaptive', 'Captive', 'AP_MODE')
    profiles = []
    visited = 0

    def settings(item, depth=0):
        if depth > 4 or len(item) > 128:
            raise ValueError('wifi_settings_limit')
        result = {}
        for key, entry in item.items():
            if any(word in key.lower() for word in ('pass', 'secret', 'token', 'credential', 'key')):
                continue
            if type(entry) in (bool, int, float):
                result[key] = entry
            elif isinstance(entry, datetime):
                result[key] = entry.isoformat()
            elif key in ('SSID_STR', 'BSSID', 'SecurityMode', 'JoinMode', 'JoinRecommendationMode') and (
                    isinstance(entry, str) and len(entry) <= 128):
                result[key] = entry
            elif isinstance(entry, dict):
                nested = settings(entry, depth + 1)
                if nested:
                    result[key] = nested
        return result

    def field_types(item):
        if len(item) > 128 or any(not isinstance(key, str) or len(key) > 160 for key in item):
            raise ValueError('wifi_field_limit')
        return {key: type(entry).__name__ for key, entry in item.items()}

    def visit(item, depth, context):
        nonlocal visited
        visited += 1
        if visited > 4096 or depth > 8:
            raise ValueError('wifi_profile_scan_limit')
        if isinstance(item, dict):
            if any(key in item for key in ('SSID_STR', 'SSID')):
                if len(profiles) >= 32:
                    raise ValueError('wifi_profile_count_limit')
                profile = {'context': context, 'field_types': field_types(item), 'settings': settings(item)}
                for key in fields:
                    entry = item.get(key)
                    if type(entry) in (bool, int):
                        profile[key] = entry
                    elif isinstance(entry, str) and len(entry) <= 128:
                        profile[key] = entry
                    elif key == 'SSID' and isinstance(entry, bytes) and len(entry) <= 32:
                        profile[key] = entry.decode('utf-8', 'replace')
                profiles.append(profile)
            for key, entry in item.items():
                if isinstance(entry, (dict, list)):
                    visit(entry, depth + 1, context + '/' + key[:80])
        elif isinstance(item, list):
            for index, entry in enumerate(item):
                if isinstance(entry, (dict, list)):
                    visit(entry, depth + 1, context + '/' + str(index))

    visit(value, 0, '')
    return {'flags': {key: entry for key, entry in value.items()
                      if isinstance(key, str) and len(key) <= 80 and type(entry) is bool},
            'field_types': field_types(value), 'settings': settings(value), 'profiles': profiles}


def wifi_log_summary(details=False, focus=None):
    configuration_path = '/private/var/preferences/SystemConfiguration/com.apple.wifi.plist'
    log_directory = '/private/var/logs'
    candidates = [metadata(log_directory + '/wifimanager.log')]
    if metadata(log_directory).get('kind') == 'directory':
        rotations = [name for name in names(log_directory)
                     if re.fullmatch(r'wifimanager\.log\.[0-9]{1,3}', name)]
        if len(rotations) > 8:
            raise ValueError('wifi_log_rotation_limit')
        candidates.extend(metadata(log_directory + '/' + name) for name in rotations)
    available = [record for record in candidates if record.get('kind') == 'file']
    result = {'configuration': metadata(configuration_path), 'records': [],
              'path_candidates': candidates,
              'links': [timezone_link('/Library'), timezone_link('/Library/Logs')],
              'log': max(available, key=lambda record: record['mtime_ns']) if available else candidates[0]}
    try:
        configuration = read_plist(configuration_path)
        enabled = configuration.get('LoggingFileEnabled')
        result['configuration']['logging_enabled'] = enabled if type(enabled) is bool else None
        result['configuration_summary'] = wifi_summary(configuration)
    except (OSError, ValueError, AttributeError):
        result['configuration']['error'] = 'configuration_unavailable'
    if result['log'].get('kind') != 'file':
        return result
    physical, information = checked(result['log']['path'])
    start = max(0, information.st_size - 2 * 1024 * 1024)
    with physical.open('rb') as stream:
        stream.seek(start)
        content = stream.read(2 * 1024 * 1024)
    result['log']['tail_bytes'] = len(content)
    result['log']['tail_start'] = start
    selected_pattern = re.compile(r'auto.?join|skipped candidate|joinmode|known network|blacklist', re.I)
    if details:
        selected_pattern = re.compile(
            r'scan.*(result|network)|suitability|filter|candidate|unified|bssid|ssid|WiFiBatteryMgmt|CPMS|power budget', re.I)
    if focus is not None:
        if not 1 <= len(focus) <= 256:
            raise ValueError('wifi_log_focus_limit')
        selected_pattern = re.compile(focus, re.I)
    private_pattern = re.compile(
        r'pass|secret|credential|keychain|\b(key|pmk|psk|ptk|gtk|token)\b|CFData|\bbytes\s*=', re.I)
    result['selection'] = {'focus': focus, 'matched': 0, 'redacted': 0, 'omitted': 0}
    result['redacted_sources'] = {}
    result['credential_decisions'] = {
        'password_missing': 0, 'missing_password_disabled': 0, 'keychain_lookup_errors': {},
        'keychain_save_errors': {}, 'save_failures': 0, 'removed_after_failed_association': 0}
    credential_prefix = r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\.\d{3} '
    missing_password = re.compile(
        credential_prefix + r'__WiFiDeviceManagerKnownNetworkSuitabilityCheck: '
        r'No password found for .{1,160}, return as unsuitable\s*$')
    disabled_password = re.compile(
        credential_prefix + r'__WiFiDeviceManagerKnownNetworkSuitabilityCheck: '
        r'disabled for missing password Network .{1,160} isFilteringAJCandidates [01]\s*$')
    lookup_error = re.compile(
        credential_prefix + r'WiFiSecurityCopy(NonSyncable)?PasswordWithTimeout_block_invoke:'
        r'\[.{1,160}\] Error result (-?[0-9]{1,10})\s*$')
    save_error = re.compile(
        credential_prefix + r'__WiFiSecuritySetPassword:\[.{1,160}\] Error result (-?[0-9]{1,10})\s*$')
    save_failure = re.compile(credential_prefix + r'Error saving (?:new )?password in keychain\s*$')
    removed_password = re.compile(
        credential_prefix + r'[A-Za-z_][A-Za-z0-9_]{0,95}: removing password for .{1,160}'
        r' due to failed association\s*$')
    position = start
    for index, raw in enumerate(content.splitlines(keepends=True)):
        offset = position
        position += len(raw)
        if (start and index == 0) or len(raw) > 4096:
            continue
        text = raw.decode('utf-8', 'replace').strip('\r\n')
        if missing_password.fullmatch(text):
            result['credential_decisions']['password_missing'] += 1
        if disabled_password.fullmatch(text):
            result['credential_decisions']['missing_password_disabled'] += 1
        error = lookup_error.fullmatch(text)
        if error and -(2 ** 31) <= int(error[2]) < 2 ** 31:
            operation = 'nonsyncable' if error[1] else 'standard'
            status_key = operation + ':' + str(int(error[2]))
            errors = result['credential_decisions']['keychain_lookup_errors']
            if status_key not in errors and len(errors) >= 16:
                status_key = 'other'
            errors[status_key] = errors.get(status_key, 0) + 1
        error = save_error.fullmatch(text)
        if error and -(2 ** 31) <= int(error[1]) < 2 ** 31:
            status_key = str(int(error[1]))
            errors = result['credential_decisions']['keychain_save_errors']
            if status_key not in errors and len(errors) >= 16:
                status_key = 'other'
            errors[status_key] = errors.get(status_key, 0) + 1
        if save_failure.fullmatch(text):
            result['credential_decisions']['save_failures'] += 1
        if removed_password.fullmatch(text):
            result['credential_decisions']['removed_after_failed_association'] += 1
        if selected_pattern.search(text):
            result['selection']['matched'] += 1
            if private_pattern.search(text):
                result['selection']['redacted'] += 1
                source = re.match(
                    r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\.\d{3} ([A-Za-z_][A-Za-z0-9_]{0,95}):', text)
                source_name = source[1] if source else 'unclassified'
                if source_name not in result['redacted_sources'] and len(result['redacted_sources']) >= 32:
                    source_name = 'other'
                result['redacted_sources'][source_name] = result['redacted_sources'].get(source_name, 0) + 1
                continue
            result['records'].append({'offset': offset, 'text': text[:480]})
            if len(result['records']) > 100:
                result['records'].pop(50)
                result['selection']['omitted'] += 1
    return result


def collect():
    mounts = [line.split() for line in Path('/proc/mounts').read_text().splitlines()]
    matches = [entry for entry in mounts if entry[1] == str(ROOT)]
    if len(matches) != 1 or matches[0][0] != '/dev/vda' or matches[0][2] != 'hfsplus':
        raise ValueError('mount_identity')
    options = matches[0][3].split(',')
    if 'ro' not in options or 'rw' in options or Path('/sys/block/vda/ro').read_text().strip() != '1':
        raise ValueError('mount_not_readonly')
    result = {'schema': 1, 'hfs_readonly': True, 'block_readonly': True,
              'database_contents_read': False, 'root_writes': 0,
              'runtime_daemon_state': 'not_observed', 'clock_correctness': 'not_established',
              'scope': 'fixed system plist allowlist and database metadata; not exhaustive',
              'launchd': [], 'overrides': [], 'databases': [],
              'timezone_links': [timezone_link(path) for path in (
                  '/private/var/db/timezone/localtime',
                  '/private/var/db/timezone/zoneinfo',
                  '/private/etc/localtime')]}
    if Path('/mnt/share/inspect-wifi-log').is_file():
        result['scope'] = 'fixed native Wi-Fi log and logging flag; filtered decision messages only'
        focus_path = Path('/mnt/share/inspect-wifi-log-focus')
        focus = focus_path.read_text(encoding='utf-8') if focus_path.is_file() else None
        result['wifi_log'] = wifi_log_summary(Path('/mnt/share/inspect-wifi-log-details').is_file(), focus)
        return result
    directory = '/System/Library/LaunchDaemons'
    directory_record = metadata(directory)
    result['launchd_directory'] = directory_record
    if directory_record.get('kind') == 'directory':
        candidates = [name for name in names(directory) if name.endswith('.plist') and target(name[:-6])]
        if len(candidates) > 32:
            raise ValueError('launchd_count_limit')
        for name in candidates:
            path = directory + '/' + name
            record = metadata(path)
            try:
                value = read_plist(path)
                record['configuration'] = {key: selected(value[key]) if key in value else
                                           {'unknown': 'missing'} for key in PLIST_KEYS}
            except Exception:
                record['configuration'] = {'unknown': 'plist_unreadable_or_over_limit'}
            result['launchd'].append(record)
    for path in ('/private/var/db/com.apple.xpc.launchd/disabled.plist',
                 '/private/var/db/com.apple.xpc.launchd/disabled.501.plist',
                 '/private/var/db/launchd.db/com.apple.launchd/overrides.plist',
                 '/private/var/db/launchd.db/com.apple.launchd.peruser.501/overrides.plist'):
        record = metadata(path)
        if record.get('exists'):
            try:
                value = read_plist(path)
                labels = [key for key in value if target(key)]
                if len(labels) > 32 or any(len(key) > 256 for key in labels):
                    raise ValueError('override_count_limit')
                record['target_overrides'] = {key: selected(value[key]) if type(value[key]) is bool else
                    {'Disabled': selected(value[key]['Disabled']) if 'Disabled' in value[key] else
                     {'unknown': 'missing'}} if isinstance(value[key], dict) else
                    {'unknown': 'unexpected_type'} for key in sorted(labels)}
                record['meaning'] = 'configuration_only; missing_target_is_not_runtime_enabled'
            except Exception:
                record['target_overrides'] = None
                record['error'] = 'plist_unreadable_or_over_limit'
        result['overrides'].append(record)
    for directory in ('/private/var/db/powerlog', '/private/var/db/Powerlog',
                      '/private/var/db/PerfPowerServices', '/private/var/mobile/Library/BatteryLife',
                      '/private/var/mobile/Library/Logs/Powerlog'):
        record = metadata(directory)
        record['entries'] = []
        record['listing_complete'] = False
        if record.get('kind') == 'directory':
            entries = names(directory)
            record['listing_complete'] = len(entries) <= MAX_ENTRIES
            for name in entries[:MAX_ENTRIES]:
                record['entries'].append(metadata(directory + '/' + name))
        result['databases'].append(record)
    if Path('/mnt/share/inspect-wifi').is_file():
        result['wifi'] = []
        for path in (
                '/private/var/preferences/SystemConfiguration/com.apple.wifi.plist',
                '/private/var/preferences/com.apple.wifi.known-networks.plist',
                '/private/var/preferences/com.apple.wifi.plist',
                '/private/var/mobile/Library/Preferences/com.apple.wifi.plist'):
            record = metadata(path)
            if record.get('exists'):
                try:
                    record['configuration'] = wifi_summary(read_plist(path))
                except Exception:
                    record['error'] = 'wifi_plist_unreadable_or_over_limit'
            result['wifi'].append(record)
        result['keychain_metadata'] = [metadata(path) for path in (
            '/private/var/Keychains/keychain-2.db',
            '/private/var/Keychains/keychain-2.db-wal',
            '/private/var/Keychains/keychain-2.db-shm')]
    return result


def emit(result):
    payload = json.dumps(result, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    if len(payload) > MAX_JSON:
        raise ValueError('json_size_limit')
    print('POWERLOG_STATE_BEGIN bytes=' + str(len(payload)) + ' sha256=' + hashlib.sha256(payload).hexdigest())
    encoded = base64.b64encode(payload).decode('ascii')
    chunks = [encoded[offset:offset + 144] for offset in range(0, len(encoded), 144)]
    for index, chunk in enumerate(chunks):
        print('POWERLOG_STATE_CHUNK ' + str(index).zfill(4) + ' ' + chunk)
    print('POWERLOG_STATE_END chunks=' + str(len(chunks)), flush=True)


if __name__ == '__main__':
    try:
        emit(collect())
    except Exception:
        print('POWERLOG_STATE_FAILED phase=collect', flush=True)
        sys.exit(1)
PY
umount /dst
trap - EXIT
echo POWERLOG_STATE_SUCCESS
