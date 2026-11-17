import argparse
import difflib
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
source = root / 'xnu/fuxi-wlan/fuxi_wlan.c'
patch = root / 'xnu/patches/0099-fuxi-wlan.patch'
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
pattern = re.compile(r'^--- (?:a/bsd/dev/fuxi_wlan\.c|/dev/null)\n\+\+\+ b/bsd/dev/fuxi_wlan\.c\n@@ -0,0 \+1,\d+ @@\n', re.M)
text = patch.read_text(encoding='utf-8')
matches = list(pattern.finditer(text))
assert len(matches) == 1
start = matches[0].start()
end = text.find('\n--- ', matches[0].end())
if end < 0:
    end = len(text)
else:
    end += 1
body = source.read_text(encoding='utf-8')
assert body.endswith('\n')
original_path = matches[0].group(0).splitlines()[0][4:]
replacement = ''.join(difflib.unified_diff([], body.splitlines(True), fromfile=original_path,
                                            tofile='b/bsd/dev/fuxi_wlan.c'))
expected = text[:start] + replacement + text[end:]
for name in ('fuxi_wlan_arena.h', 'fuxi_wlan_ath12k.h', 'fuxi_wlan_ath12k.inc',
             'fuxi_wlan_control.h', 'fuxi_wlan_ios.inc'):
    body = (source.parent / name).read_text(encoding='utf-8')
    assert body.endswith('\n') and '\r' not in body
    marker = '--- /dev/null\n+++ b/bsd/dev/' + name + '\n'
    block = ''.join(difflib.unified_diff([], body.splitlines(True), fromfile='/dev/null',
                                        tofile='b/bsd/dev/' + name))
    start = expected.find(marker)
    if start < 0:
        expected += block
    else:
        end = expected.find('\n--- ', start + len(marker))
        end = len(expected) if end < 0 else end + 1
        expected = expected[:start] + block + expected[end:]
if args.check:
    assert text == expected, 'fuxi-wlan canonical source differs from 0099'
else:
    patch.write_text(expected, encoding='utf-8', newline='\n')
print('PASS: fuxi-wlan canonical source matches 0099')
