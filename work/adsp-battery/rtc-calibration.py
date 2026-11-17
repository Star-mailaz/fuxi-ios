import os
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

WORKSPACE = Path(r'D:\xiaomi13\fuxi_ios')
SERIAL = os.environ.get('FUXI_ANDROID_SERIAL', '')
RTC_NAME = 'rtc-pm8xxx c42d000.qcom,spmi:qcom,pmk8550@0:rtc@6100'
SCHEMA = 'fuxi-rtc-calibration-v1'
MAX_AGE_MS = 3600000
MIN_EPOCH = 1700000000
MAX_EPOCH = 2200000000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(record, now_ms=None):
    require(isinstance(record, dict) and record.get('schema') == SCHEMA, 'RTC calibration schema differs')
    require(record.get('serial') == SERIAL and record.get('rtc_name') == RTC_NAME,
            'RTC calibration device or RTC identity differs')
    integer_fields = ('host_begin_ms', 'host_end_ms', 'utc_before', 'utc_after',
                      'raw_before', 'raw_after', 'offset_seconds')
    require(all(type(record.get(name)) is int for name in integer_fields), 'RTC calibration integers required')
    host_begin, host_end = record['host_begin_ms'], record['host_end_ms']
    utc_before, utc_after = record['utc_before'], record['utc_after']
    raw_before, raw_after = record['raw_before'], record['raw_after']
    require(0 <= host_end - host_begin <= 5000, 'RTC capture host interval is invalid')
    require(MIN_EPOCH <= utc_before <= utc_after <= MAX_EPOCH, 'Android UTC is outside the sane date window')
    require(0 <= raw_before <= raw_after <= 0xffffffff, 'RTC counter reset, wrapped or malformed')
    require(utc_after - utc_before <= 2 and raw_after - raw_before <= 2,
            'RTC capture interval exceeds two seconds')
    require(abs((utc_after - utc_before) - (raw_after - raw_before)) <= 1,
            'RTC and Android UTC intervals differ')
    require(abs(utc_before * 1000 - host_begin) <= 3000 and abs(utc_after * 1000 - host_end) <= 3000,
            'Android and host UTC differ by more than three seconds')
    offset = utc_before - raw_before
    require(0 <= offset <= 0xffffffff and record['offset_seconds'] == offset, 'RTC calibration offset differs')
    current = int(time.time() * 1000) if now_ms is None else now_ms
    require(type(current) is int and host_end <= current <= host_end + MAX_AGE_MS,
            'RTC calibration is expired or from the future')
    return record


def capture():
    script = ('date -u +%s; cat /sys/class/rtc/rtc0/since_epoch; '
              'cat /sys/class/rtc/rtc0/name; cat /sys/class/rtc/rtc0/since_epoch; date -u +%s')
    host_begin = int(time.time() * 1000)
    result = subprocess.run(['adb', '-s', SERIAL, 'shell', f'su -c "{script}"'],
                            check=True, capture_output=True, text=True, timeout=15)
    host_end = int(time.time() * 1000)
    lines = result.stdout.splitlines()
    require(len(lines) == 5 and not result.stderr.strip(), 'RTC capture output is incomplete')
    require(all(lines[index].isdigit() for index in (0, 1, 3, 4)), 'RTC capture counters are malformed')
    record = {
        'schema': SCHEMA, 'serial': SERIAL, 'rtc_name': lines[2],
        'captured_at_utc': datetime.fromtimestamp(host_end / 1000, timezone.utc).isoformat(),
        'host_begin_ms': host_begin, 'host_end_ms': host_end,
        'utc_before': int(lines[0]), 'raw_before': int(lines[1]),
        'raw_after': int(lines[3]), 'utc_after': int(lines[4]),
        'offset_seconds': int(lines[0]) - int(lines[1]),
        'source': 'read-only Android date and rtc0 sysfs; no RTC register or clock writes',
    }
    return validate(record, host_end)


def load(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))


def verify_live(record):
    validate(record)
    current = capture()
    require(current['raw_before'] >= record['raw_after'], 'RTC counter went backwards since calibration')
    require(abs(current['offset_seconds'] - record['offset_seconds']) <= 2,
            'RTC offset changed since calibration')
    return current


def main():
    parser = argparse.ArgumentParser(description='Read-only calibration of Android UTC against the PMK8550 RTC counter.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    capture_parser = subparsers.add_parser('capture')
    capture_parser.add_argument('output', type=Path)
    verify_parser = subparsers.add_parser('verify')
    verify_parser.add_argument('calibration', type=Path)
    args = parser.parse_args()
    if args.command == 'capture':
        for name in ('work/PHONE-LOCK-000', 'work/hybrid-driver/HOLD-PHONE', 'work/adsp-battery/hw000/HOLD'):
            require(not (WORKSPACE / name).exists(), f'Phone reserved: {name}')
        require(not args.output.exists(), 'RTC capture output already exists')
        record = capture()
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        print(f'RTC_CALIBRATED raw={record["raw_before"]} offset={record["offset_seconds"]} '
              f'utc={record["utc_before"]} output={args.output}')
    else:
        record = load(args.calibration)
        current = verify_live(record)
        print(f'RTC_LIVE_OK raw={current["raw_before"]} offset={record["offset_seconds"]} '
              f'utc={current["utc_before"]}')


if __name__ == '__main__':
    main()
