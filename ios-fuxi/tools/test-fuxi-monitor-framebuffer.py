import ast
import contextlib
import io
from pathlib import Path
import unittest

import usb.core

from fuxi_framebuffer import read_framebuffer_bytes


class FramebufferTests(unittest.TestCase):
    def run_capture(self, failures, reconnect=None):
        calls = []
        remaining = list(failures)
        recoveries = []

        def request(number, length, value, index):
            offset = value | index << 16
            calls.append(offset)
            self.assertEqual(number, 0x4e)
            self.assertEqual(length, min(512, 1080 * 150 * 4 - offset))
            if remaining and offset == remaining[0]:
                remaining.pop(0)
                raise usb.core.USBError('fixture disconnect')
            return bytes([(offset // 512) % 251]) * length

        def recover():
            recoveries.append(True)
            if reconnect:
                reconnect()

        with contextlib.redirect_stdout(io.StringIO()):
            result = read_framebuffer_bytes(request, 150, recover)
        self.assertEqual(len(result), 1080 * 150 * 4)
        for offset in range(0, len(result), 512):
            self.assertEqual(result[offset:offset + 512],
                             bytes([(offset // 512) % 251]) * min(512, len(result) - offset))
        return calls, recoveries

    def test_complete_without_reconnect(self):
        calls, recoveries = self.run_capture([])
        self.assertEqual(len(calls), (1080 * 150 * 4 + 511) // 512)
        self.assertEqual(recoveries, [])

    def test_resume_at_failed_chunk_without_rereading_prefix(self):
        calls, recoveries = self.run_capture([512, 131072])
        self.assertEqual(calls.count(0), 1)
        self.assertEqual(calls.count(512), 2)
        self.assertEqual(calls.count(131072), 2)
        self.assertEqual(len(recoveries), 2)

    def test_retry_budget_is_for_the_entire_capture(self):
        with self.assertRaises(usb.core.USBError):
            self.run_capture([512, 1024, 1536])

    def test_different_boot_is_not_combined(self):
        def refuse():
            raise ValueError('different monitor boot')
        with self.assertRaisesRegex(ValueError, 'different monitor boot'):
            self.run_capture([512], refuse)

    def test_short_transfer_is_not_completed_with_padding(self):
        with self.assertRaisesRegex(ValueError, 'short framebuffer'):
            read_framebuffer_bytes(lambda *arguments: b'', 150, lambda: None)

    def test_invalid_height_never_reaches_transport(self):
        def forbidden(*arguments):
            raise AssertionError('unexpected transport operation')
        for height in (0, 149, 2401):
            with self.assertRaises(ValueError):
                read_framebuffer_bytes(forbidden, height, forbidden)

    def test_production_reconnect_validates_boot_identity(self):
        path = Path(__file__).with_name('fuxi-xnu-monitor.py')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        node = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == 'read_framebuffer')
        fake_usb = type('FakeUSB', (), {'core': usb.core, 'util': type('FakeUtil', (), {
            'dispose_resources': staticmethod(lambda device: None)})})
        identity = {'image': 1, 'end': 2, 'entry': 3, 'boot_args': 4, 'launch': 1}
        changed = dict(identity, entry=9)
        reports = iter([identity, changed])
        environment = {
            'usb': fake_usb,
            'time': type('FakeTime', (), {'monotonic': staticmethod(lambda: 1),
                                        'sleep': staticmethod(lambda seconds: None)}),
            'monitor': lambda: next(reports), 'find_probe': lambda: object(),
            'args': type('Args', (), {'framebuffer_height': 150})(),
            'request': lambda *arguments: b'',
            'read_framebuffer_bytes': lambda request, height, recover: recover(),
        }
        parent = ast.parse('def fixture():\n    dev = None\n')
        parent.body[0].body.extend([node, ast.Return(value=ast.Call(
            func=ast.Name(id='read_framebuffer', ctx=ast.Load()), args=[], keywords=[]))])
        ast.fix_missing_locations(parent)
        exec(compile(parent, str(path), 'exec'), environment)
        with self.assertRaisesRegex(ValueError, 'different monitor boot'):
            environment['fixture']()


if __name__ == '__main__':
    unittest.main()
