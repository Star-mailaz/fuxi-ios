import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('rtc_calibration', Path(__file__).with_name('rtc-calibration.py'))
rtc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rtc)
NOW = 1794821893000


def valid_record():
    return {
        'schema': rtc.SCHEMA, 'serial': rtc.SERIAL, 'rtc_name': rtc.RTC_NAME,
        'host_begin_ms': NOW, 'host_end_ms': NOW + 100,
        'utc_before': NOW // 1000, 'utc_after': NOW // 1000,
        'raw_before': 38946, 'raw_after': 38946,
        'offset_seconds': NOW // 1000 - 38946,
    }


class RtcCalibrationTests(unittest.TestCase):
    def test_valid_capture_and_age_bound(self):
        record = valid_record()
        for age in (0, 1, rtc.MAX_AGE_MS):
            with self.subTest(age=age):
                self.assertIs(rtc.validate(record, record['host_end_ms'] + age), record)

    def test_bad_records_fail_closed(self):
        changes = (
            ('schema', 'other'), ('serial', 'other'), ('rtc_name', 'rtc-other'),
            ('host_begin_ms', True), ('raw_before', '38946'), ('offset_seconds', 0),
            ('host_end_ms', NOW - 1), ('host_end_ms', NOW + 5001),
            ('utc_before', rtc.MIN_EPOCH - 1), ('utc_after', rtc.MAX_EPOCH + 1),
            ('utc_after', NOW // 1000 - 1), ('raw_before', -1),
            ('raw_before', 0x100000000), ('raw_after', 38945), ('raw_after', 38949),
            ('utc_after', NOW // 1000 + 3), ('host_begin_ms', NOW - 4000),
        )
        for key, value in changes:
            with self.subTest(key=key, value=value):
                record = valid_record()
                record[key] = value
                with self.assertRaises(ValueError):
                    rtc.validate(record, NOW + 6000)
        for value in (None, [], {}, {'schema': rtc.SCHEMA}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                rtc.validate(value, NOW + 100)

    def test_expired_and_future_records(self):
        record = valid_record()
        for current in (NOW - 1, record['host_end_ms'] - 1, record['host_end_ms'] + rtc.MAX_AGE_MS + 1):
            with self.subTest(current=current), self.assertRaises(ValueError):
                rtc.validate(record, current)

    def test_counter_and_wall_clock_both_advance(self):
        record = valid_record()
        record['utc_after'] += 1
        record['raw_after'] += 1
        record['host_end_ms'] += 1000
        rtc.validate(record, record['host_end_ms'])
        record['raw_after'] += 1
        rtc.validate(record, record['host_end_ms'])
        record['utc_after'] -= 1
        with self.assertRaisesRegex(ValueError, 'intervals differ'):
            rtc.validate(record, record['host_end_ms'])

    def test_live_verification_rejects_reset_and_offset_change(self):
        record = valid_record()
        with mock.patch.object(rtc.time, 'time', return_value=(NOW + 1000) / 1000):
            for raw, offset, accepted in ((38947, record['offset_seconds'], True),
                                           (38945, record['offset_seconds'], False),
                                           (38947, record['offset_seconds'] + 3, False)):
                current = copy.deepcopy(record)
                current['raw_before'] = raw
                current['offset_seconds'] = offset
                with self.subTest(raw=raw, offset=offset), mock.patch.object(rtc, 'capture', return_value=current):
                    if accepted:
                        self.assertIs(rtc.verify_live(record), current)
                    else:
                        with self.assertRaises(ValueError):
                            rtc.verify_live(record)


if __name__ == '__main__':
    unittest.main()
