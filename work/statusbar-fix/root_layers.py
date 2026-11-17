from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re

BLOCK = 4194304
COUNT = 5120


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_layers(snapshot, count=COUNT, block_size=BLOCK):
    layers = []
    visited = set()
    current = Path(snapshot).resolve()
    while True:
        assert current not in visited and len(visited) < 24, 'snapshot parent cycle or excessive depth'
        visited.add(current)
        manifest = current / 'phone-blocks.txt'
        hashes = manifest.read_text().split()
        indices = list(map(int, (current / 'diff-blocks.txt').read_text().split()))
        assert len(hashes) == count and all(re.fullmatch('[0-9a-f]{64}', value) for value in hashes)
        assert indices == sorted(set(indices))
        assert all(0 <= index < count for index in indices)
        pull = current / 'pull.bin'
        assert pull.stat().st_size == len(indices) * block_size
        layers.append({'root': current, 'hashes': hashes, 'positions': {
            index: position for position, index in enumerate(indices)}, 'pull': pull})
        parent_file = current / 'parent.json'
        if not parent_file.exists():
            break
        parent = json.loads(parent_file.read_text())
        current = Path(parent['snapshot']).resolve()
        assert digest_file(current / 'phone-blocks.txt') == parent['phone_manifest_sha256'], 'parent manifest changed'
    return list(reversed(layers))


class SnapshotReader:
    def __init__(self, base, layers, block_size=BLOCK):
        self.base = Path(base).resolve()
        self.layers = layers
        self.block_size = block_size
        self.stack = ExitStack()
        self.streams = {}

    def __enter__(self):
        for path in [self.base] + [layer['pull'] for layer in self.layers]:
            if path not in self.streams:
                self.streams[path] = self.stack.enter_context(path.open('rb'))
        return self

    def __exit__(self, *arguments):
        return self.stack.__exit__(*arguments)

    def block(self, index):
        source, position = self.base, index
        for layer in reversed(self.layers):
            if index in layer['positions']:
                source, position = layer['pull'], layer['positions'][index]
                break
        stream = self.streams[source]
        stream.seek(position * self.block_size)
        value = stream.read(self.block_size)
        assert len(value) == self.block_size
        if self.layers:
            assert hashlib.sha256(value).hexdigest() == self.layers[-1]['hashes'][index], f'snapshot block {index}'
        return value


def write_backing(base, layers, output, count=COUNT, block_size=BLOCK):
    base, output = Path(base).resolve(), Path(output).resolve()
    assert block_size % 512 == 0 and base.stat().st_size == count * block_size
    assert not output.exists()
    locations = [(base, index) for index in range(count)]
    for layer in layers:
        for index, position in layer['positions'].items():
            locations[index] = (layer['pull'], position)
    runs = []
    for path, position in locations:
        if runs and path == runs[-1][0] and position == runs[-1][1] + runs[-1][2]:
            runs[-1][2] += 1
        else:
            runs.append([path, position, 1])
    lines = ['# Disk DescriptorFile', 'version=1', 'encoding="UTF-8"', 'CID=fffffffe',
             'parentCID=ffffffff', 'createType="twoGbMaxExtentFlat"', '# Extent description']
    sectors = block_size // 512
    for path, position, length in runs:
        source = path.as_posix()
        assert '"' not in source and '\n' not in source and '\r' not in source
        lines.append(f'RW {length * sectors} FLAT "{source}" {position * sectors}')
    lines += ['', 'ddb.virtualHWVersion = "4"', 'ddb.adapterType = "lsilogic"',
              'ddb.geometry.heads = "255"', 'ddb.geometry.sectors = "63"',
              f'ddb.geometry.cylinders = "{max(1, count * sectors // (255 * 63))}"', '']
    descriptor = '\n'.join(lines)
    assert len(descriptor.encode()) < 1024 * 1024
    output.write_text(descriptor, encoding='utf-8', newline='\n')
    return len(runs)
