"""模擬手機，測 phone-check.py 的 remove_ksu_module／verify_ios_root（不碰手機、不寫 fuxi_Backup）。"""
import hashlib
import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "phone-check.py"


def load():
    spec = importlib.util.spec_from_file_location("pc_under_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakePhone:
    def __init__(self, pc, extra=None):
        self.pc = pc
        self.files = {}
        for name in pc.MODULE_HOST_REFERENCES:
            self.files[name] = (pc.IOS_ENTRY / name).read_bytes()
        self.files["module.prop"] = b"id=fuxi_ios_boot\nversion=v9\n"
        self.files["action.sh"] = b"#!/system/bin/sh\nreboot\n"
        self.files["loader.sha256"] = b"x\n"
        self.files.update(extra or {})
        self.module = True
        self.mapped = False
        self.pushed = {}
        self.calls = []

    def rooted(self, script, timeout=60):
        self.calls.append(script)
        pc = self.pc
        if script.startswith("[ -e "):
            path = script.split()[2]
            present = {pc.KSU_MODULE: self.module, pc.KSU_MODULE_UPDATE: False, pc.ROOT_MAPPER: self.mapped}.get(path, False)
            return "present" if present else "absent"
        if script.startswith("for f in"):
            return "\n".join(f for f in pc.MODULE_ACTIVE_ITEMS if f in self.files)
        if script.startswith(f"cd {pc.KSU_MODULE} && find"):
            return "\n".join(f"{hashlib.sha256(v).hexdigest()}  ./{k}" for k, v in sorted(self.files.items()))
        if script.startswith("sha256sum /data/local/tmp/"):
            return hashlib.sha256(self.pushed[script.split()[1]]).hexdigest() + "  x"
        if script.startswith("chmod 755 /data/local/tmp/fuxi-inspect-fiemap"):
            return (pc.IOS_ENTRY / "expected-fiemap.txt").read_text(encoding="utf-8").strip()
        if script.startswith("chmod 755 /data/local/tmp/fuxi-check-pin"):
            return "flags_rc=0 flags=0x800000 x pin_rc=0 moved=0 y"
        if script.startswith("rm -f /data/local/tmp/"):
            self.pushed.pop(script.split()[2], None)
            return ""
        if script.startswith(f"rm -rf {pc.KSU_MODULE}"):
            self.module = False
            return ""
        if script.startswith("ls -A /data/adb/modules"):
            return ""
        raise AssertionError("unexpected rooted: " + script)

    def adb(self, *args, timeout=60):
        assert args[0] == "push", args
        self.pushed[args[2]] = Path(args[1]).read_bytes()
        return ""

    def run(self, argv, stdout=None, check=False, timeout=None, **kw):
        assert "tar -c -C /data/adb/modules fuxi_ios_boot" in argv[-1]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            d = tarfile.TarInfo("fuxi_ios_boot"); d.type = tarfile.DIRTYPE; tar.addfile(d)
            for k, v in sorted(self.files.items()):
                info = tarfile.TarInfo("fuxi_ios_boot/" + k); info.size = len(v)
                tar.addfile(info, io.BytesIO(v))
        stdout.write(buf.getvalue())


class Tests(unittest.TestCase):
    def setUp(self):
        self.pc = load()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ws = root / "fuxi_ios"
        (self.ws / "work/dualboot").mkdir(parents=True)
        (root / "fuxi_Backup").mkdir()
        self.out = self.ws / "work/dualboot/remove-ksu-test"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_remove(self, fake):
        pc = self.pc
        with mock.patch.object(pc, "rooted", fake.rooted), mock.patch.object(pc, "adb", fake.adb), \
                mock.patch.object(pc.subprocess, "run", fake.run), \
                mock.patch.object(pc, "verify_backup", lambda *a, **k: {}), \
                mock.patch.object(pc, "preserve_mtd", lambda out: {"saved": True}), \
                mock.patch.object(pc, "WORKSPACE", self.ws):
            return pc.remove_ksu_module(Path("restore"), self.out, {"active_slot": "0"})

    def test_removes_after_archive(self):
        fake = FakePhone(self.pc)
        result = self.run_remove(fake)
        self.assertEqual(result["module"], "REMOVED_AND_VERIFIED")
        self.assertFalse(fake.module)
        archive = Path(result["module_archive"]["file"])
        self.assertTrue(archive.is_file())
        self.assertIn("version=v9", result["module_archive"]["module_prop"])
        self.assertEqual(fake.pushed, {})  # 工具用完刪除
        order = [c.split()[0] + " " + c.split()[1] for c in fake.calls if c.startswith("rm -rf")]
        self.assertEqual(order, ["rm -rf"])
        rm_index = next(i for i, c in enumerate(fake.calls) if c.startswith("rm -rf"))
        pin_index = max(i for i, c in enumerate(fake.calls) if "check-pin" in c)
        self.assertLess(pin_index, rm_index)

    def test_refuses_active_module(self):
        fake = FakePhone(self.pc, extra={"service.sh": b"echo hi\n"})
        with self.assertRaisesRegex(RuntimeError, "more than the action button"):
            self.run_remove(fake)
        self.assertTrue(fake.module)

    def test_refuses_reference_mismatch(self):
        fake = FakePhone(self.pc)
        fake.files["expected-fiemap.txt"] = b"different\n"
        with self.assertRaisesRegex(RuntimeError, "Host reference differs"):
            self.run_remove(fake)
        self.assertTrue(fake.module)

    def test_refuses_mapped_root_before_removal(self):
        fake = FakePhone(self.pc)
        fake.mapped = True
        with self.assertRaisesRegex(RuntimeError, "mapped"):
            self.run_remove(fake)
        self.assertTrue(fake.module)

    def test_already_absent(self):
        fake = FakePhone(self.pc)
        fake.module = False
        self.assertEqual(self.run_remove(fake)["module"], "ALREADY_ABSENT")

    def test_refuses_slot_b(self):
        fake = FakePhone(self.pc)
        with mock.patch.object(self.pc, "rooted", fake.rooted):
            with self.assertRaisesRegex(RuntimeError, "slot a"):
                self.pc.remove_ksu_module(Path("r"), self.out, {"active_slot": "1"})


if __name__ == "__main__":
    unittest.main()
