#!/usr/bin/env python3
"""Adapt a successful menu build to the existing loader safety/monitor layout.

Reuses work/boot-chain/prepare-test.py's metadata copying. No phone operations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

workspace = Path(__file__).resolve().parents[1]
storage = workspace / "work/Codex-Xiaomi13-GPU-20261109"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate", type=Path)
    p.add_argument("name")
    a = p.parse_args()
    if not re.fullmatch(r"native-[a-z0-9-]+-loader", a.name):
        raise ValueError("Unsafe wrapper name")
    candidate = a.candidate.resolve()
    report = json.loads((candidate / "report.json").read_text(encoding="utf-8"))
    if report["result"] != "ok" or digest(candidate / "boot.img") != report["candidate"]["sha256"]:
        raise ValueError("Candidate did not pass build/hash verification")
    source = storage / report["payload"]
    if digest(source / "payload.bin") != report["payload_sha256"]:
        raise ValueError("Payload changed")
    output = storage / a.name
    output.mkdir(exist_ok=False)
    for name in ("payload.bin", "source.txt", "private.adt", "memory-layout.json", "rtc-calibration.json"):
        if (source / name).is_file():
            shutil.copyfile(source / name, output / name)
    shutil.copyfile(candidate / "boot.img", output / "boot.img")
    (output / "sha256.txt").write_text(
        f'{report["kernel_sha256"]}  kernel.development.fuxi\n'
        f'{report["payload_sha256"]}  payload.bin\n'
        f'{report["candidate"]["sha256"]}  boot.img\n', encoding="utf-8", newline="\n")
    (output / "menu-source.json").write_text(json.dumps({"candidate": str(candidate), "report": report},
                                                        ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (candidate / "phone-wrapper.txt").write_text(a.name + "\n", encoding="utf-8", newline="\n")
    print("MENU_PHONE_WRAPPER_READY", output)


if __name__ == "__main__":
    main()
