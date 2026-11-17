import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from root_layers import SnapshotReader, digest_file, load_layers, write_backing

root = Path(__file__).resolve().parent
qemu_dir = root.parents[1] / 'candidates/vm-tools/qemu'
block_size, count = 4096, 8


def run(*arguments):
    return subprocess.run(list(map(str, arguments)), check=True, capture_output=True, text=True)


def save_layer(path, blocks, changed, parent=None):
    path.mkdir()
    (path / 'phone-blocks.txt').write_text(''.join(hashlib.sha256(value).hexdigest() + '\n' for value in blocks))
    (path / 'diff-blocks.txt').write_text(' '.join(map(str, changed)) + '\n')
    (path / 'pull.bin').write_bytes(b''.join(blocks[index] for index in changed))
    if parent:
        (path / 'parent.json').write_text(json.dumps({
            'snapshot': str(parent), 'phone_manifest_sha256': digest_file(parent / 'phone-blocks.txt'),
        }))


with tempfile.TemporaryDirectory(prefix='root-layers-test-', dir=root) as temporary:
    test_dir = Path(temporary).resolve()
    assert test_dir.parent == root and test_dir.name.startswith('root-layers-test-')
    base = test_dir / 'base.img'
    blocks = [bytes([index]) * block_size for index in range(count)]
    base.write_bytes(b''.join(blocks))
    original_hash = digest_file(base)
    blocks[0], blocks[3], blocks[7] = [bytes([value]) * block_size for value in (20, 23, 27)]
    parent = test_dir / 'parent'
    save_layer(parent, blocks, [0, 3, 7])
    blocks[2], blocks[3] = [bytes([value]) * block_size for value in (32, 33)]
    child = test_dir / 'child'
    save_layer(child, blocks, [2, 3], parent)
    layers = load_layers(child, count, block_size)
    assert len(layers) == 2
    with SnapshotReader(base, layers, block_size) as snapshot:
        assert [snapshot.block(index) for index in range(count)] == blocks
    descriptor = test_dir / 'snapshot.vmdk'
    assert write_backing(base, layers, descriptor, count, block_size) >= 5
    reconstructed = test_dir / 'reconstructed.img'
    run(qemu_dir / 'qemu-img.exe', 'convert', '-f', 'vmdk', '-O', 'raw', descriptor, reconstructed)
    assert reconstructed.read_bytes() == b''.join(blocks)
    before = {path: digest_file(path) for path in (base, parent / 'pull.bin', child / 'pull.bin')}
    overlay = test_dir / 'overlay.qcow2'
    run(qemu_dir / 'qemu-img.exe', 'create', '-f', 'qcow2', '-F', 'vmdk', '-b', descriptor, overlay)
    run(qemu_dir / 'qemu-io.exe', '-f', 'qcow2', '-c', f'write -P 0x58 {block_size} {block_size}', overlay)
    rewritten = test_dir / 'rewritten.img'
    run(qemu_dir / 'qemu-img.exe', 'convert', '-f', 'qcow2', '-O', 'raw', overlay, rewritten)
    expected = list(blocks)
    expected[1] = b'X' * block_size
    assert rewritten.read_bytes() == b''.join(expected)
    assert all(digest_file(path) == checksum for path, checksum in before.items())
    manifest_path = parent / 'phone-blocks.txt'
    manifest = manifest_path.read_bytes()
    manifest_path.write_bytes(manifest.replace(b'\n', b'\r\n'))
    try:
        load_layers(child, count, block_size)
    except AssertionError:
        pass
    else:
        raise AssertionError('changed parent manifest was accepted')
    manifest_path.write_bytes(manifest)
    pull = child / 'pull.bin'
    original = pull.read_bytes()
    pull.write_bytes(b'!' + original[1:])
    with SnapshotReader(base, load_layers(child, count, block_size), block_size) as snapshot:
        try:
            snapshot.block(2)
        except AssertionError:
            pass
        else:
            raise AssertionError('corrupt snapshot data was accepted')
print('ROOT_LAYERS_OK: parent precedence, reconstruction, writable overlay isolation and corruption rejection')
