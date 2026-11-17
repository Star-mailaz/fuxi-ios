#!/usr/bin/env python3
"""Adapt the pinned blacktop builder without changing the local build scripts."""
import argparse
import os
from pathlib import Path
import re
import runpy
import shutil

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("builder", type=Path)
args = ap.parse_args()
root = Path(__file__).resolve().parents[2]
builder = args.builder
ram_layout = os.environ.get('FUXI_RAM_LAYOUT', 'full')
if ram_layout not in ('full', '9g'):
    ap.error('FUXI_RAM_LAYOUT must be full or 9g')
ath12k_object = os.environ.get('FUXI_ATH12K_OBJECT')
if ath12k_object:
    object_path = Path(ath12k_object)
    if not object_path.is_absolute() or object_path.name != 'fuxi_ath12k.o' or not re.fullmatch(
            r'/[A-Za-z0-9_./+-]+', ath12k_object):
        ap.error('FUXI_ATH12K_OBJECT must be an absolute POSIX path without Make or shell metacharacters')
    runpy.run_path(str(root / 'tools/ci/ath12k-link.py'))['validate_bundle'](object_path.parent)
for source in sorted((root / "xnu/patches").iterdir()):
    if source.suffix not in (".sh", ".patch"):
        continue
    dest = builder / "patches" / source.name
    if source.suffix == ".sh":
        # Historical staging scripts run only for SWEET; FUXI uses the same
        # open-source pthread/HFS/BearSSL providers and SDK headers.
        text = source.read_text().replace('[[ "${MACHINE_CONFIG:-}" == SWEET ]]',
                                          '[[ "${MACHINE_CONFIG:-}" == FUXI ]]')
        dest.write_text(text)
    else:
        shutil.copyfile(source, dest)
        Path(str(dest) + ".fuxi-required").touch()

if ram_layout == '9g':
    source = root / 'xnu/variants/ram9g.patch'
    dest = builder / 'patches/0119-fuxi-memory-9g.patch'
    shutil.copyfile(source, dest)
    Path(str(dest) + '.fuxi-required').touch()

if ath12k_object:
    source = root / 'xnu/variants/ath12k-link.patch'
    dest = builder / 'patches/0120-fuxi-ath12k-link.patch'
    shutil.copyfile(source, dest)
    Path(str(dest) + '.fuxi-required').touch()

p = builder / "build.sh"
text = p.read_text()


def replace(old, new):
    global text
    if text.count(old) != 1:
        raise SystemExit("pinned builder changed: " + old)
    text = text.replace(old, new)


replace('ARCHS="x86_64 arm64e" VALID_ARCHS="x86_64 arm64e"',
        'ARCHS="x86_64 arm64e arm64" VALID_ARCHS="x86_64 arm64e arm64"')
replace('warning "Skipping patch ${PATCH}',
        'if [ -e "${PATCH}.fuxi-required" ]; then\n'
        '                    error "Required Fuxi patch failed: ${PATCH}: ${APPLY_CHECK}"\n'
        '                    exit 1\n'
        '                fi\n'
        '                warning "Skipping patch ${PATCH}')
p.write_text(text)
