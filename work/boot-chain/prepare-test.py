import argparse
import hashlib
import re
import shutil
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument('chain')
parser.add_argument('name')
arguments = parser.parse_args()
assert re.fullmatch(r'chain-[a-z0-9-]+', arguments.chain)
assert re.fullmatch(r'native-[a-z0-9-]+-loader', arguments.name)
workspace = Path(__file__).resolve().parents[2]
storage = workspace / 'work/Codex-Xiaomi13-GPU-20261109'
chain = Path(__file__).resolve().parent / arguments.chain
output = storage / arguments.name
assert not output.exists()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(path):
    return {name.strip().lstrip('*'): checksum
            for checksum, name in (line.split(maxsplit=1) for line in path.read_text().splitlines())}


build = (chain / 'build.txt').read_text().splitlines()
assert 'force_linux=False' in build
payload_name = next(line.removeprefix('payload from ') for line in build if line.startswith('payload from '))
assert re.fullmatch(r'native-[a-z0-9-]+-loader', payload_name)
source = storage / payload_name
source_sums = manifest(source / 'sha256.txt')
chain_sums = manifest(chain / 'sha256.txt')
assert digest(source / 'payload.bin') == source_sums['payload.bin'] == chain_sums['payload.bin']
assert digest(chain / 'boot.img') == chain_sums['boot.img']
assert (chain / 'boot.img').read_bytes().count((source / 'payload.bin').read_bytes()) == 1
output.mkdir()
for name in ('payload.bin', 'source.txt', 'private.adt', 'memory-layout.json'):
    if (source / name).is_file():
        shutil.copyfile(source / name, output / name)
shutil.copyfile(chain / 'boot.img', output / 'boot.img')
(output / 'sha256.txt').write_text(
    f'{source_sums["kernel.development.fuxi"]}  kernel.development.fuxi\n'
    f'{source_sums["payload.bin"]}  payload.bin\n'
    f'{chain_sums["boot.img"]}  boot.img\n', newline='\n')
(output / 'chain-source.txt').write_text(arguments.chain + '\n' + payload_name + '\n', newline='\n')
print('CHAIN_TEST_READY', arguments.name, chain_sums['boot.img'])
