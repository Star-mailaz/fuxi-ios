#!/usr/bin/env python3
"""000 第三方 App 安裝（guest 端）：把 resign-app-adhoc.py 產生的 tar（唯讀磁碟 /dev/vdc）解進 /Applications，
當成不加沙盒的系統 App；appex 補進 launchd.plist 的 AppExtensions 快取，再刪 LaunchServices 資料庫讓 lsd 開機重建。
後兩步復用 ksrc/tools/sweet-root-tweaks.py 的 app_extensions()／save()／rebuild_launchservices()（內建 App 模式
--install-staged-apps 已上機用過），這裡只多做 tar 檢查與逐檔核對。
不覆蓋：同名目錄、同 bundle ID 的 App／placeholder／已裝容器 App 一律拒絕；桌面配置 IconState 由外框核對不變。
解開時先寫進 /Applications/.<名稱>.fuxi-partial，逐檔 SHA-256 與權限核對完才改名；失敗時整個 overlay 不寫回手機。

usage: install-app-guest.py install ROOT DEVICE SHARE      （guest，root 執行）
       install-app-guest.py self-test TWEAKS                （主機測試，WSL root 執行）
"""
import hashlib
import importlib.util
import io
import os
import plistlib
import re
import sys
import tarfile
import tempfile

DIR_MODE, EXEC_MODE, FILE_MODE = 0o755, 0o755, 0o644
CHUNK = 8 << 20
MARGIN = 64 << 20


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_tweaks(path):
    spec = importlib.util.spec_from_file_location('sweet_root_tweaks', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_inputs(share):
    lines = open(os.path.join(share, 'app.txt'), encoding='ascii').read().split('\n')
    require(len(lines) == 5 and lines[4] == '', 'app.txt must hold four lines')
    name, bundle_id, size, digest = lines[:4]
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.app', name), 'unexpected app name')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,127}', bundle_id), 'unexpected bundle identifier')
    require(re.fullmatch(r'[1-9][0-9]{0,10}', size) and int(size) % 512 == 0, 'unexpected tar size')
    require(re.fullmatch(r'[0-9a-f]{64}', digest), 'unexpected tar hash')
    expected = {}
    for line in open(os.path.join(share, 'files.sha256'), encoding='utf-8').read().splitlines():
        file_digest, mode, path = line.split(' ', 2)
        require(re.fullmatch(r'[0-9a-f]{64}', file_digest) and mode in ('644', '755'), 'bad files.sha256 line')
        require(path.startswith(name + '/') and path not in expected, 'bad files.sha256 path')
        expected[path] = (file_digest, int(mode, 8))
    require(expected, 'files.sha256 is empty')
    return name, bundle_id, int(size), digest, expected


def device_digest(device, size):
    digest = hashlib.sha256()
    with open(device, 'rb') as stream:
        left = size
        while left:
            chunk = stream.read(min(CHUNK, left))
            require(chunk, 'device shorter than the tar')
            digest.update(chunk)
            left -= len(chunk)
    return digest.hexdigest()


def bundle_ids(root):
    """已存在的 bundle ID：/Applications、AppPlaceholders（含停放的）、已裝容器 App。"""
    patterns = ('Applications/*.app', 'System/Library/AppPlaceholders/*.app',
                'System/Library/AppPlaceholders.fuxi-staged/*.app',
                'private/var/containers/Bundle/Application/*/*.app')
    import glob
    found, unreadable = {}, 0
    for pattern in patterns:
        for app in glob.glob(os.path.join(root, pattern)):
            info = os.path.join(app, 'Info.plist')
            if not os.path.isfile(info):
                continue
            try:
                with open(info, 'rb') as stream:
                    identifier = plistlib.load(stream).get('CFBundleIdentifier')
            except Exception:
                unreadable += 1
                continue
            if isinstance(identifier, str):
                found.setdefault(identifier, app[len(root):])
    return found, unreadable


def extract(device, size, name, expected, partial):
    """逐成員檢查後寫進 partial；回傳（檔案數、目錄數、bytes）。"""
    files = dirs = total = 0
    seen, seen_root = set(), False
    with open(device, 'rb') as raw:
        with tarfile.open(fileobj=raw, mode='r:', encoding='utf-8') as archive:
            for member in archive:
                require(member.offset_data + max(member.size, 0) <= size, 'tar member beyond the verified size')
                path = member.name
                require(path == name or path.startswith(name + '/'), 'tar member outside the app')
                parts = path.split('/')
                require(all(part not in ('', '.', '..') for part in parts), 'unsafe tar path')
                require(member.uid == 0 and member.gid == 0, 'tar member not root:wheel')
                if path == name:
                    # App 根目錄就是預先建好的 partial，只核對類型與權限。
                    require(member.isdir() and member.mode == DIR_MODE and not seen_root, 'bad app root member')
                    seen_root = True
                    continue
                target = partial + path[len(name):]
                require(not os.path.lexists(target), 'tar member repeated')
                require(os.path.isdir(os.path.dirname(target)) and not os.path.islink(os.path.dirname(target)),
                        'tar member before its directory')
                if member.isdir():
                    require(member.mode == DIR_MODE, 'unexpected directory mode')
                    os.mkdir(target, DIR_MODE)
                    os.chown(target, 0, 0)
                    os.chmod(target, DIR_MODE)
                    dirs += 1
                    continue
                require(member.isfile(), 'tar holds a link or special file')
                require(path in expected and expected[path][1] == member.mode, 'tar member differs from files.sha256')
                digest = hashlib.sha256()
                source = archive.extractfile(member)
                with open(target, 'xb') as stream:
                    while True:
                        chunk = source.read(CHUNK)
                        if not chunk:
                            break
                        digest.update(chunk)
                        stream.write(chunk)
                require(digest.hexdigest() == expected[path][0], f'{path} hash differs')
                os.chown(target, 0, 0)
                os.chmod(target, member.mode)
                seen.add(path)
                files += 1
                total += member.size
    require(seen_root and seen == set(expected), 'tar files differ from files.sha256')
    return files, dirs, total


def recheck(final, name, expected):
    """改名後重走一遍：檔案集合、內容、擁有者、權限與 files.sha256 完全一致，沒有連結或多餘檔案。"""
    found = set()
    for directory, subdirs, names in os.walk(final):
        info = os.lstat(directory)
        require(info.st_uid == 0 and info.st_gid == 0 and info.st_mode & 0o7777 == DIR_MODE and
                not os.path.islink(directory), f'{directory} owner or mode differs')
        for leaf in names:
            path = os.path.join(directory, leaf)
            info = os.lstat(path)
            relative = name + path[len(final):]
            require(relative in expected and not os.path.islink(path), f'unexpected file {relative}')
            digest = hashlib.sha256()
            with open(path, 'rb') as stream:
                for chunk in iter(lambda: stream.read(CHUNK), b''):
                    digest.update(chunk)
            require((digest.hexdigest(), info.st_mode & 0o7777) == expected[relative] and
                    info.st_uid == 0 and info.st_gid == 0, f'{relative} differs after install')
            found.add(relative)
    require(found == set(expected), 'installed files differ from files.sha256')


def install(root, device, share, tweaks=None):
    name, bundle_id, size, digest, expected = read_inputs(share)
    tweaks = tweaks or load_tweaks(os.path.join(share, 'sweet-root-tweaks.py'))
    applications = os.path.join(root, 'Applications')
    final = os.path.join(applications, name)
    partial = os.path.join(applications, '.' + name + '.fuxi-partial')
    launchd = os.path.join(root, 'System/Library/xpc/launchd.plist')
    require(os.path.isdir(applications) and os.path.isfile(launchd), 'root has no /Applications or launchd.plist')
    require(not os.path.lexists(final) and not os.path.lexists(partial), f'{name} already present')
    ids, unreadable = bundle_ids(root)
    require(bundle_id not in ids, f'bundle identifier already used by {ids.get(bundle_id)}')
    print('BUNDLE_IDS_CHECKED', len(ids), 'unreadable', unreadable)
    stale = [key for key in tweaks.load(launchd).get('AppExtensions', {}) if key.startswith(f'/Applications/{name}/')]
    require(not stale, f'extension cache already has {len(stale)} entries for {name}')
    vfs = os.statvfs(root)
    free = vfs.f_bavail * vfs.f_frsize
    require(free >= size + MARGIN, f'only {free} bytes free')
    print('FREE_BYTES_BEFORE', free)
    require(device_digest(device, size) == digest, 'tar on the device differs from app.txt')
    print('TAR_VERIFIED', size)
    os.mkdir(partial, DIR_MODE)
    os.chown(partial, 0, 0)
    os.chmod(partial, DIR_MODE)
    files, dirs, total = extract(device, size, name, expected, partial)
    os.rename(partial, final)
    recheck(final, name, expected)
    print('APP_INSTALLED', name, 'files', files, 'dirs', dirs + 1, 'bytes', total)
    info = os.lstat(launchd)
    plist = tweaks.load(launchd)
    cache = plist.setdefault('AppExtensions', {})
    added = 0
    for key, value in tweaks.app_extensions(root, '/Applications/' + name):
        require(key not in cache, f'extension cache already has {key}')
        cache[key] = value
        added += 1
    tweaks.save(launchd, plist, info.st_uid, info.st_gid, info.st_mode & 0o7777)
    after = os.lstat(launchd)
    require((after.st_uid, after.st_gid, after.st_mode & 0o7777) == (info.st_uid, info.st_gid, info.st_mode & 0o7777),
            'launchd.plist owner or mode changed')
    print('EXTENSION_CACHE_ADDED', added)
    tweaks.rebuild_launchservices(root)
    import glob
    require(not glob.glob(os.path.join(root, tweaks.LS_DATABASES)), 'LaunchServices database left')
    print('INSTALL_APP_VERIFIED', name, bundle_id)


# ---------------------------------------------------------- self-test ----

def fixture_tar(path, name, entries, extra=()):
    with tarfile.open(path, 'w', format=tarfile.PAX_FORMAT, encoding='utf-8') as archive:
        items = [(name, None, DIR_MODE)] + [(f'{name}/{key}', value, mode) for key, value, mode in entries]
        for member_name, data, mode in items:
            item = tarfile.TarInfo(member_name)
            item.uid = item.gid = 0
            item.mode = mode
            if data is None:
                item.type = tarfile.DIRTYPE
            else:
                item.size = len(data)
            archive.addfile(item, io.BytesIO(data) if data is not None else None)
        for item in extra:
            archive.addfile(item)


def fixture_share(share, name, bundle_id, tar, entries, override=None):
    os.makedirs(share, exist_ok=True)
    with open(tar, 'rb') as stream:
        data = stream.read()
    lines = [name, bundle_id, str(len(data)), hashlib.sha256(data).hexdigest()]
    for index, value in (override or {}).items():
        lines[index] = value
    with open(os.path.join(share, 'app.txt'), 'w', encoding='ascii', newline='\n') as stream:
        stream.write('\n'.join(lines) + '\n')
    with open(os.path.join(share, 'files.sha256'), 'w', encoding='utf-8', newline='\n') as stream:
        for key, value, mode in entries:
            if value is not None:
                stream.write(f'{hashlib.sha256(value).hexdigest()} {mode:o} {name}/{key}\n')


def fixture_root(root, tweaks):
    for directory in ('Applications/Old.app', 'System/Library/xpc', 'System/Library/AppPlaceholders/Ph.app',
                      'private/var/mobile/Containers/Data/InternalDaemon/X/Library/Caches'):
        os.makedirs(os.path.join(root, directory))
    with open(os.path.join(root, 'Applications/Old.app/Info.plist'), 'wb') as stream:
        plistlib.dump({'CFBundleIdentifier': 'com.example.old'}, stream)
    with open(os.path.join(root, 'System/Library/AppPlaceholders/Ph.app/Info.plist'), 'wb') as stream:
        plistlib.dump({'CFBundleIdentifier': 'com.example.placeholder'}, stream)
    tweaks.save(os.path.join(root, 'System/Library/xpc/launchd.plist'),
                {'LaunchDaemons': {}, 'AppExtensions': {'/Applications/Old.app/PlugIns/A.appex': {}}}, 0, 0, 0o644)
    open(os.path.join(root, 'private/var/mobile/Containers/Data/InternalDaemon/X/Library/Caches/'
                            'com.apple.LaunchServices-1.csstore'), 'wb').close()


def refused(function, *values):
    try:
        function(*values)
    except (ValueError, KeyError, tarfile.TarError, OSError):
        return True
    return False


def self_test(tweaks_path):
    require(os.geteuid() == 0, 'self-test needs root (chown)')
    tweaks = load_tweaks(tweaks_path)
    appex_info = plistlib.dumps({'CFBundleExecutable': 'Share', 'CFBundleIdentifier': 'com.example.app.share',
                                 'NSExtension': {'NSExtensionPointIdentifier': 'com.apple.share-services'},
                                 'MinimumOSVersion': '16.0'})
    entries = [('Info.plist', plistlib.dumps({'CFBundleExecutable': 'App', 'CFBundleIdentifier': 'com.example.app'}),
                FILE_MODE),
               ('App', b'\xcf\xfa\xed\xfe' + bytes(5000), EXEC_MODE), ('PlugIns', None, DIR_MODE),
               ('PlugIns/Share.appex', None, DIR_MODE), ('PlugIns/Share.appex/Info.plist', appex_info, FILE_MODE),
               ('PlugIns/Share.appex/Share', b'\xcf\xfa\xed\xfe' + bytes(100), EXEC_MODE),
               ('完整版', b'', FILE_MODE)]
    with tempfile.TemporaryDirectory(prefix='fuxi-install-app-') as temporary:
        def case(label, tar_entries=entries, extra=(), share_entries=entries, override=None, prepare=None):
            base = os.path.join(temporary, label)
            root = os.path.join(base, 'root')
            fixture_root(root, tweaks)
            if prepare:
                prepare(root)
            tar = os.path.join(base, 'app.tar')
            fixture_tar(tar, 'App.app', tar_entries, extra)
            fixture_share(os.path.join(base, 'share'), 'App.app', 'com.example.app', tar, share_entries, override)
            return root, tar, os.path.join(base, 'share')

        root, tar, share = case('good')
        install(root, tar, share, tweaks)
        final = os.path.join(root, 'Applications/App.app')
        require(open(os.path.join(final, '完整版'), 'rb').read() == b'' and
                os.stat(os.path.join(final, 'App')).st_mode & 0o7777 == EXEC_MODE, 'installed fixture differs')
        cache = tweaks.load(os.path.join(root, 'System/Library/xpc/launchd.plist'))['AppExtensions']
        entry = cache['/Applications/App.app/PlugIns/Share.appex']
        require(entry['_executablePath'] == '/Applications/App.app/PlugIns/Share.appex/Share' and
                'MinimumOSVersion' not in entry['_infoPlist'] and '/Applications/Old.app/PlugIns/A.appex' in cache,
                'extension cache differs')
        require(not os.path.lexists(os.path.join(root, 'Applications/.App.app.fuxi-partial')), 'partial left behind')
        require(refused(install, root, tar, share, tweaks), 'second install accepted')

        link = tarfile.TarInfo('App.app/link')
        link.type, link.linkname = tarfile.SYMTYPE, '/etc/passwd'
        escape = tarfile.TarInfo('App.app/../escape')
        escape.size = 0
        wrong_owner = [(key, value, mode) for key, value, mode in entries]
        bad_cases = {
            'hash': dict(override={3: '0' * 64}),
            'size': dict(override={2: '512'}),
            'name': dict(override={0: '../App.app'}),
            'link': dict(extra=(link,)),
            'escape': dict(extra=(escape,)),
            'content': dict(share_entries=[(k, (v + b'x') if k == 'App' else v, m) for k, v, m in entries]),
            'mode': dict(share_entries=[(k, v, FILE_MODE if k == 'App' else m) for k, v, m in entries]),
            'missing': dict(share_entries=wrong_owner + [('Extra', b'1', FILE_MODE)]),
            'same-id': dict(prepare=lambda root: plistlib.dump(
                {'CFBundleIdentifier': 'com.example.app'},
                open(os.path.join(root, 'System/Library/AppPlaceholders/Ph.app/Info.plist'), 'wb'))),
            'exists': dict(prepare=lambda root: os.mkdir(os.path.join(root, 'Applications/App.app'))),
            'extension-key': dict(prepare=lambda root: tweaks.save(
                os.path.join(root, 'System/Library/xpc/launchd.plist'),
                {'AppExtensions': {'/Applications/App.app/PlugIns/Share.appex': {}}}, 0, 0, 0o644)),
        }
        for label, options in bad_cases.items():
            root, tar, share = case('bad-' + label, **options)
            require(refused(install, root, tar, share, tweaks), f'bad case {label} accepted')
            require(not os.path.lexists(os.path.join(root, 'Applications/App.app')) or label == 'exists',
                    f'bad case {label} left an installed app')
    print('PASS install-app guest: tar/hash/mode checks, refusals, extension cache, LaunchServices reset')


if __name__ == '__main__':
    if sys.argv[1:2] == ['install'] and len(sys.argv) == 5:
        install(*sys.argv[2:5])
    elif sys.argv[1:2] == ['self-test'] and len(sys.argv) == 3:
        self_test(sys.argv[2])
    else:
        raise SystemExit(__doc__)
