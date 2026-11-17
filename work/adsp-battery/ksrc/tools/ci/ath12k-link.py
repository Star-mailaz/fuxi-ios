import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

OBJECT_SHA256 = 'dc0694f49e8557b6dce943fe07711e272579b8ffc0e67196499d6f6ec3b83931'
LOCK_SHA256 = 'f23882695f1c136c27b3f9cb36673bebad9ae1fc2af3fa787a98bd4add76c3c9'
SCAN_DWELL_SHA256 = '4abc2793df722c3fc03fd098118cc1731301b5523a5c8f8b28d04228b8ec95bb'
ENTRY_POINTS = (
    '_nw_wifi_start', '_nw_wifi_step', '_nw_wifi_stop', '_nw_wifi_poll',
    '_nw_wifi_irq_mode', '_nw_wifi_scan', '_nw_wifi_bss_count',
    '_nw_wifi_bss_get', '_nw_wifi_stats',
    '_nw_wifi_set_platform', '_nw_wifi_control_transport_set',
    '_nw_wifi_control_attach', '_nw_wifi_control_receive',
    '_nw_wifi_power', '_nw_wifi_set_events', '_nw_wifi_tx',
)
IMPORTS = {
    '_bzero', '_memcmp', '_memcpy', '_memmove', '_memset', '_snprintf',
    '_sscanf', '_strchr', '_strcmp', '_strlen', '_strncpy', '_strtoul',
    '_vsnprintf',
}
KERNEL_TARGET = 'arm64-apple-macos15.5'
KERNEL_PLATFORM = (1, 0x000f0500)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def platform_version(path):
    data = path.read_bytes()
    require(len(data) >= 32 and struct.unpack_from('<3I', data) ==
            (0xfeedfacf, 0x0100000c, 0), 'Expected a plain arm64 Mach-O image')
    count, command_bytes = struct.unpack_from('<2I', data, 16)
    require(count <= command_bytes // 8 and command_bytes <= len(data) - 32,
            'Mach-O load command table is invalid')
    cursor, end, versions = 32, 32 + command_bytes, []
    for _ in range(count):
        require(cursor + 8 <= end, 'Mach-O load command is truncated')
        command, size = struct.unpack_from('<2I', data, cursor)
        require(size >= 8 and not size % 8 and size <= end - cursor,
                'Mach-O load command size is invalid')
        if command == 0x32:
            require(size >= 24, 'Mach-O build version is truncated')
            platform, minimum, _, tools = struct.unpack_from('<4I', data, cursor + 8)
            require(size == 24 + tools * 8, 'Mach-O build tool table is invalid')
            versions.append((platform, minimum))
        elif command in (0x24, 0x25, 0x2f, 0x30):
            require(size == 16, 'Mach-O minimum version is invalid')
            versions.append(({0x24: 1, 0x25: 2, 0x2f: 3, 0x30: 4}[command],
                             struct.unpack_from('<I', data, cursor + 8)[0]))
        cursor += size
    require(cursor == end and len(versions) == 1, 'Mach-O platform must be unambiguous')
    return versions[0]


def validate_bundle(directory):
    directory = Path(directory).resolve()
    object_path = directory / 'fuxi_ath12k.o'
    require(object_path.is_file() and not object_path.is_symlink(),
            'Pinned ath12k object is missing or is a symlink')
    require(digest(object_path) == OBJECT_SHA256, 'Pinned ath12k object hash differs')
    with object_path.open('rb') as stream:
        header = stream.read(32)
    require(len(header) == 32 and struct.unpack_from('<4I', header) ==
            (0xfeedfacf, 0x0100000c, 0, 1), 'ath12k input must be an arm64 Mach-O object')
    require(platform_version(object_path) == KERNEL_PLATFORM,
            'ath12k object platform differs from the Fuxi kernel build')
    report_path = directory / 'fuxi_ath12k.build-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    dwell_path = directory / 'fuxi_ath12k.scan-dwell.json'
    require(dwell_path.is_file() and not dwell_path.is_symlink() and
            digest(dwell_path) == SCAN_DWELL_SHA256, 'ath12k scan dwell provenance differs')
    dwell = json.loads(dwell_path.read_text(encoding='utf-8'))
    require(dwell.get('schema') == 'fuxi-ath12k-scan-dwell-v1' and
            dwell.get('feature_bit') == 1 << 31 and dwell.get('attribute') == 46 and
            dwell.get('maximum_requested_ms') == 1000 and
            dwell.get('maximum_scan_budget_ms') == 19000 and
            dwell.get('passive_ssids_null') is True and
            dwell.get('linux_rdev_ops_sha256') ==
            'bfa4934811cbe41355ec4be5c713f31564df9432648bb65def782fd10214e06e' and
            dwell.get('hardware_verified') is False, 'ath12k scan dwell ABI differs')
    for suffix in ('/src/nw_cfg80211_control.c', '/out/ath12k-src/mac.c'):
        objects = [item for item in report.get('objects', [])
                   if item.get('source', '').endswith(suffix)]
        expected = dwell['files'][suffix.lstrip('/')]['after_sha256']
        require(len(objects) == 1 and objects[0].get('source_sha256') == expected,
                'ath12k build does not include the reviewed scan dwell source')
    require(report.get('runtime') == 'mainline' and
            report.get('legacy_station_linked') is False and
            report.get('hardware_verified') is False, 'ath12k build report differs')
    identity = report.get('source_identity', {})
    require(identity.get('source_lock_sha256') == LOCK_SHA256,
            'ath12k source lock differs')
    flags = report.get('flags', [])
    require(flags.count('-target') == 1 and
            flags[flags.index('-target') + 1:flags.index('-target') + 2] ==
            [KERNEL_TARGET] and '-mkernel' in flags and
            '-mgeneral-regs-only' in flags, 'ath12k kernel ABI flags differ')
    undefined = set((directory / 'fuxi_ath12k.undefined.txt').read_text().split())
    exports = set((directory / 'fuxi_ath12k.exports.txt').read_text().split())
    require(undefined == IMPORTS, 'ath12k kernel imports differ')
    require(set(ENTRY_POINTS) <= exports, 'ath12k module entry points are missing')
    return {
        'schema': 'fuxi-ath12k-link-v1',
        'object_sha256': OBJECT_SHA256,
        'build_report_sha256': digest(report_path),
        'source_lock_sha256': LOCK_SHA256,
        'source_identity': identity,
        'scan_dwell_provenance_sha256': SCAN_DWELL_SHA256,
        'scan_dwell': dwell,
        'entry_points': list(ENTRY_POINTS),
        'imports': sorted(IMPORTS),
        'source_run': 44010197996,
        'source_commit': 'b2876c666c76af54be793a41830596a6b604a063',
        'kernel_build_target': KERNEL_TARGET,
        'macho_platform': KERNEL_PLATFORM[0],
        'minimum_os': '15.5',
        'hardware_verified': False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--kernel', type=Path)
    parser.add_argument('--nm', type=Path)
    arguments = parser.parse_args()
    record = validate_bundle(arguments.directory)
    if arguments.kernel:
        require(platform_version(arguments.kernel) == KERNEL_PLATFORM,
                'Linked kernel platform differs from the ath12k object')
        command = [str(arguments.nm)] if arguments.nm else ['xcrun', 'nm']
        result = subprocess.run(command + ['--defined-only', str(arguments.kernel)],
                                check=True, capture_output=True, text=True, timeout=90)
        symbols = {line.split()[-1] for line in result.stdout.splitlines() if line.split()}
        require(set(ENTRY_POINTS) <= symbols, 'Linked kernel lacks ath12k entry points')
        record['linked_kernel_sha256'] = digest(arguments.kernel)
        record['entry_points_defined'] = True
    if arguments.output:
        with arguments.output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(record, indent=2) + '\n')
    print('PASS pinned ath12k object, ABI, source lock and imports' +
          ('; kernel entry points defined' if arguments.kernel else ''))


if __name__ == '__main__':
    main()
