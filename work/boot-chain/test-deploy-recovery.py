import ast
import copy
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name('deploy-verified.py')


def load_recovery():
    parsed = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    nodes = [node for node in parsed.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) or
             (isinstance(node, ast.Assign) and all(isinstance(target, ast.Name) and target.id.isupper()
                                                  for target in node.targets))]
    module = types.ModuleType('deploy_recovery_under_test')
    module.__file__ = str(SCRIPT)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT), 'exec'), module.__dict__)
    production = next(node for node in parsed.body if isinstance(node, ast.Try))
    failure_path = copy.deepcopy(production)
    failure_path.body = [ast.Raise(exc=ast.Name(id='injected_failure', ctx=ast.Load()), cause=None)]
    failure_path.orelse = []
    module.failure_path = compile(ast.fix_missing_locations(ast.Module(body=[failure_path], type_ignores=[])),
                                  '<production-deployment-except-finally>', 'exec')
    return module


def checksum(contents):
    return hashlib.sha256(contents).hexdigest()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fuxi-deploy-recovery-')
        self.addCleanup(self.temporary.cleanup)
        self.deploy = load_recovery()
        self.deploy.workspace = Path(self.temporary.name) / 'fuxi_ios'
        self.deploy.workspace.mkdir()
        self.deploy.backup = self.deploy.workspace.parent / 'fuxi_Backup' / 'boot_b-chain-v4-before-chain-v6-test'
        self.deploy.backup.mkdir(parents=True)
        self.deploy.backup_created = True
        self.deploy.arguments = types.SimpleNamespace(previous='chain-v4', next='chain-v6')
        self.deploy.token = '000 deploy chain-v6 host-only-test-token'
        self.deploy.previous_image = self.deploy.workspace / 'work/boot-chain/chain-v4/boot.img'
        self.deploy.previous_image.parent.mkdir(parents=True)
        self.previous_boot = b'P' * 4096
        self.deploy.previous_image.write_bytes(self.previous_boot)
        self.deploy.previous_sha = checksum(self.previous_boot)
        self.deploy.size = len(self.previous_boot)
        self.deploy.stock_a = checksum(b'stock boot a')
        # 2026-11-18 起 boot_a 可為已驗證的常駐選單；部署開始時記下的值才是還原的基準
        self.deploy.boot_a_sha = checksum(b'installed dualboot boot a')
        self.phone_boot_a = self.deploy.boot_a_sha
        self.deploy.module_path = '/data/adb/modules/fuxi_ios_boot'
        self.deploy.local_module = self.deploy.workspace / 'work/ksu-ios-entry/fuxi_ios_boot'
        self.deploy.local_module.mkdir(parents=True)
        self.deploy.host_saved_hashes = {}
        self.original_files = {}
        for name in self.deploy.HOST_MODULE_FILES:
            contents = ('old ' + name).encode()
            if name == 'loader.sha256':
                contents = (self.deploy.previous_sha + '\n').encode()
            elif name == 'loader.size':
                contents = (str(self.deploy.size) + '\n').encode()
            self.original_files[name] = contents
            saved = self.deploy.backup / 'host-module-before' / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(contents)
            target = self.deploy.local_module / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(('changed ' + name).encode())
            self.deploy.host_saved_hashes[name] = {'sha256': checksum(contents), 'bytes': len(contents)}
        archive = self.deploy.backup / 'fuxi_ios_boot-module.tar'
        with tarfile.open(archive, 'w') as saved:
            root = tarfile.TarInfo('fuxi_ios_boot')
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            saved.addfile(root)
            for name, contents in self.original_files.items():
                member = tarfile.TarInfo('fuxi_ios_boot/' + name)
                member.size = len(contents)
                member.mode = 0o755 if name.startswith('bin/') else 0o644
                saved.addfile(member, io.BytesIO(contents))
        self.deploy.archive_sha = checksum(archive.read_bytes())
        self.deploy.owned = [self.deploy.workspace / 'work/PHONE-LOCK-000',
                             self.deploy.workspace / 'work/hybrid-driver/HOLD-PHONE']
        for path in self.deploy.owned:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.deploy.token, encoding='utf-8')
        self.deploy.boot_changed = True
        self.deploy.module_changed = True
        self.deploy.host_changed = True
        self.deploy.pending_write = None
        self.deploy.release_allowed = False
        self.deploy.failure_report = None
        self.original_failure = AssertionError('original deployment verification failed')
        self.deploy.injected_failure = self.original_failure
        self.remote_files = {}
        self.remote_members = {}
        self.phone_boot = b'N' * 4096
        self.calls = []
        self.fail_boot = None
        self.fail_module = None
        self.bad_remote_boot_hash = False
        self.bad_boot_readback = False
        self.bad_module_readback = False
        self.capacity_output = '0 0 0 12'
        self.deploy.adb = mock.Mock(side_effect=self.adb)
        self.deploy.rooted = mock.Mock(side_effect=self.rooted)
        self.deploy.say = mock.Mock()
        self.no_phone = mock.patch.object(self.deploy.subprocess, 'check_output',
                                          side_effect=AssertionError('Actual subprocess/phone access is forbidden'))
        self.no_phone.start()
        self.addCleanup(self.no_phone.stop)

    def adb(self, *command):
        self.calls.append(('adb', command))
        if command[0] == 'push':
            self.remote_files[command[2]] = Path(command[1]).read_bytes()
            return ''
        if command == ('shell', 'getprop ro.boot.slot_suffix'):
            return '_a'
        raise AssertionError(f'Unexpected mock adb call: {command}')

    def rooted(self, command):
        self.calls.append(('rooted', command))
        words = shlex.split(command)
        if words == ['od', '-An', '-t', 'u1', '/sys/firmware/devicetree/base/memory/ddr_size']:
            return self.capacity_output
        if words[:3] == ['stat', '-c', '%s']:
            return str(len(self.remote_files[words[3]]))
        if words[0] == 'sha256sum':
            target = words[1]
            if target == '/dev/block/by-name/boot_a':
                return self.phone_boot_a
            if self.bad_remote_boot_hash and target.endswith('.img'):
                return checksum(b'corrupted remote boot')
            if self.bad_module_readback and target.endswith('/module.prop'):
                return checksum(b'corrupted module readback')
            return checksum(self.remote_files[target])
        if words[0] == 'dd':
            if self.fail_boot:
                raise self.fail_boot
            source = next(word.removeprefix('if=') for word in words if word.startswith('if='))
            self.phone_boot = self.remote_files[source]
            return ''
        if words[0] == 'echo':
            return ''
        if words[0] == 'head':
            return checksum(b'bad prefix') if self.bad_boot_readback else checksum(self.phone_boot)
        if words[:2] == ['tar', '-xf']:
            if self.fail_module:
                raise self.fail_module
            with tarfile.open(fileobj=io.BytesIO(self.remote_files[words[2]])) as saved:
                for member in saved:
                    target = '/data/adb/modules/' + member.name.rstrip('/')
                    self.remote_members[target] = member
                    if member.isfile():
                        self.remote_files[target] = saved.extractfile(member).read()
            return ''
        if words[:2] == ['test', '-d']:
            if not self.remote_members[words[2]].isdir():
                raise AssertionError('Expected restored directory')
            return ''
        if words[:3] == ['stat', '-c', '%a %u %g']:
            member = self.remote_members[words[3]]
            return f'{member.mode:o} {member.uid} {member.gid}'
        raise AssertionError(f'Unexpected mock rooted call: {command}')

    def run_failure_path(self):
        with self.assertRaises(BaseException) as failure:
            exec(self.deploy.failure_path, self.deploy.__dict__)
        self.assertIs(failure.exception, self.deploy.injected_failure)
        return self.deploy.failure_report

    def assert_locks_held(self):
        for path in self.deploy.owned:
            self.assertEqual(path.read_text(encoding='utf-8'), self.deploy.token)
        messages = [call.args[0] for call in self.deploy.say.call_args_list]
        self.assertTrue(any('MANUAL_RECOVERY_REQUIRED' in message for message in messages))
        self.assertNotIn('PHONE_RELEASED', messages)

    def assert_host_restored(self):
        for name, contents in self.original_files.items():
            self.assertEqual((self.deploy.local_module / name).read_bytes(), contents)

    def assert_saved_report(self, report):
        saved = json.loads(Path(report['report']).read_text(encoding='utf-8'))
        self.assertEqual(saved['original_error']['message'], str(self.deploy.injected_failure))
        events = [json.loads(line) for line in Path(report['journal']).read_text(encoding='utf-8').splitlines()]
        self.assertTrue(events)
        self.assertTrue(all(event['token'] == self.deploy.token for event in events))
        return saved, events

    def test_boot_restore_failure_still_restores_module_and_host(self):
        self.fail_boot = subprocess.CalledProcessError(1, 'mock restore boot')
        report = self.run_failure_path()
        self.assertFalse(report['steps']['boot']['verified'])
        self.assertTrue(report['steps']['module']['verified'])
        self.assertTrue(report['steps']['host_module']['verified'])
        self.assert_host_restored()
        self.assert_locks_held()
        self.assert_saved_report(report)

    def test_module_restore_failure_still_restores_host(self):
        self.fail_module = subprocess.CalledProcessError(1, 'mock restore module')
        report = self.run_failure_path()
        self.assertTrue(report['steps']['boot']['verified'])
        self.assertFalse(report['steps']['module']['verified'])
        self.assertTrue(report['steps']['host_module']['verified'])
        self.assert_host_restored()
        self.assert_locks_held()

    def test_unknown_restore_failure_retains_locks(self):
        self.fail_boot = RuntimeError('unknown recovery effect')
        report = self.run_failure_path()
        self.assertEqual(report['steps']['boot']['error']['type'], 'RuntimeError')
        self.assertTrue(report['steps']['module']['attempted'])
        self.assert_host_restored()
        self.assert_locks_held()

    def test_all_verified_recovery_releases_own_locks(self):
        report = self.run_failure_path()
        self.assertTrue(report['recovery_verified'])
        self.assertEqual(self.phone_boot, self.previous_boot)
        self.assert_host_restored()
        self.assertTrue(all(not path.exists() for path in self.deploy.owned))
        saved, events = self.assert_saved_report(report)
        self.assertTrue(saved['recovery_verified'])
        self.assertEqual(saved['lock_state_at_report'], 'held_before_finalization')
        names = [event['event'] for event in events]
        self.assertLess(names.index('recovery_confirmed'), names.index('own_lock_removed'))

    def test_boot_restore_rejects_changed_boot_a(self):
        self.phone_boot_a = checksum(b'boot a changed during deployment')
        report = self.run_failure_path()
        self.assertFalse(report['steps']['boot']['verified'])
        self.assertIn('boot_a differs', report['steps']['boot']['error']['message'])
        self.assertTrue(report['steps']['module']['verified'])
        self.assert_locks_held()

    def test_boot_restore_requires_recorded_boot_a(self):
        self.deploy.boot_a_sha = None
        report = self.run_failure_path()
        self.assertFalse(report['steps']['boot']['verified'])
        self.assert_locks_held()

    def test_foreign_token_is_not_removed(self):
        foreign = self.deploy.owned[1]
        foreign.write_text('another owner token', encoding='utf-8')
        report = self.run_failure_path()
        self.assertTrue(report['recovery_verified'])
        self.assertFalse(self.deploy.owned[0].exists())
        self.assertEqual(foreign.read_text(encoding='utf-8'), 'another owner token')
        self.assertNotIn(mock.call('PHONE_RELEASED'), self.deploy.say.call_args_list)

    def test_host_copy_failure_attempts_other_host_files(self):
        original_copy = self.deploy.shutil.copyfile
        attempted = []
        def copy_file(source, target):
            attempted.append(Path(target))
            if Path(target).name == 'module.prop':
                raise OSError('mock host copy failure')
            return original_copy(source, target)
        with mock.patch.object(self.deploy.shutil, 'copyfile', side_effect=copy_file):
            report = self.run_failure_path()
        self.assertEqual(len(attempted), len(self.deploy.HOST_MODULE_FILES))
        self.assertFalse(report['steps']['host_module']['verified'])
        self.assert_locks_held()

    def test_previous_input_mutation_rejected_before_boot_write(self):
        self.deploy.previous_image.write_bytes(b'X' * self.deploy.size)
        report = self.run_failure_path()
        self.assertFalse(report['steps']['boot']['verified'])
        self.assertFalse(any(kind == 'rooted' and command.startswith('dd ') for kind, command in self.calls))
        self.assertTrue(report['steps']['module']['verified'])
        self.assert_locks_held()

    def test_remote_boot_corruption_rejected_before_boot_write(self):
        self.bad_remote_boot_hash = True
        report = self.run_failure_path()
        self.assertFalse(report['steps']['boot']['verified'])
        self.assertFalse(any(kind == 'rooted' and command.startswith('dd ') for kind, command in self.calls))
        self.assertTrue(report['steps']['module']['verified'])
        self.assert_locks_held()

    def test_boot_readback_failure_retains_locks(self):
        self.bad_boot_readback = True
        report = self.run_failure_path()
        self.assertFalse(report['steps']['boot']['verified'])
        self.assertTrue(report['steps']['module']['verified'])
        self.assert_locks_held()

    def test_module_readback_checks_more_than_loader_pin(self):
        self.bad_module_readback = True
        report = self.run_failure_path()
        self.assertFalse(report['steps']['module']['verified'])
        self.assertIn('module.prop', report['steps']['module']['error']['message'])
        self.assert_locks_held()

    def test_archive_corruption_does_not_extract(self):
        archive = self.deploy.backup / 'fuxi_ios_boot-module.tar'
        with archive.open('ab') as stream:
            stream.write(b'changed')
        report = self.run_failure_path()
        self.assertFalse(report['steps']['module']['verified'])
        self.assertFalse(any(kind == 'rooted' and command.startswith('tar ') for kind, command in self.calls))
        self.assert_host_restored()
        self.assert_locks_held()

    def test_host_backup_corruption_skips_only_bad_file(self):
        (self.deploy.backup / 'host-module-before/loader.size').write_bytes(b'corrupt')
        report = self.run_failure_path()
        self.assertFalse(report['steps']['host_module']['verified'])
        self.assertEqual((self.deploy.local_module / 'bin/check-pin').read_bytes(), self.original_files['bin/check-pin'])
        self.assert_locks_held()

    def test_unknown_remote_writer_does_not_start_more_phone_writes(self):
        self.deploy.pending_write = 'deploy boot_b'
        report = self.run_failure_path()
        self.assertFalse(report['recovery_verified'])
        self.assertFalse(self.calls)
        self.assert_host_restored()
        self.assert_locks_held()

    def test_interrupted_deployment_retains_locks_even_after_readback(self):
        self.deploy.injected_failure = KeyboardInterrupt('interrupted deployment')
        report = self.run_failure_path()
        self.assertTrue(all(step['verified'] for step in report['steps'].values()))
        self.assertFalse(report['recovery_verified'])
        self.assert_locks_held()

    def test_recovery_interrupt_does_not_mask_original_or_skip_other_actions(self):
        self.fail_boot = KeyboardInterrupt('interrupted boot recovery')
        report = self.run_failure_path()
        self.assertTrue(report['steps']['module']['verified'])
        self.assert_host_restored()
        self.assert_locks_held()

    def test_report_failure_retains_locks(self):
        with mock.patch.object(self.deploy, 'save_recovery_report', return_value=False):
            report = self.run_failure_path()
        self.assertTrue(report['recovery_verified'])
        self.assert_locks_held()

    def test_journal_failure_retains_locks(self):
        with mock.patch.object(self.deploy, 'recovery_event', return_value=False):
            self.run_failure_path()
        self.assert_locks_held()

    def test_lock_delete_failure_does_not_mask_deployment_failure(self):
        with mock.patch.object(Path, 'unlink', side_effect=OSError('mock token unlink failure')):
            report = self.run_failure_path()
        self.assertTrue(report['recovery_verified'])
        self.assert_locks_held()
        _, events = self.assert_saved_report(report)
        self.assertEqual(events[-1]['event'], 'lock_release_failed')

    def test_unexpected_lock_path_is_never_deleted(self):
        outside = self.deploy.workspace.parent / 'foreign-lock'
        outside.write_text(self.deploy.token, encoding='utf-8')
        self.deploy.owned.append(outside)
        self.run_failure_path()
        self.assertEqual(outside.read_text(encoding='utf-8'), self.deploy.token)
        self.assert_locks_held()

    def test_unexpected_lock_inside_workspace_is_never_deleted(self):
        unexpected = self.deploy.workspace / 'work/NOT-A-PHONE-LOCK'
        unexpected.write_text(self.deploy.token, encoding='utf-8')
        self.deploy.owned.append(unexpected)
        self.run_failure_path()
        self.assert_locks_held()

    def test_token_replaced_during_release_is_not_removed(self):
        target = self.deploy.owned[0]
        original_read = Path.read_text
        reads = 0
        def read_text(path, *arguments, **options):
            nonlocal reads
            contents = original_read(path, *arguments, **options)
            if path == target:
                reads += 1
                if reads == 2:
                    target.write_text('replacement foreign token', encoding='utf-8')
            return contents
        with mock.patch.object(Path, 'read_text', read_text):
            self.run_failure_path()
        self.assertEqual(target.read_text(encoding='utf-8'), 'replacement foreign token')
        self.assertEqual(self.deploy.owned[1].read_text(encoding='utf-8'), self.deploy.token)
        self.assertNotIn(mock.call('PHONE_RELEASED'), self.deploy.say.call_args_list)

    def test_recovery_input_outside_workspace_is_rejected(self):
        outside = self.deploy.workspace.parent / 'foreign-boot.img'
        outside.write_bytes(self.previous_boot)
        self.deploy.previous_image = outside
        report = self.run_failure_path()
        self.assertFalse(report['steps']['boot']['verified'])
        self.assertTrue(report['steps']['module']['verified'])
        self.assertEqual(outside.read_bytes(), self.previous_boot)
        self.assert_locks_held()

    def test_backup_outside_named_root_is_not_written(self):
        outside = self.deploy.workspace.parent / 'foreign-backup'
        outside.mkdir()
        self.deploy.backup = outside
        self.run_failure_path()
        self.assertEqual(list(outside.iterdir()), [])
        self.assert_locks_held()

    def test_failure_before_backup_uses_new_owned_diagnostic_directory(self):
        self.deploy.boot_changed = self.deploy.module_changed = self.deploy.host_changed = False
        self.deploy.backup_created = False
        marker = self.deploy.backup / 'foreign-marker'
        marker.write_bytes(b'not owned by this attempt')
        report = self.run_failure_path()
        self.assertTrue(report['recovery_verified'])
        self.assertTrue(all(not path.exists() for path in self.deploy.owned))
        self.assertEqual(marker.read_bytes(), b'not owned by this attempt')
        self.assertFalse(Path(report['journal']).is_relative_to(self.deploy.backup))

    def test_success_finalization_does_not_run_recovery_or_phone_calls(self):
        self.assertTrue(self.deploy.finish_deployment(True, None))
        self.assertFalse(self.calls)
        self.assertTrue(all(not path.exists() for path in self.deploy.owned))
        self.assertFalse(list(self.deploy.backup.glob('recovery-*')))

    def test_capacity_guard_accepts_exact_12gb_bytes(self):
        self.assertIsNone(self.deploy.verify_device_capacity())

    def test_capacity_guard_rejects_8gb_missing_and_malformed(self):
        for output in ('0 0 0 8', '', '0 0 12', '0 0 0 12 0', 'unknown', '0 0 0 012'):
            with self.subTest(output=output):
                self.capacity_output = output
                with self.assertRaises(ValueError):
                    self.deploy.verify_device_capacity()

    def test_wrong_capacity_blocks_both_phone_recovery_writes(self):
        self.capacity_output = '0 0 0 8'
        report = self.run_failure_path()
        self.assertFalse(report['steps']['boot']['verified'])
        self.assertFalse(report['steps']['module']['verified'])
        self.assertTrue(report['steps']['host_module']['verified'])
        self.assertFalse(any(kind == 'adb' for kind, command in self.calls))
        self.assert_host_restored()
        self.assert_locks_held()

    def test_production_capacity_guard_precedes_backup_and_writes(self):
        parsed = ast.parse(SCRIPT.read_text(encoding='utf-8'))
        production = next(node for node in parsed.body if isinstance(node, ast.Try))
        guard_index = next(index for index, statement in enumerate(production.body)
                           if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
                                  node.func.id == 'verify_device_capacity' for node in ast.walk(statement)))
        backup_index = next(index for index, statement in enumerate(production.body)
                            if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
                                   node.func.attr == 'mkdir' and isinstance(node.func.value, ast.Name) and
                                   node.func.value.id == 'backup' for node in ast.walk(statement)))
        self.assertLess(guard_index, backup_index)

    def test_one_failed_journal_event_cannot_be_cleared_by_later_success(self):
        original_event = self.deploy.recovery_event
        count = 0
        def record_event(report, event, **details):
            nonlocal count
            count += 1
            return False if count == 1 else original_event(report, event, **details)
        with mock.patch.object(self.deploy, 'recovery_event', side_effect=record_event):
            self.run_failure_path()
        self.assert_locks_held()

    def test_unexpected_recovery_exception_preserves_original_failure(self):
        with mock.patch.object(self.deploy, 'recover_deployment', side_effect=RuntimeError('unexpected recovery crash')):
            report = self.run_failure_path()
        self.assertEqual(report['unexpected_recovery_error']['message'], 'unexpected recovery crash')
        self.assert_locks_held()

    def test_unexpected_finalization_exception_preserves_original_failure(self):
        with mock.patch.object(self.deploy, 'finish_deployment', side_effect=RuntimeError('unexpected finalization crash')):
            self.run_failure_path()
        self.assert_locks_held()


if __name__ == '__main__':
    unittest.main()
