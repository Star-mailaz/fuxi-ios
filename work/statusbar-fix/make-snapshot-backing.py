import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from root_layers import BLOCK, COUNT, load_layers, write_backing

snapshot, base, output = map(Path, sys.argv[1:4])
layers = load_layers(snapshot)
runs = write_backing(base, layers, output)
qemu_img = Path(__file__).resolve().parents[2] / 'candidates/vm-tools/qemu/qemu-img.exe'
info = json.loads(subprocess.check_output([str(qemu_img), 'info', '--output=json',
                                          '-f', 'vmdk', str(output)], text=True))
assert info['virtual-size'] == BLOCK * COUNT and info['format'] == 'vmdk'
print('SNAPSHOT_BACKING', len(layers), 'layers', runs, 'extents', output.stat().st_size, 'bytes')
