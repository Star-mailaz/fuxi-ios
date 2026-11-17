import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat
import tempfile


CONFIGURATION = Path("private/var/preferences/SystemConfiguration/com.apple.wifi.plist")


def configure(root, action):
    root = Path(root)
    if action not in ("enable", "disable") or not root.is_absolute() or root.is_symlink():
        raise ValueError("Invalid root or action")
    path = root
    for component in CONFIGURATION.parts:
        path = path / component
        information = path.lstat()
        if stat.S_ISLNK(information.st_mode):
            raise ValueError("Configuration symlinks are refused")
    if not stat.S_ISREG(information.st_mode) or not 1 <= information.st_size <= 1024 * 1024:
        raise ValueError("Unexpected configuration type or size")
    original = path.read_bytes()
    if not original.startswith(b"bplist00"):
        raise ValueError("Expected the existing binary configuration")
    value = plistlib.loads(original)
    expected = action == "disable"
    if not isinstance(value, dict) or value.get("LoggingFileEnabled") is not expected:
        raise ValueError("LoggingFileEnabled changed or has an unexpected type")
    updated = dict(value)
    updated["LoggingFileEnabled"] = not expected
    payload = plistlib.dumps(updated, fmt=plistlib.FMT_BINARY, sort_keys=False)
    decoded = plistlib.loads(payload)
    if decoded != updated or {key: entry for key, entry in decoded.items() if key != "LoggingFileEnabled"} != {
            key: entry for key, entry in value.items() if key != "LoggingFileEnabled"}:
        raise ValueError("Unrelated configuration fields changed")
    temporary = path.with_name(path.name + ".fuxi-logging.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IMODE(information.st_mode))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, information.st_uid, information.st_gid)
        os.chmod(temporary, stat.S_IMODE(information.st_mode))
        if path.read_bytes() != original:
            raise ValueError("Configuration changed before replacement")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    if path.read_bytes() != payload:
        raise ValueError("Written configuration differs")
    return {"action": action, "before": expected, "after": not expected,
            "other_fields_unchanged": True,
            "sha256_before": hashlib.sha256(original).hexdigest(),
            "sha256_after": hashlib.sha256(payload).hexdigest()}


def self_test():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / CONFIGURATION
        path.parent.mkdir(parents=True)
        original = {"LoggingFileEnabled": False, "mStageAutoJoin": True,
                    "List of known networks": [{"SSID": b"host-test", "private": b"\x00\x01\x02"}]}
        path.write_bytes(plistlib.dumps(original, fmt=plistlib.FMT_BINARY))
        path.chmod(0o640)
        report = configure(root, "enable")
        assert report["before"] is False and report["after"] is True
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
        changed = plistlib.loads(path.read_bytes())
        assert changed == original | {"LoggingFileEnabled": True}
        try:
            configure(root, "enable")
        except ValueError:
            pass
        else:
            raise AssertionError("Unexpected prior logging state accepted")
        configure(root, "disable")
        assert plistlib.loads(path.read_bytes()) == original
        for invalid in (None, 0, "false"):
            path.write_bytes(plistlib.dumps(original | {"LoggingFileEnabled": invalid},
                                           fmt=plistlib.FMT_BINARY))
            before = path.read_bytes()
            try:
                configure(root, "enable")
            except ValueError:
                assert path.read_bytes() == before
            else:
                raise AssertionError("Non-boolean logging state accepted")
        path.unlink()
        target = root / "unrelated.plist"
        target.write_bytes(plistlib.dumps(original, fmt=plistlib.FMT_BINARY))
        path.symlink_to(target)
        try:
            configure(root, "enable")
        except ValueError:
            assert plistlib.loads(target.read_bytes()) == original
        else:
            raise AssertionError("Configuration symlink accepted")
    print("WIFI_LOGGING_SELF_TEST_OK phone_operations=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--action", choices=("enable", "disable"))
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
    elif arguments.root is not None and arguments.action is not None:
        print(json.dumps(configure(arguments.root, arguments.action), sort_keys=True))
    else:
        parser.error("--root and --action are required")
