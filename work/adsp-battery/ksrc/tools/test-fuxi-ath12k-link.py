import argparse
import json
from pathlib import Path
import runpy
import shutil
import struct
import tempfile


ROOT = Path(__file__).resolve().parents[1]
GATE = runpy.run_path(str(ROOT / 'tools/ci/ath12k-link.py'))


def rejected(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError('Invalid ath12k link input was accepted')


def image(commands, count=1, byte_count=None):
    return struct.pack('<8I', 0xfeedfacf, 0x0100000c, 0, 1, count,
                       len(commands) if byte_count is None else byte_count, 0, 0) + commands


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', nargs='?', type=Path)
    arguments = parser.parse_args()
    checks = 0
    with tempfile.TemporaryDirectory(prefix='fuxi-ath12k-link-') as temporary:
        directory = Path(temporary)
        object_path = directory / 'platform.o'
        version = struct.pack('<6I', 0x32, 24, 1, 0x000f0500, 0x000f0500, 0)
        object_path.write_bytes(image(version))
        assert GATE['platform_version'](object_path) == GATE['KERNEL_PLATFORM']
        checks += 1
        old_version = struct.pack('<4I', 0x24, 16, 0x000f0500, 0x000f0500)
        object_path.write_bytes(image(old_version))
        assert GATE['platform_version'](object_path) == GATE['KERNEL_PLATFORM']
        checks += 1
        bad_images = (
            b'',
            image(version)[:31],
            image(version)[:-1],
            image(version, byte_count=8),
            image(version, count=2),
            image(version, count=0),
            image(version + version, count=2),
            image(b'', count=0),
            image(struct.pack('<2I', 0x32, 0)),
            image(struct.pack('<2I', 0x32, 8)),
            image(struct.pack('<6I', 0x32, 24, 1, 0x000f0500, 0x000f0500, 1)),
            image(struct.pack('<4I', 0x24, 16, 0x000f0500, 0x000f0500) + b'\0' * 8,
                  byte_count=24),
        )
        for malformed in bad_images:
            object_path.write_bytes(malformed)
            rejected(lambda: GATE['platform_version'](object_path))
            checks += 1
        if arguments.bundle:
            record = GATE['validate_bundle'](arguments.bundle)
            assert record['kernel_build_target'] == GATE['KERNEL_TARGET']
            checks += 1
            copied = directory / 'bundle'
            shutil.copytree(arguments.bundle, copied)
            report_path = copied / 'fuxi_ath12k.build-report.json'
            original = report_path.read_bytes()
            for field, value in (
                    ('runtime', 'legacy'),
                    ('legacy_station_linked', True),
                    ('hardware_verified', True),
                    ('flags', ['-target', 'arm64-apple-ios16.0', '-mkernel', '-mgeneral-regs-only']),
                    ('flags', ['-target', GATE['KERNEL_TARGET'], '-mkernel']),
                    ('source_identity', {'source_lock_sha256': '0' * 64})):
                report = json.loads(original)
                report[field] = value
                report_path.write_text(json.dumps(report), encoding='utf-8')
                rejected(lambda: GATE['validate_bundle'](copied))
                checks += 1
            report_path.write_bytes(original)
            for filename, replacement in (
                    ('fuxi_ath12k.o', b'broken'),
                    ('fuxi_ath12k.scan-dwell.json', b'{}\n'),
                    ('fuxi_ath12k.undefined.txt', b'_unexpected_kernel_import\n'),
                    ('fuxi_ath12k.exports.txt', b'')):
                path = copied / filename
                original = path.read_bytes()
                path.write_bytes(replacement)
                rejected(lambda: GATE['validate_bundle'](copied))
                path.write_bytes(original)
                checks += 1
            original = report_path.read_bytes()
            for suffix in ('/out/ath12k-src/mac.c', '/src/nw_cfg80211_control.c'):
                report = json.loads(original)
                for item in report['objects']:
                    if item.get('source', '').endswith(suffix):
                        item['source_sha256'] = '0' * 64
                report_path.write_text(json.dumps(report), encoding='utf-8')
                rejected(lambda: GATE['validate_bundle'](copied))
                report_path.write_bytes(original)
                checks += 1
            GATE['validate_bundle'](copied)
            checks += 1
    print(f'PASS ath12k link inputs: {checks} platform and bundle checks')


if __name__ == '__main__':
    main()
