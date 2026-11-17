#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import struct
import sys

tools = Path(__file__).resolve().parent
sys.path.insert(0, str(tools))
import adt

spec = importlib.util.spec_from_file_location('fuxi_ram', tools / 'mkadt-fuxi.py')
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)
layout.mkadt.d22ap_product = lambda: None
base = layout.PHYS_BASE
assert layout.memory_contains([(base, 0xc0000000), (0x980000000, 0x180000000)], base, 0x240000000)
assert not layout.memory_contains([(base, 0xc0000000), (0x980004000, 0x17fffc000)], base, 0x240000000)
assert not layout.memory_contains([(base, 0x140000000)], base, 0x240000000)
assert not layout.memory_contains([(base, 0x240000000)], base, 0)
assert not layout.memory_contains([(base, 0x240000000)], (1 << 64) - 1, 2)
original = layout.build(smp=True, gpu_reserve=True)
chosen = next(node for node in original.children if node.name == 'chosen')
chosen.props.append(('fuxi-root-extents', 0, b'preserve-existing-mapping'))
original_blob = adt.serialize(original)
for name, size, scratch in (('9g', 0x23e000000, 0xafe000000), ('full', 0x13e000000, 0x9fe000000)):
    layout.configure_ram(name)
    for root in (layout.build(smp=True, gpu_reserve=True), adt.parse(original_blob)[0]):
        root = layout.reserve_gpu(root)
        chosen = next(node for node in root.children if node.name == 'chosen')
        assert struct.unpack('<Q', chosen.prop('dram-size'))[0] == size
        assert struct.unpack('<2Q', chosen.prop('fuxi-gpu-memory')) == (scratch, 0x2000000)
        assert base + size == scratch
        assert scratch + 0x2000000 <= 1 << 36
        for offset in (0, 0xfffffe00, 0x100000000, 0x1fffffe00, 0x200000000, size - 512):
            if offset >= size:
                continue
            request = (0x47, 0x58, 0x59)[offset >> 32]
            value, index = offset & 0xffff, (offset >> 16) & 0xffff
            bank = (0x47, 0x58, 0x59).index(request)
            assert value | index << 16 | bank << 32 == offset
        if chosen.prop('fuxi-root-extents'):
            assert chosen.prop('fuxi-root-extents') == b'preserve-existing-mapping'
try:
    layout.configure_ram('12g')
except ValueError:
    pass
else:
    raise AssertionError('unsupported geometry accepted')
print('PASS: adjacent banks, gaps, overflow, 5g/9g scratch separation and preserved root mapping')
