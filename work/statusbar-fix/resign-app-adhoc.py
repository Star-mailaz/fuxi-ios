#!/usr/bin/env python3
"""把已砸殼的 IPA 重簽成 ad hoc，打成 phone-readthrough.py --install-app 用的 tar。

IPA 是不可信資料：只讀 zip、不執行裡面任何東西；路徑、類型、大小先檢查，Python 請用 -I 執行。
核心的 sweet AMFI（0025／0035／0036）只驗 CodeDirectory 的分頁 hash、只解析 XML entitlements，root 上有簽章即平台
程式，沒有 trust cache。砸殼後原 App Store 簽章的分頁 hash 已失效，所以每個 Mach-O 換一個 SuperBlob：
  - 一個 SHA-256 ad hoc CodeDirectory（版本 0x20400、4K 頁、codeLimit＝簽章位置、execSeg 指向 __TEXT），
    沿用原 identifier，不帶 team ID；
  - 空 requirements（槽 2）、原 XML entitlements（槽 5）與原 DER entitlements（槽 7）原樣保留；
  - 特殊槽 -1／-3 綁該 bundle 的 Info.plist 與 _CodeSignature/CodeResources（只有 bundle 主執行檔）。
LC_CODE_SIGNATURE 的位置與大小不變、不足處補 0，所以簽章前的每個 byte 都不動（程式會核對）。
CodeDirectory 版面沿用 ksrc/tools/mkinit.py code_signature()；核對沿用 work/localbuild/verify-sb-shape.py
（UniXNU scripts/audit-target-userspace.py）的逐頁 hash 與特殊槽檢查，另寫一份不共用簽章程式碼的解析。
查過但不適用：mkinit 只會產生新檔、ios27-root.py 只算 cdhash；本機沒有 ldid／zsign。

usage: python -X utf8 -I resign-app-adhoc.py build IPA OUTDIR
       python -X utf8 -I resign-app-adhoc.py verify OUTDIR
       python -X utf8 -I resign-app-adhoc.py self-test
"""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import struct
import sys
import tarfile
import tempfile
import zipfile

PAGE_SHIFT = 12
PAGE = 1 << PAGE_SHIFT
CPU_ARM64 = 0x0100000c
MH_EXECUTE, MH_DYLIB, MH_BUNDLE = 2, 6, 8
LC_SEGMENT_64, LC_CODE_SIGNATURE, LC_ENCRYPTION_INFO_64 = 0x19, 0x1d, 0x2c
SUPERBLOB, CODEDIRECTORY, REQUIREMENTS = 0xfade0cc0, 0xfade0c02, 0xfade0c01
ENTITLEMENTS, DER_ENTITLEMENTS = 0xfade7171, 0xfade7172
EMPTY_REQUIREMENTS = struct.pack('>III', REQUIREMENTS, 12, 0)
MAX_TOTAL, MAX_FILE, MAX_ENTRIES, MAX_ENTITLEMENTS = 1 << 30, 512 << 20, 20000, 64 << 10
DIR_MODE, EXEC_MODE, FILE_MODE = 0o755, 0o755, 0o644


def require(condition, message):
    if not condition:
        raise ValueError(message)


# ---------------------------------------------------------------- 簽章 ----

def macho_layout(data):
    """thin arm64 Mach-O 的簽章位置、__TEXT 與 filetype；不合要求就拒絕。"""
    require(len(data) >= 32, 'truncated Mach-O header')
    magic, cpu, subtype, filetype, ncmds, sizeofcmds = struct.unpack_from('<6I', data)
    require(magic == 0xfeedfacf and cpu == CPU_ARM64 and subtype & 0xffffff == 0,
            'only thin plain arm64 Mach-O is supported')
    require(filetype in (MH_EXECUTE, MH_DYLIB, MH_BUNDLE), f'unexpected Mach-O file type {filetype}')
    end = 32 + sizeofcmds
    require(end <= len(data) and ncmds <= sizeofcmds // 8, 'invalid load command bounds')
    offset, signature, text, linkedit, cryptid = 32, None, None, None, None
    for _ in range(ncmds):
        command, size = struct.unpack_from('<II', data, offset)
        require(size >= 8 and size % 8 == 0 and offset + size <= end, 'invalid load command')
        if command == LC_SEGMENT_64:
            require(size >= 72, 'truncated segment')
            name = data[offset + 8:offset + 24].split(b'\0', 1)[0]
            fileoff, filesize = struct.unpack_from('<2Q', data, offset + 40)
            require(fileoff + filesize <= len(data), 'segment outside file')
            if name == b'__TEXT':
                require(text is None, 'duplicate __TEXT')
                text = (fileoff, filesize)
            elif name == b'__LINKEDIT':
                require(linkedit is None, 'duplicate __LINKEDIT')
                linkedit = (fileoff, filesize)
        elif command == LC_CODE_SIGNATURE:
            require(size == 16 and signature is None, 'invalid code signature command')
            signature = struct.unpack_from('<II', data, offset + 8)
        elif command == LC_ENCRYPTION_INFO_64:
            require(size >= 24 and cryptid is None, 'invalid encryption info')
            cryptid = struct.unpack_from('<I', data, offset + 16)[0]
        offset += size
    require(offset == end, 'load commands do not fill sizeofcmds')
    require(signature is not None and text is not None and linkedit is not None,
            'needs __TEXT, __LINKEDIT and LC_CODE_SIGNATURE')
    require(cryptid in (None, 0), 'binary is still encrypted (cryptid != 0)')
    sig_off, sig_size = signature
    require(sig_off >= end and sig_off % 16 == 0 and sig_off + sig_size == len(data) and
            linkedit[0] + linkedit[1] == len(data) and linkedit[0] <= sig_off,
            'code signature must end __LINKEDIT and the file')
    return {'filetype': filetype, 'sig_off': sig_off, 'sig_size': sig_size, 'text': text}


def superblob_slots(blob):
    """SuperBlob 的 {type: leaf bytes}，逐項檢查邊界。"""
    require(len(blob) >= 12, 'truncated signature')
    magic, length, count = struct.unpack_from('>3I', blob)
    require(magic == SUPERBLOB and 12 + 8 * count <= length <= len(blob), 'invalid SuperBlob')
    slots = {}
    for index in range(count):
        kind, start = struct.unpack_from('>2I', blob, 12 + 8 * index)
        require(12 + 8 * count <= start and start + 8 <= length and kind not in slots, 'invalid SuperBlob slot')
        size = struct.unpack_from('>I', blob, start + 4)[0]
        require(8 <= size and start + size <= length, 'SuperBlob leaf outside the blob')
        slots[kind] = blob[start:start + size]
    return slots


def old_signature(data, layout):
    """原簽章裡要保留的：identifier、XML 與 DER entitlements。"""
    slots = superblob_slots(data[layout['sig_off']:layout['sig_off'] + layout['sig_size']])
    directory = slots.get(0)
    require(directory is not None and struct.unpack_from('>I', directory)[0] == CODEDIRECTORY,
            'original signature has no code directory')
    ident_off = struct.unpack_from('>I', directory, 20)[0]
    require(44 <= ident_off < len(directory) and b'\0' in directory[ident_off:], 'invalid original identifier')
    identifier = directory[ident_off:].split(b'\0', 1)[0]
    require(re.fullmatch(rb'[A-Za-z0-9._-]{1,255}', identifier), 'unexpected original identifier')
    xml = slots.get(5)
    der = slots.get(7)
    if xml is not None:
        require(struct.unpack_from('>I', xml)[0] == ENTITLEMENTS and len(xml) <= MAX_ENTITLEMENTS,
                'invalid XML entitlements')
        require(isinstance(plistlib.loads(xml[8:]), dict), 'XML entitlements are not a dictionary')
    if der is not None:
        require(struct.unpack_from('>I', der)[0] == DER_ENTITLEMENTS and len(der) <= MAX_ENTITLEMENTS,
                'invalid DER entitlements')
    return identifier, xml, der


def code_directory(data, layout, identifier, specials):
    """mkinit.py code_signature() 的版面：版本 0x20400、CS_ADHOC、SHA-256、4K 頁。"""
    limit = layout['sig_off']
    hashes = b''.join(hashlib.sha256(data[o:min(o + PAGE, limit)]).digest() for o in range(0, limit, PAGE))
    nspecial = len(specials)
    special = b''.join(specials[index - 1] for index in range(nspecial, 0, -1))
    ident = identifier + b'\0'
    ident_off = 88
    hash_off = ident_off + len(ident) + 32 * nspecial
    length = hash_off + len(hashes)
    text_off, text_size = layout['text']
    flags = 1 if layout['filetype'] == MH_EXECUTE else 0             # CS_EXECSEG_MAIN_BINARY
    cd = struct.pack('>9I4BI', CODEDIRECTORY, length, 0x20400, 0x2,      # CS_ADHOC
                     hash_off, ident_off, nspecial, len(hashes) // 32, limit,
                     32, 2, 0, PAGE_SHIFT, 0)
    cd += struct.pack('>III', 0, 0, 0)                                # scatter, team, spare3
    cd += struct.pack('>QQQQ', 0, text_off, text_size, flags)         # codeLimit64, execSeg
    assert len(cd) == ident_off
    return cd + ident + special + hashes


def sign(data, info_plist=None, resources=None):
    """回傳重簽後的 Mach-O；簽章前的 bytes 與檔案長度都不變。"""
    layout = macho_layout(data)
    identifier, xml, der = old_signature(data, layout)
    zero = bytes(32)
    specials = [hashlib.sha256(info_plist).digest() if info_plist is not None else zero,
                hashlib.sha256(EMPTY_REQUIREMENTS).digest(),
                hashlib.sha256(resources).digest() if resources is not None else zero,
                zero,
                hashlib.sha256(xml).digest() if xml is not None else zero,
                zero,
                hashlib.sha256(der).digest() if der is not None else zero]
    used = max([2] + [index + 1 for index, value in enumerate(specials) if value != zero])
    leaves = [(0, code_directory(data, layout, identifier, specials[:used])), (2, EMPTY_REQUIREMENTS)]
    leaves += [(5, xml)] if xml is not None else []
    leaves += [(7, der)] if der is not None else []
    header = 12 + 8 * len(leaves)
    index, body, position = b'', b'', header
    for kind, leaf in leaves:
        index += struct.pack('>II', kind, position)
        body += leaf
        position += len(leaf)
    blob = struct.pack('>3I', SUPERBLOB, position, len(leaves)) + index + body
    require(len(blob) <= layout['sig_size'], 'new signature does not fit the existing LC_CODE_SIGNATURE space')
    signed = data[:layout['sig_off']] + blob + bytes(layout['sig_size'] - len(blob))
    assert len(signed) == len(data) and signed[:layout['sig_off']] == data[:layout['sig_off']]
    return signed


def verify(data, info_plist=None, resources=None):
    """獨立核對（不用 sign() 的程式碼）：逐頁 hash、特殊槽、execSeg 與 ad hoc 旗標。"""
    require(len(data) >= 32 and struct.unpack_from('<I', data)[0] == 0xfeedfacf, 'not a 64-bit Mach-O')
    filetype, ncmds, sizeofcmds = struct.unpack_from('<3I', data, 12)
    offset, sig, text = 32, None, None
    for _ in range(ncmds):
        command, size = struct.unpack_from('<II', data, offset)
        require(8 <= size and offset + size <= 32 + sizeofcmds, 'bad load command')
        if command == LC_CODE_SIGNATURE:
            sig = struct.unpack_from('<II', data, offset + 8)
        elif command == LC_SEGMENT_64 and data[offset + 8:offset + 24].rstrip(b'\0') == b'__TEXT':
            text = struct.unpack_from('<2Q', data, offset + 40)
        offset += size
    require(sig is not None and text is not None and sig[0] + sig[1] <= len(data), 'no signature')
    blob = data[sig[0]:sig[0] + sig[1]]
    magic, length, count = struct.unpack_from('>3I', blob)
    require(magic == SUPERBLOB and length <= len(blob) and not any(blob[length:]), 'bad SuperBlob or padding')
    leaves = {}
    for index in range(count):
        kind, start = struct.unpack_from('>2I', blob, 12 + 8 * index)
        size = struct.unpack_from('>I', blob, start + 4)[0]
        require(start + size <= length and kind not in leaves, 'bad leaf')
        leaves[kind] = blob[start:start + size]
    require(set(leaves) <= {0, 2, 5, 7} and 0 in leaves and leaves.get(2) == EMPTY_REQUIREMENTS,
            'unexpected signature leaves')
    cd = leaves[0]
    (magic, size, version, flags, hash_off, ident_off, nspecial, nslots, limit,
     hash_size, hash_type, platform, page_shift, _) = struct.unpack_from('>9I4BI', cd)
    require(magic == CODEDIRECTORY and size == len(cd) and version == 0x20400 and flags == 0x2 and
            hash_size == 32 and hash_type == 2 and page_shift == PAGE_SHIFT, 'not a SHA-256 ad hoc directory')
    require(limit == sig[0] and nslots == (limit + PAGE - 1) // PAGE and
            hash_off + 32 * nslots == len(cd) and hash_off - 32 * nspecial >= ident_off, 'bad code bounds')
    team_off = struct.unpack_from('>I', cd, 48)[0]
    exec_base, exec_limit, exec_flags = struct.unpack_from('>3Q', cd, 64)
    require(team_off == 0 and (exec_base, exec_limit) == tuple(text) and
            exec_flags == (1 if filetype == MH_EXECUTE else 0), 'bad team or execSeg fields')
    for page in range(nslots):
        expected = cd[hash_off + 32 * page:hash_off + 32 * (page + 1)]
        require(hashlib.sha256(data[page * PAGE:min((page + 1) * PAGE, limit)]).digest() == expected,
                f'code page {page} hash mismatch')
    sources = {1: info_plist, 2: leaves[2], 3: resources, 5: leaves.get(5), 7: leaves.get(7)}
    for slot in range(1, nspecial + 1):
        value = sources.get(slot)
        expected = hashlib.sha256(value).digest() if value is not None else bytes(32)
        require(cd[hash_off - 32 * slot:hash_off - 32 * (slot - 1)] == expected, f'special slot -{slot} mismatch')
    for slot in (5, 7):
        require(slot not in leaves or nspecial >= slot, f'entitlement slot {slot} not bound')
    identifier = cd[ident_off:].split(b'\0', 1)[0].decode('ascii')
    entitlements = sorted(plistlib.loads(leaves[5][8:])) if 5 in leaves else []
    return {'identifier': identifier, 'pages': nslots, 'special_slots': nspecial,
            'cdhash': hashlib.sha256(cd).hexdigest()[:40], 'entitlements': entitlements,
            'der_entitlements': 7 in leaves}


# ---------------------------------------------------------------- IPA ----

def is_macho(data):
    return len(data) >= 4 and data[:4] in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe',
                                           b'\xbe\xba\xfe\xca', b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce')


def read_ipa(path):
    """{bundle 內相對路徑: bytes 或 None（目錄）} 與 App 名稱；拒絕路徑穿越、連結、怪類型與過大的內容。"""
    archive = zipfile.ZipFile(path)
    infos = archive.infolist()
    require(0 < len(infos) <= MAX_ENTRIES, 'unexpected IPA entry count')
    require(sum(info.file_size for info in infos) <= MAX_TOTAL, 'IPA expands beyond 1 GiB')
    apps = set()
    for info in infos:
        parts = info.filename.split('/')
        require(parts[0] == 'Payload', 'IPA entry outside Payload/')
        if len(parts) > 2 or (len(parts) == 2 and parts[1]):
            apps.add(parts[1])
    require(len(apps) == 1, 'IPA must hold exactly one app')
    app = apps.pop()
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.app', app), 'unexpected app bundle name')
    entries, folded = {}, set()
    for info in infos:
        name = info.filename
        require('\\' not in name and '\0' not in name and not name.startswith('/'), 'unsafe IPA path')
        kind = stat.S_IFMT(info.external_attr >> 16)
        require(kind in (0, stat.S_IFREG, stat.S_IFDIR), 'IPA holds a link or special file')
        if name in ('Payload/', f'Payload/{app}', f'Payload/{app}/'):
            continue
        require(name.startswith(f'Payload/{app}/'), 'IPA entry outside the app bundle')
        relative = name[len(f'Payload/{app}/'):]
        is_dir = relative.endswith('/') or kind == stat.S_IFDIR
        relative = relative.rstrip('/')
        parts = relative.split('/')
        require(all(part not in ('', '.', '..') and len(part.encode('utf-8')) <= 255 for part in parts),
                'unsafe IPA path component')
        require(len(relative.encode('utf-8')) <= 900, 'IPA path too long')
        key = relative.casefold()
        require(key not in folded, 'IPA holds names that differ only in case')
        folded.add(key)
        if is_dir:
            require(info.file_size == 0, 'directory entry with data')
            entries[relative] = None
        else:
            require(info.file_size <= MAX_FILE, 'IPA file too large')
            data = archive.read(info)
            require(len(data) == info.file_size, 'IPA file size differs')
            entries[relative] = data
    for relative in list(entries):
        parent = PurePosixPath(relative).parent
        while str(parent) != '.':
            require(entries.get(str(parent), None) is None, 'file used as a directory')
            entries.setdefault(str(parent), None)
            parent = parent.parent
    return app, entries


def bundle_inputs(entries, relative):
    """主執行檔才綁 Info.plist（-1）與 CodeResources（-3）。"""
    parent = PurePosixPath(relative).parent
    base = '' if str(parent) == '.' else str(parent) + '/'
    info = entries.get(base + 'Info.plist')
    if info is None:
        return None, None
    try:
        executable = plistlib.loads(info).get('CFBundleExecutable')
    except Exception as error:
        raise ValueError(f'unreadable Info.plist for {relative}') from error
    if executable != PurePosixPath(relative).name:
        return None, None
    return info, entries.get(base + '_CodeSignature/CodeResources')


def build(ipa, output):
    output = Path(output).resolve()
    require(not output.exists(), 'output must be a new directory')
    app, entries = read_ipa(ipa)
    signed, report = {}, []
    for relative, data in sorted(entries.items()):
        if data is None or not is_macho(data):
            continue
        info, resources = bundle_inputs(entries, relative)
        new = sign(data, info, resources)
        result = verify(new, info, resources)
        result.update(path=relative, size=len(new), sha256_before=hashlib.sha256(data).hexdigest(),
                      sha256=hashlib.sha256(new).hexdigest(), bundle_main=info is not None)
        signed[relative] = new
        report.append(result)
    main = plistlib.loads(entries['Info.plist'])
    require(main.get('CFBundleExecutable') in signed, 'main executable missing or not Mach-O')
    output.mkdir(parents=False)
    files = []
    with tarfile.open(output / 'app.tar', 'w', format=tarfile.PAX_FORMAT, encoding='utf-8') as archive:
        root = tarfile.TarInfo(app)
        root.type, root.mode = tarfile.DIRTYPE, DIR_MODE
        members = [(root, None)]
        for relative, data in sorted(entries.items()):
            item = tarfile.TarInfo(f'{app}/{relative}')
            if data is None:
                item.type, item.mode = tarfile.DIRTYPE, DIR_MODE
            else:
                data = signed.get(relative, data)
                item.size = len(data)
                item.mode = EXEC_MODE if relative in signed else FILE_MODE
                files.append((hashlib.sha256(data).hexdigest(), f'{app}/{relative}', item.mode))
            members.append((item, data))
        for item, data in members:
            item.uid = item.gid = 0
            item.uname, item.gname = 'root', 'wheel'
            item.mtime = 1700000000
            archive.addfile(item, io.BytesIO(data) if data is not None else None)
    (output / 'files.sha256').write_text(''.join(f'{digest} {mode:o} {name}\n' for digest, name, mode in files),
                                         encoding='utf-8', newline='\n')
    manifest = {'schema': 'fuxi-adhoc-app-v1', 'app': app, 'bundle_identifier': main.get('CFBundleIdentifier'),
                'executable': main.get('CFBundleExecutable'), 'version': main.get('CFBundleShortVersionString'),
                'minimum_os': main.get('MinimumOSVersion'), 'source_ipa_sha256': sha256_file(Path(ipa)),
                'files': len(files), 'directories': sum(1 for value in entries.values() if value is None) + 1,
                'bytes': sum(len(signed.get(name, data)) for name, data in entries.items() if data is not None),
                'machos': report,
                'verification': 'ad hoc page and special-slot hashes; no Apple certificate trust claim'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
                                          encoding='utf-8', newline='\n')
    (output / 'SHA256SUMS').write_text(''.join(f'{sha256_file(output / name)}  {name}\n'
                                               for name in ('app.tar', 'files.sha256', 'manifest.json')),
                                       encoding='ascii', newline='\n')
    check(output)
    return manifest


def sha256_file(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check(output):
    """重讀產物：SHA256SUMS、tar 內容與 files.sha256 一致，每個 Mach-O 重新核對。"""
    output = Path(output)
    sums = {}
    for line in (output / 'SHA256SUMS').read_text(encoding='ascii').splitlines():
        digest, name = line.split('  ', 1)
        require(sha256_file(output / name) == digest, f'{name} differs from SHA256SUMS')
        sums[name] = digest
    require(set(sums) == {'app.tar', 'files.sha256', 'manifest.json'}, 'unexpected SHA256SUMS entries')
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    app = manifest['app']
    expected = {}
    for line in (output / 'files.sha256').read_text(encoding='utf-8').splitlines():
        digest, mode, name = line.split(' ', 2)
        expected[name] = (digest, int(mode, 8))
    contents, dirs = {}, 0
    with tarfile.open(output / 'app.tar', 'r:', encoding='utf-8') as archive:
        for item in archive:
            require(item.name == app or item.name.startswith(app + '/'), 'tar member outside the app')
            require(item.uid == 0 and item.gid == 0, 'tar member not root:wheel')
            if item.isdir():
                require(item.mode == DIR_MODE, 'unexpected directory mode')
                dirs += 1
                continue
            require(item.isfile() and item.mode in (EXEC_MODE, FILE_MODE), 'unexpected tar member type or mode')
            contents[item.name] = (archive.extractfile(item).read(), item.mode)
    require(set(contents) == set(expected) and len(contents) == manifest['files'] and dirs == manifest['directories'],
            'tar members differ from files.sha256')
    for name, (data, mode) in contents.items():
        require((hashlib.sha256(data).hexdigest(), mode) == expected[name], f'{name} differs from files.sha256')

    def bundle_file(relative, leaf):
        parent = PurePosixPath(relative).parent
        key = f'{app}/{leaf}' if str(parent) == '.' else f'{app}/{parent}/{leaf}'
        return contents[key][0] if key in contents else None

    for entry in manifest['machos']:
        data = contents[f"{app}/{entry['path']}"][0]
        info = bundle_file(entry['path'], 'Info.plist') if entry['bundle_main'] else None
        resources = bundle_file(entry['path'], '_CodeSignature/CodeResources') if entry['bundle_main'] else None
        result = verify(data, info, resources)
        require(result['cdhash'] == entry['cdhash'] and contents[f"{app}/{entry['path']}"][1] == EXEC_MODE,
                f"{entry['path']} signature differs from the manifest")
    return manifest


# ---------------------------------------------------------- self-test ----

def fixture_macho(filetype=MH_EXECUTE, cryptid=0, sig_size=0x2000, identifier=b'com.example.fixture',
                  entitlements=b'<?xml version="1.0"?><plist version="1.0"><dict><key>a</key><true/></dict></plist>'):
    """__TEXT（0x4000）＋__LINKEDIT（0x100＋簽章）＋LC_CODE_SIGNATURE，舊簽章帶假的 SHA-1 CD 與 XML／DER entitlements。"""
    text_size, sig_off = 0x4000, 0x4100
    commands = [
        struct.pack('<II16sQQQQiiII', LC_SEGMENT_64, 72, b'__TEXT', 0x100000000, text_size, 0, text_size, 5, 5, 0, 0),
        struct.pack('<II16sQQQQiiII', LC_SEGMENT_64, 72, b'__LINKEDIT', 0x100000000 + text_size, 0x4000,
                    text_size, sig_off - text_size + sig_size, 1, 1, 0, 0),
        struct.pack('<IIIIII', LC_ENCRYPTION_INFO_64, 24, 0x4000, 0, cryptid, 0),
        struct.pack('<IIII', LC_CODE_SIGNATURE, 16, sig_off, sig_size)]
    body = b''.join(commands)
    image = bytearray(sig_off)
    image[:32 + len(body)] = struct.pack('<8I', 0xfeedfacf, CPU_ARM64, 0, filetype, len(commands), len(body), 0, 0) + body
    for position in range(0x1000, text_size, 7):
        image[position] = position * 31 & 0xff
    old_cd = struct.pack('>9I4BI', CODEDIRECTORY, 0, 0x20400, 0, 0, 44, 0, 0, 0, 20, 1, 0, 12, 0) + identifier + b'\0'
    old_cd = old_cd[:4] + struct.pack('>I', len(old_cd)) + old_cd[8:]
    leaves = [(0, old_cd)]
    if entitlements is not None:
        leaves += [(5, struct.pack('>II', ENTITLEMENTS, 8 + len(entitlements)) + entitlements),
                   (7, struct.pack('>II', DER_ENTITLEMENTS, 12) + b'\x70\x02\x01\x01')]
    position = 12 + 8 * len(leaves)
    index, data = b'', b''
    for kind, leaf in leaves:
        index += struct.pack('>II', kind, position)
        data += leaf
        position += len(leaf)
    blob = struct.pack('>3I', SUPERBLOB, position, len(leaves)) + index + data
    return bytes(image) + blob + bytes(sig_size - len(blob))


def refused(function, *values):
    try:
        function(*values)
    except (ValueError, struct.error, KeyError, zipfile.BadZipFile):
        return True
    return False


def fixture_ipa(path, entries, links=()):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, 'target')


def self_test():
    info = plistlib.dumps({'CFBundleExecutable': 'Fixture', 'CFBundleIdentifier': 'com.example.fixture',
                           'MinimumOSVersion': '16.0'})
    resources = b'<plist>resources</plist>'
    original = fixture_macho()
    signed = sign(original, info, resources)
    result = verify(signed, info, resources)
    require(signed[:0x4100] == original[:0x4100] and len(signed) == len(original), 'signing changed code bytes')
    require(result['identifier'] == 'com.example.fixture' and result['pages'] == 5 and
            result['special_slots'] == 7 and result['entitlements'] == ['a'] and result['der_entitlements'],
            'signed fixture differs')
    require(sign(signed, info, resources) == signed, 'signing is not idempotent')
    library = sign(fixture_macho(MH_DYLIB, entitlements=None))
    require(verify(library)['special_slots'] == 2 and verify(library)['entitlements'] == [], 'library fixture differs')
    for position in (0x10, 0x1000, 0x40ff):
        changed = bytearray(signed)
        changed[position] ^= 1
        require(refused(verify, bytes(changed), info, resources), f'flipped byte {position:#x} accepted')
    require(refused(verify, signed, info + b' ', resources), 'changed Info.plist accepted')
    require(refused(verify, signed, info, None), 'missing CodeResources accepted')
    require(refused(verify, signed[:-1] + b'\1', info, resources), 'dirty signature padding accepted')
    for bad in (fixture_macho(cryptid=1), fixture_macho(sig_size=0x100), original[:0x4000],
                b'\xca\xfe\xba\xbe' + original[4:], fixture_macho(identifier=b'bad id')):
        require(refused(sign, bad), 'invalid Mach-O accepted for signing')
    with tempfile.TemporaryDirectory(prefix='fuxi-resign-') as temporary:
        directory = Path(temporary)
        app = 'Payload/Fixture.app/'
        good = {app + 'Info.plist': info, app + 'Fixture': original, app + '_CodeSignature/CodeResources': resources,
                app + 'Frameworks/Lib.framework/Lib': fixture_macho(MH_DYLIB, entitlements=None),
                app + 'Frameworks/Lib.framework/Info.plist': plistlib.dumps({'CFBundleExecutable': 'Lib'}),
                app + 'Assets.car': b'not code', app + '完整版': b''}
        fixture_ipa(directory / 'good.ipa', good)
        manifest = build(directory / 'good.ipa', directory / 'out')
        require(manifest['files'] == 7 and len(manifest['machos']) == 2 and
                {entry['path']: entry['bundle_main'] for entry in manifest['machos']} ==
                {'Fixture': True, 'Frameworks/Lib.framework/Lib': True}, 'built fixture manifest differs')
        require(check(directory / 'out')['app'] == 'Fixture.app', 'built fixture does not re-verify')
        require(refused(build, directory / 'good.ipa', directory / 'out'), 'existing output reused')
        with tarfile.open(directory / 'out/app.tar') as archive:
            modes = {item.name: item.mode for item in archive}
        require(modes['Fixture.app/Fixture'] == 0o755 and modes['Fixture.app/Assets.car'] == 0o644 and
                modes['Fixture.app/Frameworks'] == 0o755 and 'Fixture.app/完整版' in modes, 'tar modes differ')
        (directory / 'out/files.sha256').write_text('0' * 64 + ' 644 Fixture.app/Assets.car\n', encoding='utf-8')
        require(refused(check, directory / 'out'), 'tampered output accepted')
        bad_sets = [({**good, 'Payload/Other.app/x': b''}, ()), ({**good, app + '../x': b''}, ()),
                    ({**good, app + 'a/./b': b''}, ()), ({**good, app + 'assets.CAR': b''}, ()),
                    ({**good, 'outside': b''}, ()), (good, (app + 'link',)),
                    ({key: value for key, value in good.items() if not key.endswith('/Fixture')}, ()),
                    ({**good, app + 'Fixture': fixture_macho(cryptid=1)}, ())]
        for number, (entries, links) in enumerate(bad_sets):
            fixture_ipa(directory / f'bad{number}.ipa', entries, links)
            require(refused(build, directory / f'bad{number}.ipa', directory / f'bad-out{number}'),
                    f'unsafe IPA {number} accepted')
    print('PASS ad hoc re-sign: page/special-slot hashes, unchanged code bytes, refusals, IPA path checks, tar modes')


def main(argv):
    if argv[1:] == ['self-test']:
        self_test()
    elif len(argv) == 4 and argv[1] == 'build':
        manifest = build(argv[2], argv[3])
        print(json.dumps({key: manifest[key] for key in ('app', 'bundle_identifier', 'version', 'files', 'bytes')},
                         ensure_ascii=False))
        print('MACHOS', len(manifest['machos']), 'PAGES', sum(entry['pages'] for entry in manifest['machos']))
    elif len(argv) == 3 and argv[1] == 'verify':
        manifest = check(argv[2])
        print('VERIFIED', manifest['app'], manifest['files'], 'files', len(manifest['machos']), 'Mach-O')
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    try:
        main(sys.argv)
    except ValueError as error:
        raise SystemExit(f'REFUSED: {error}') from error
