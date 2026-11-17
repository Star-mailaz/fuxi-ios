#!/usr/bin/env python3
"""Bounded, read-only BDF inventory; never select, extract or install board data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys


MAGIC = b'QCA-ATH12K-BOARD\0'
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_RAW_BYTES = 1024 * 1024
MAX_TLVS = 8192
MAX_RECORDS = 1024
MAX_ALIASES = 64
MAX_NAME_BYTES = 512
MAX_ELF_HEADERS = 128
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CAPTURE_LOG_BYTES = 1024 * 1024
WLAN_DIRECTORY = '/usr/local/share/fuxi/wlan'
UINT32_LIMIT = 1 << 32
FORMAT_SOURCE = 'https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/hw.h'
SELECTOR_SOURCE = 'https://github.com/torvalds/linux/blob/v6.12/drivers/net/wireless/ath/ath12k/core.c'
CNSS_SOURCE = 'https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/qmi.c'
CNSS_M3_SOURCE = 'https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/518147fd7e0199758efe9bd96a22c9c2ea30bcd9/platform/cnss2/pci.c#L4099'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checked_range(offset, size, total, bits=64):
    limit = 1 << bits
    require(type(offset) is int and type(size) is int and 0 <= offset < limit and 0 <= size < limit,
            'invalid unsigned range')
    require(size <= limit - offset and offset <= total and size <= total - offset, 'range overflow or truncation')
    return offset + size


def parse_board_name(raw, kind='board'):
    require(kind in ('board', 'regdb'), 'invalid board-name kind')
    require(0 < len(raw) <= MAX_NAME_BYTES and all(32 <= value < 127 for value in raw),
            'board name must be bounded printable ASCII without NUL')
    text = raw.decode('ascii')
    attributes = {}
    allowed = {'bus', 'vendor', 'device', 'subsystem-vendor', 'subsystem-device',
               'qmi-chip-id', 'qmi-board-id', 'variant'}
    for token in text.split(','):
        require(token.count('=') == 1, 'invalid board-name attribute')
        key, value = token.split('=')
        require(key in allowed and value and key not in attributes, 'unknown, empty or duplicate board-name attribute')
        if key == 'bus':
            require(re.fullmatch(r'[a-z][a-z0-9_-]{0,15}', value), 'invalid bus attribute')
            decoded = value
        elif key in ('qmi-chip-id', 'qmi-board-id'):
            require(re.fullmatch(r'0|[1-9][0-9]{0,9}', value) and int(value) < UINT32_LIMIT,
                    'QMI board-name ID must be unsigned decimal u32')
            decoded = int(value)
        elif key == 'variant':
            require(len(value) <= 128 and value.strip() == value, 'invalid variant attribute')
            decoded = value
        else:
            require(re.fullmatch(r'[0-9a-fA-F]{4}', value), 'PCI board-name ID must have four hex digits')
            decoded = int(value, 16)
        attributes[key] = decoded
    require('bus' in attributes, 'board name missing required bus attribute')
    qmi = {'qmi-chip-id', 'qmi-board-id'}
    pci = {'vendor', 'device', 'subsystem-vendor', 'subsystem-device'}
    require(not qmi.intersection(attributes) or qmi.issubset(attributes), 'board name missing required QMI attributes')
    require(not pci.intersection(attributes) or pci.issubset(attributes), 'board name missing required PCI attributes')
    require(not pci.intersection(attributes) or attributes['bus'] == 'pci', 'PCI attributes on non-PCI board name')
    require(kind != 'board' or qmi.issubset(attributes), 'board name missing required QMI attributes')
    require(qmi.issubset(attributes) or set(attributes) == {'bus'}, 'unsupported bus-only regdb attributes')
    return {'name': text, 'attributes': attributes, 'ids_source': 'container_name_not_live_hardware'}


def parse_tlvs(data, base, budget):
    position = 0
    while position < len(data):
        require(len(data) - position >= 8, 'truncated TLV header')
        identifier, size = struct.unpack_from('<II', data, position)
        start = position + 8
        aligned = (size + 3) & ~3
        require(aligned < UINT32_LIMIT, 'TLV aligned length overflows u32')
        end = checked_range(start, aligned, len(data))
        require(not any(data[start + size:end]), 'nonzero TLV padding')
        budget[0] += 1
        require(budget[0] <= MAX_TLVS, 'TLV count limit exceeded')
        yield identifier, data[start:start + size], base + start
        position = end


def parse_board2(data):
    require(len(MAGIC) < len(data) <= MAX_FILE_BYTES and data.startswith(MAGIC), 'invalid ath12k board-2 magic or size')
    records, known_names, budget = [], set(), [0]
    for identifier, payload, offset in parse_tlvs(data[len(MAGIC):], len(MAGIC), budget):
        require(identifier in (0, 1), 'unsupported top-level board-2 TLV')
        require(len(records) < MAX_RECORDS, 'board-2 record limit exceeded')
        kind = 'board' if identifier == 0 else 'regdb'
        aliases, board_data, data_offset = [], None, None
        for child_id, value, child_offset in parse_tlvs(payload, offset, budget):
            if child_id == 0:
                require(board_data is None and len(aliases) < MAX_ALIASES, 'name after data or alias limit exceeded')
                alias = parse_board_name(value, kind)
                identity = (kind, alias['name'])
                require(identity not in known_names, 'duplicate board-2 name')
                known_names.add(identity)
                aliases.append(alias)
            elif child_id == 1:
                require(aliases and board_data is None and 0 < len(value) <= MAX_RAW_BYTES,
                        'missing name, duplicate data or invalid board-data size')
                board_data, data_offset = value, child_offset
            else:
                raise ValueError('unsupported nested board-2 TLV')
        require(aliases and board_data is not None, 'board-2 record missing required name/data TLVs')
        records.append({'kind': kind, 'names': aliases, 'data_offset': data_offset,
                        'bytes': len(board_data), 'sha256': sha256(board_data),
                        'wire_type_hint': 'elf' if board_data.startswith(b'\x7fELF') else 'bin',
                        'calibration_compatibility': 'unverified'})
    require(any(record['kind'] == 'board' for record in records), 'board-2 missing required board record')
    return {'format': 'ath12k-board-api2', 'format_source': FORMAT_SOURCE,
            'records': records, 'tlvs_checked': budget[0]}


def parse_elf(data):
    require(16 <= len(data) <= MAX_RAW_BYTES and data[:4] == b'\x7fELF', 'invalid ELF magic or size')
    elf_class, encoding, version = data[4:7]
    require(elf_class in (1, 2) and encoding in (1, 2) and version == 1 and not any(data[9:16]),
            'unsupported or malformed ELF identification')
    endian = '<' if encoding == 1 else '>'
    bits = 32 if elf_class == 1 else 64
    header_size, program_size, section_size = (52, 32, 40) if bits == 32 else (64, 56, 64)
    require(len(data) >= header_size, 'truncated ELF header')
    header_format = 'HHIIIIIHHHHHH' if bits == 32 else 'HHIQQQIHHHHHH'
    (elf_type, machine, elf_version, entry, program_offset, section_offset, flags,
     size, program_stride, program_count, section_stride, section_count,
     string_index) = struct.unpack_from(endian + header_format, data, 16)
    require(elf_version == 1 and size == header_size, 'invalid ELF header version/size')
    require(program_count <= MAX_ELF_HEADERS and section_count <= MAX_ELF_HEADERS,
            'ELF header count exceeds bound or uses extended numbering')
    require((not program_count and not program_offset) or
            (program_offset >= header_size and program_stride == program_size), 'invalid ELF program table')
    require((not section_count and not section_offset) or
            (section_count and section_offset >= header_size and section_stride == section_size), 'invalid ELF section table')
    checked_range(program_offset, program_count * program_stride, len(data), bits)
    checked_range(section_offset, section_count * section_stride, len(data), bits)
    require(string_index == 0 or string_index < section_count, 'invalid ELF section-string index')
    segments = []
    for index in range(program_count):
        values = struct.unpack_from(endian + ('IIIIIIII' if bits == 32 else 'IIQQQQQQ'),
                                    data, program_offset + index * program_stride)
        if bits == 32:
            segment_type, offset, virtual, physical, file_size, memory_size, segment_flags, alignment = values
        else:
            segment_type, segment_flags, offset, virtual, physical, file_size, memory_size, alignment = values
        checked_range(offset, file_size, len(data), bits)
        require(virtual < (1 << bits) and memory_size <= (1 << bits) - virtual, 'ELF segment address overflow')
        require(segment_type != 1 or memory_size >= file_size, 'ELF load segment memory smaller than file')
        require(alignment in (0, 1) or alignment & (alignment - 1) == 0, 'invalid ELF segment alignment')
        segments.append({'type': segment_type, 'offset': offset, 'bytes': file_size,
                         'memory_bytes': memory_size, 'sha256': sha256(data[offset:offset + file_size])})
    return {'format': 'android-raw-elf-wrapper', 'elf': {'class_bits': bits, 'endian': 'little' if encoding == 1 else 'big',
            'type': elf_type, 'machine': machine, 'program_headers': program_count,
            'section_headers': section_count, 'segments': segments},
            'embedded_calibration_ids': None,
            'missing': ['verified Android BDF payload schema/ID offsets', 'live BDF selection and calibration evidence']}


def filename_hint(name):
    numbered = re.fullmatch(r'bdwlan(g)?([0-9a-fA-F]{2})?\.([eb])([0-9a-fA-F]{2})', name)
    if numbered:
        high = int(numbered[2], 16) if numbered[2] else 0
        return {'basis': 'CNSS_filename_encoding_only', 'board_id_hint': high * 256 + int(numbered[4], 16),
                'gf_stem': bool(numbered[1]), 'suffix_type': 'elf' if numbered[3] == 'e' else 'bin',
                'is_live_id': False, 'source': CNSS_SOURCE}
    project = re.fullmatch(r'bd_(m2|m3|m11)(gl)?\.elf', name)
    if project:
        return {'basis': 'CNSS_filename_encoding_only', 'project_hint': project[1],
                'global_name_hint': bool(project[2]), 'is_live_id': False, 'source': CNSS_SOURCE}
    return None


def inventory_bytes(data, name, provenance, file_format='auto'):
    require(isinstance(provenance, str) and provenance.strip(), 'nonempty provenance is required')
    require(file_format in ('auto', 'board-2', 'android-elf', 'opaque-raw'), 'invalid inventory format')
    require(0 < len(data) <= MAX_FILE_BYTES, 'input file size exceeds bound or is empty')
    if file_format == 'board-2' or (file_format == 'auto' and (data.startswith(b'QCA-ATH') or name == 'board-2.bin')):
        report = parse_board2(data)
    elif file_format == 'android-elf' or (file_format == 'auto' and (data.startswith(b'\x7fELF') or name.endswith('.elf'))):
        report = parse_elf(data)
    else:
        require(len(data) <= MAX_RAW_BYTES, 'opaque raw BDF exceeds driver file bound')
        report = {'format': 'opaque-raw-not-schema-verified', 'embedded_calibration_ids': None,
                  'missing': ['verified raw BIN BDF schema/ID offsets', 'live BDF selection and calibration evidence']}
    report.update(name=name, bytes=len(data), sha256=sha256(data), provenance=provenance,
                  filename_hint=filename_hint(name), selected=False, calibration_compatibility='unverified')
    return report


def read_regular(path, max_bytes=MAX_FILE_BYTES):
    require(type(max_bytes) is int and 0 < max_bytes <= MAX_FILE_BYTES, 'invalid regular-file read bound')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink() and
            not getattr(before, 'st_file_attributes', 0) & 0x400, 'input must be a regular non-reparse file')
    require(0 < before.st_size <= max_bytes, 'input file size exceeds bound or is empty')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                'input identity changed before read')
        data = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
        require((opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and
                len(data) == before.st_size == opened.st_size, 'input changed or short read')
    return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON attribute')
        result[key] = value
    return result


def read_root_capture(path):
    manifest_bytes = read_regular(path, MAX_MANIFEST_BYTES)
    manifest = json.loads(manifest_bytes.decode('utf-8'), object_pairs_hook=unique_object)
    require(isinstance(manifest, dict), 'capture manifest must be an object')
    provenance, files, version = manifest.get('provenance'), manifest.get('files'), manifest.get('version')
    require(isinstance(provenance, dict) and isinstance(provenance.get('guest_log'), str) and
            isinstance(provenance.get('captured_at'), str) and provenance['captured_at'] and
            isinstance(provenance.get('method'), str) and provenance['method'], 'capture provenance missing required attributes')
    require(isinstance(files, dict) and len(files) <= 64 and isinstance(version, dict), 'invalid capture files/version attributes')
    require(isinstance(manifest.get('root_path'), str) and manifest['root_path'].startswith('/') and
            type(manifest.get('root_bytes')) is int and manifest['root_bytes'] > 0, 'capture root missing required attributes')
    guest = Path(provenance['guest_log'])
    if not guest.is_absolute():
        guest = path.parent / guest
    require(guest.resolve().is_relative_to(path.parent.resolve()), 'guest log must stay inside capture directory')
    log_bytes = read_regular(guest, MAX_CAPTURE_LOG_BYTES)
    lines = [line.strip() for line in log_bytes.decode('utf-8').splitlines()]
    for marker in ('ROOT_ASSETS_MOUNT_OK', 'ROOT_ASSETS_INSPECT_SUCCESS', 'GUEST_OK'):
        require(lines.count(marker) == 1, 'capture missing or duplicate success marker ' + marker)
    directories, sent, counts, versions = [], {}, [], []
    for line in lines:
        if line.startswith('ROOT_DIRECTORY '):
            item = json.loads(line.removeprefix('ROOT_DIRECTORY '), object_pairs_hook=unique_object)
            require(isinstance(item, dict) and isinstance(item.get('path'), str) and type(item.get('exists')) is bool,
                    'invalid ROOT_DIRECTORY receipt')
            if item['path'] == WLAN_DIRECTORY:
                directories.append(item)
        elif line.startswith('ROOT_FILE_SENT '):
            match = re.fullmatch(r'ROOT_FILE_SENT (/[\S]+) ([0-9]+)', line)
            require(match and match[1] not in sent and int(match[2]) > 0, 'invalid or duplicate ROOT_FILE_SENT receipt')
            sent[match[1]] = int(match[2])
        elif line.startswith('ROOT_FILE_COUNT '):
            count = line.removeprefix('ROOT_FILE_COUNT ')
            require(re.fullmatch(r'[0-9]{1,3}', count), 'invalid ROOT_FILE_COUNT receipt')
            counts.append(int(count))
        elif line.startswith('ROOT_VERSION '):
            versions.append(json.loads(line.removeprefix('ROOT_VERSION '), object_pairs_hook=unique_object))
    require(len(directories) == 1, 'capture missing or duplicate WLAN ROOT_DIRECTORY receipt')
    require(counts == [len(files)] and set(sent) == set(files), 'capture manifest differs from file receipts')
    require(versions == [version], 'capture manifest differs from version receipt')
    observed = []
    for runtime_path, entry in files.items():
        require(isinstance(entry, dict) and entry.get('runtime_path') == runtime_path and
                type(entry.get('bytes')) is int and entry['bytes'] == sent[runtime_path] and
                re.fullmatch(r'[0-9a-fA-F]{64}', str(entry.get('sha256', ''))), 'invalid capture file record')
        observed.append({'runtime_path': runtime_path, 'bytes': entry['bytes'], 'sha256': entry['sha256'].lower(),
                         'status': 'manifest_and_guest_receipt_only_not_payload_verified'})
    wlan_files = [entry for entry in observed if entry['runtime_path'].startswith(WLAN_DIRECTORY + '/')]
    require(directories[0]['exists'] or not wlan_files, 'absent WLAN directory contradicts manifest file records')
    return {'manifest_path': str(path.resolve()), 'manifest_sha256': sha256(manifest_bytes),
            'guest_log_path': str(guest.resolve()), 'guest_log_sha256': sha256(log_bytes),
            'root_path': manifest['root_path'], 'root_bytes': manifest['root_bytes'],
            'captured_at': provenance['captured_at'], 'version': version,
            'wlan_directory': {'runtime_path': WLAN_DIRECTORY, 'exists': directories[0]['exists'],
                               'evidence': 'successful_guest_ROOT_DIRECTORY_receipt'},
            'observed_files': observed, 'wlan_files_recorded': len(wlan_files),
            'payload_files_opened': 0, 'bdf_selected': False}


def safe_path(text, absolute=False):
    require(isinstance(text, str) and len(text) <= 512 and
            re.fullmatch(r'/?[A-Za-z0-9_.!,:/-]+', text) and text.startswith('/') == absolute and
            all(part and part not in ('.', '..') for part in text.lstrip('/').split('/')), 'unsafe receipt path')
    return text


def parse_android_capability(data):
    require(0 < len(data) <= MAX_CAPTURE_LOG_BYTES, 'Android capability log exceeds bound or is empty')
    patterns = {
        'firmware_path': r'FW name is (\S+), FW fallback name is (\S+)',
        'cap': r'Target capability: chip_id: (0x[0-9a-fA-F]+), chip_family: (0x[0-9a-fA-F]+), board_id: (0x[0-9a-fA-F]+), soc_id: (0x[0-9a-fA-F]+), otp_version: (0x[0-9a-fA-F]+)',
        'version': r'fw_version: (0x[0-9a-fA-F]+), fw_build_timestamp: ([^,]+), fw_build_id: ([^,]+), hwid_bitmap:\s*(0x[0-9a-fA-F]+)',
        'bdf_start': r'Sending BDF download message, state: (0x[0-9a-fA-F]+), type: ([0-9]+)',
        'prefix': r'FW name added with prefix: (\S+)',
        'download': r'Downloading BDF: (\S+), size: ([0-9]+)',
        'host_bdf': r'Host BDF config: HW_XPA: ([0-9]+) CalDB: ([0-9]+)',
        'm3_start': r'Sending M3 information message, state: (0x[0-9a-fA-F]+)',
        'm3_memory': r'M3 memory, va: (0x[0-9a-fA-F]+), pa: (0x[0-9a-fA-F]+), size: (0x[0-9a-fA-F]+)'}
    prefixes = {name: pattern.split(' (')[0] for name, pattern in patterns.items()}
    events, requests, found, downloads, pending = {}, {}, {}, [], None
    previous_time = -1
    for line_number, line in enumerate(data.decode('utf-8').splitlines(), 1):
        line_match = re.fullmatch(r'\[\s*([0-9]{1,10})\.([0-9]{1,6})\]\s+(.*)', line)
        if not line_match:
            require('cnss: Target capability:' not in line and 'cnss: Downloading BDF:' not in line,
                    'required Android receipt lacks bounded timestamp')
            continue
        time_us = int(line_match[1]) * 1000000 + int(line_match[2].ljust(6, '0'))
        text = line_match[3]
        if text.startswith('ueventd: firmware: loading '):
            match = re.fullmatch(r"ueventd: firmware: loading '([^']+)' for '([^']+)'", text)
            require(match, 'malformed firmware request receipt')
            name, sysfs = safe_path(match[1]), safe_path(match[2], True)
            require(name not in requests, 'duplicate firmware request receipt')
            require(sysfs.endswith('/firmware/' + name.replace('/', '!')), 'firmware request/sysfs mismatch')
            requests[name] = {'sysfs_path': sysfs, 'time_us': time_us}
        elif text.startswith('ueventd: found '):
            match = re.fullmatch(r'ueventd: found (\S+) for (\S+)', text)
            require(match, 'malformed firmware resolution receipt')
            runtime, sysfs = safe_path(match[1], True), safe_path(match[2], True)
            names = [name for name, request in requests.items() if request['sysfs_path'] == sysfs]
            require(len(names) == 1 and names[0] not in found and time_us >= requests[names[0]]['time_us'],
                    'unmatched, duplicate or reordered firmware resolution')
            found[names[0]] = {'runtime_path': runtime, 'time_us': time_us}
        elif text.startswith('cnss: '):
            message = text.removeprefix('cnss: ')
            matched = [(name, re.fullmatch(pattern, message)) for name, pattern in patterns.items()]
            matched = [(name, match) for name, match in matched if match]
            if not matched:
                require(not any(message.startswith(prefix) for prefix in prefixes.values()), 'malformed recognized CNSS receipt')
                continue
            name, match = matched[0]
            require(time_us >= previous_time, 'Android CNSS receipt time regressed')
            previous_time = time_us
            values = match.groups()
            if name in ('bdf_start', 'm3_start'):
                require(int(values[0], 16) < 1 << 64, 'CNSS state overflows u64')
            if name == 'prefix':
                if pending is not None:
                    require('request_name' not in pending, 'duplicate BDF prefix receipt')
                    pending['request_name'] = safe_path(values[0])
                    pending['prefix_time_us'] = time_us
            elif name == 'bdf_start':
                require(pending is None and len(downloads) < 2, 'duplicate or unfinished BDF transaction')
                bdf_type = int(values[1])
                require(bdf_type in (0, 1, 4), 'unsupported observed BDF type')
                pending = {'type': bdf_type, 'start_time_us': time_us, 'line_number': line_number}
            elif name == 'download':
                request_name, size = safe_path(values[0]), int(values[1])
                require(pending is not None and pending.get('request_name') == request_name and
                        0 < size <= MAX_RAW_BYTES and request_name in found and
                        pending['start_time_us'] <= pending['prefix_time_us'] <= requests[request_name]['time_us'] <=
                        found[request_name]['time_us'] <= time_us,
                        'BDF download lacks matching request/resolution or has invalid size')
                pending.update(request_name=request_name, runtime_path=found[request_name]['runtime_path'],
                               reported_bytes=size, download_time_us=time_us, each_segment_ack_observed=False)
                downloads.append(pending)
                pending = None
            else:
                require(name not in events, 'duplicate Android ' + name + ' receipt')
                events[name] = {'values': values, 'time_us': time_us, 'line_number': line_number}
    require(pending is None and all(name in events for name in ('firmware_path', 'cap', 'version', 'host_bdf')),
            'Android receipt missing required CAP/FW/HostBDF attributes')
    require(len(downloads) == 2 and downloads[0]['type'] == 4 and downloads[1]['type'] in (0, 1),
            'Android receipt requires ordered REGDB then board-data transactions')
    require(events['firmware_path']['time_us'] <= events['cap']['time_us'] <= events['version']['time_us'] <=
            downloads[0]['start_time_us'] <= downloads[1]['start_time_us'] <= events['host_bdf']['time_us'],
            'Android firmware/CAP/BDF receipt order differs')
    cap = {name: int(value, 16) for name, value in zip(('chip_id', 'chip_family', 'board_id', 'soc_id', 'otp_version'), events['cap']['values'])}
    require(all(value < UINT32_LIMIT for value in cap.values()), 'CAP ID overflows u32')
    fw_version, timestamp, build_id, hwid = events['version']['values']
    require(int(fw_version, 16) < UINT32_LIMIT and int(hwid, 16) < UINT32_LIMIT and
            len(timestamp) <= 64 and 0 < len(build_id) <= 256 and
            all(32 <= ord(value) < 127 for value in timestamp + build_id), 'invalid firmware identity receipt')
    firmware_name, fallback_name = (safe_path(value) for value in events['firmware_path']['values'])
    require(firmware_name in found and events['firmware_path']['time_us'] <= found[firmware_name]['time_us'] <= events['cap']['time_us'],
            'active firmware lacks a matching resolved request')
    host_xpa, caldb = map(int, events['host_bdf']['values'])
    require(host_xpa <= 255 and caldb <= 255, 'HostBDF value exceeds bound')
    m3 = None
    require(('m3_start' in events) == ('m3_memory' in events), 'incomplete M3 information receipt')
    if 'm3_memory' in events:
        require(events['host_bdf']['time_us'] <= events['m3_start']['time_us'] <= events['m3_memory']['time_us'],
                'M3 receipt precedes BDF host progress')
        printed_va, dma_address, size = (int(value, 16) for value in events['m3_memory']['values'])
        require(printed_va < 1 << 64 and dma_address > 0 and 0 < size <= 2 * MAX_RAW_BYTES, 'invalid M3 memory receipt')
        checked_range(dma_address, size, 1 << 64)
        m3 = {'printed_va': printed_va, 'va_pointer_value_verified': False, 'va_format': '%pK_may_be_redacted',
              'dma_address': dma_address, 'cpu_physical_address_verified': False, 'bytes': size,
              'payload_sha256': None, 'runtime_m3_filename_observed': False,
              'metadata_line_number': events['m3_memory']['line_number'],
              'metadata_time_us': events['m3_memory']['time_us'],
              'metadata_log_stage': 'before_QMI_request_and_reply_in_published_CNSS',
              'm3_info_reply_observed': False}
    downloads[1]['host_progressed_to_m3'] = m3 is not None
    candidate = None
    if firmware_name == 'kiwi/amss20.bin':
        candidate = {'request_name': 'kiwi/phy_ucode20.elf',
                     'android_path_to_check': '/vendor/firmware_mnt/image/kiwi/phy_ucode20.elf',
                     'basis': 'published_CNSS_KIWI_FW_V2_whole_file_load_not_runtime_filename_receipt',
                     'source': CNSS_M3_SOURCE, 'extract_elf_segments': False,
                     'selector_inputs_verified': False, 'installed_cnss_revision_verified': False,
                     'verified_loaded_payload_hash': None}
    return {'cap': cap, 'cap_validity_flags_observed': False, 'board_tlv_presence': 'not_logged_CNSS_normalized_value_only',
            'firmware': {'request_name': firmware_name, 'fallback_name': fallback_name,
                         'runtime_path': found[firmware_name]['runtime_path'], 'fw_version': int(fw_version, 16),
                         'timestamp': timestamp, 'build_id': build_id, 'hwid_bitmap': int(hwid, 16)},
            'regdb_request': downloads[0], 'board_request': downloads[1],
            'host_bdf': {'hw_xpa': host_xpa, 'caldb': caldb}, 'm3': m3, 'published_m3_source_candidate': candidate,
            'xnu_bdf_selected': False, 'calibration_compatibility': 'unverified'}


def read_android_survey(path):
    manifest_bytes = read_regular(path, MAX_MANIFEST_BYTES)
    manifest = json.loads(manifest_bytes.decode('utf-8'), object_pairs_hook=unique_object)
    require(isinstance(manifest, dict) and isinstance(manifest.get('records'), dict) and
            0 < len(manifest['records']) <= 32 and isinstance(manifest.get('captured_at'), str) and manifest['captured_at'] and
            manifest.get('method') == 'read-only Android shell', 'invalid Android survey manifest')
    verified = {}
    for name in ('identity', 'capability'):
        entry = manifest['records'].get(name)
        require(isinstance(entry, dict) and isinstance(entry.get('host_path'), str) and
                type(entry.get('bytes')) is int and 0 < entry['bytes'] <= MAX_CAPTURE_LOG_BYTES and
                re.fullmatch(r'[0-9a-fA-F]{64}', str(entry.get('sha256', ''))), 'Android survey missing required record ' + name)
        record_path = Path(entry['host_path'])
        if not record_path.is_absolute():
            record_path = path.parent / record_path
        require(record_path.resolve().is_relative_to(path.parent.resolve()), 'survey record path escapes capture directory')
        data = read_regular(record_path, MAX_CAPTURE_LOG_BYTES)
        require(len(data) == entry['bytes'] and sha256(data) == entry['sha256'].lower(), 'Android survey record hash/size mismatch')
        verified[name] = (data, str(record_path.resolve()), sha256(data))
    identity = verified['identity'][0].decode('utf-8').splitlines()
    require(identity and identity[0] == 'fuxi', 'Android survey identity is not Fuxi')
    report = parse_android_capability(verified['capability'][0])
    report.update(manifest_path=str(path.resolve()), manifest_sha256=sha256(manifest_bytes),
                  captured_at=manifest['captured_at'], device=identity[0], capability_path=verified['capability'][1],
                  capability_sha256=verified['capability'][2], identity_sha256=verified['identity'][2],
                  firmware_payloads_opened=0)
    return report


def read_android_assets(path, survey=None):
    manifest_bytes = read_regular(path, MAX_MANIFEST_BYTES)
    manifest = json.loads(manifest_bytes.decode('utf-8'), object_pairs_hook=unique_object)
    require(isinstance(manifest, dict) and isinstance(manifest.get('files'), dict) and
            0 < len(manifest['files']) <= 64 and isinstance(manifest.get('provenance'), dict) and
            type(manifest.get('root_staging_verified')) is bool, 'invalid Android assets manifest')
    require(all(isinstance(manifest['provenance'].get(name), str) and manifest['provenance'][name]
                for name in ('method', 'captured_at')), 'Android assets missing required provenance attributes')
    entries = manifest['files']
    require(all(isinstance(entry, dict) and type(entry.get('bytes')) is int and 0 < entry['bytes'] <= MAX_FILE_BYTES
                for entry in entries.values()) and sum(entry['bytes'] for entry in entries.values()) <= 32 * MAX_RAW_BYTES,
            'Android asset batch exceeds size bound')
    if survey:
        evidence_path = manifest['provenance'].get('selection_evidence')
        require(isinstance(evidence_path, str), 'Android assets lack selection evidence path')
        evidence = Path(evidence_path)
        if not evidence.is_absolute():
            evidence = path.parent / evidence
        require(evidence.resolve() == Path(survey['capability_path']),
                'Android assets reference a different selection receipt')
    reports = []
    for name, entry in entries.items():
        require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', name) and '..' not in name and
                isinstance(entry.get('host_path'), str) and re.fullmatch(r'[0-9a-fA-F]{64}', str(entry.get('sha256', ''))),
                'invalid Android asset record')
        android_path = safe_path(entry.get('android_path'), True)
        require(android_path.rsplit('/', 1)[-1] == name, 'Android asset basename/path mismatch')
        host = Path(entry['host_path'])
        if not host.is_absolute():
            host = path.parent / host
        require(host.resolve().is_relative_to(path.parent.resolve()), 'Android asset host path escapes capture directory')
        data = read_regular(host)
        require(len(data) == entry['bytes'] and sha256(data) == entry['sha256'].lower(), 'Android asset hash/size mismatch')
        report = {'name': name, 'android_path': entry['android_path'], 'host_path': str(host.resolve()),
                  'bytes': len(data), 'sha256': sha256(data), 'status': 'local_payload_hash_verified'}
        if survey:
            matched = [role for role in ('regdb_request', 'board_request')
                       if survey[role]['runtime_path'] == entry['android_path']]
            for role in matched:
                require(len(data) == survey[role]['reported_bytes'], 'asset differs from actual download size')
                report['actual_android_request_role'] = role
                if role == 'board_request':
                    require(data.startswith(b'\x7fELF') == (survey[role]['type'] == 1), 'BDF wire type differs from file magic')
                    report['format_inventory'] = inventory_bytes(data, name, str(path.resolve()))
            if survey['firmware']['runtime_path'] == entry['android_path']:
                report['actual_android_request_role'] = 'firmware'
                report['receipt_build_id_in_payload'] = survey['firmware']['build_id'].encode('ascii') in data
        reports.append(report)
    return {'manifest_path': str(path.resolve()), 'manifest_sha256': sha256(manifest_bytes),
            'root_staging_declared': manifest['root_staging_verified'], 'root_staging_verified': False, 'files': reports,
            'xnu_bdf_selected': False, 'm3_payload_hash_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='*')
    parser.add_argument('--provenance', required=True, help='Successful read-only capture/manifest record; not calibration proof')
    parser.add_argument('--format', choices=('auto', 'board-2', 'android-elf', 'opaque-raw'), default='auto')
    parser.add_argument('--capture-manifest', type=Path, help='Verify successful root capture receipts without opening captured payload files')
    parser.add_argument('--android-survey-manifest', type=Path, help='Verify local Android CAP/request receipts; never execute recorded commands')
    parser.add_argument('--android-assets-manifest', type=Path, help='Verify captured Android payload hashes without staging or selecting')
    args = parser.parse_args()
    try:
        require(args.files or args.capture_manifest or args.android_survey_manifest or args.android_assets_manifest,
                'explicit BDF files or a successful capture manifest are required')
        require(len(args.files) <= 64, 'file count limit exceeded')
        require(len({path.resolve() for path in args.files}) == len(args.files), 'duplicate input path')
        capture = read_root_capture(args.capture_manifest) if args.capture_manifest else None
        survey = read_android_survey(args.android_survey_manifest) if args.android_survey_manifest else None
        assets = read_android_assets(args.android_assets_manifest, survey) if args.android_assets_manifest else None
        reports = []
        for path in args.files:
            report = inventory_bytes(read_regular(path), path.name, args.provenance, args.format)
            report['host_path'] = str(path.resolve())
            reports.append(report)
        missing = ['M3 payload hash and matching firmware provenance', 'native-root WLAN staging evidence',
                   'calibration suitability is not proved by container names or firmware acceptance']
        if survey:
            missing.append('raw CAP TLV validity flags are not present in normalized CNSS logs')
        else:
            missing.append('same-boot successful WLFW CAP identity and actual firmware/BDF request receipts')
        roles = {entry.get('actual_android_request_role') for entry in assets['files']} if assets else set()
        if not {'firmware', 'regdb_request', 'board_request'}.issubset(roles):
            missing.append('actual requested firmware/BDF/regdb payload hash chain')
        print(json.dumps({'schema': 1, 'automatic_selection': False, 'files': reports, 'root_capture': capture,
                          'android_survey': survey, 'android_assets': assets,
                          'selector_source': SELECTOR_SOURCE,
                          'missing_live_evidence': missing}, indent=2))
    except (ValueError, OSError, struct.error) as error:
        raise SystemExit(str(error)) from error


if __name__ == '__main__':
    main()
