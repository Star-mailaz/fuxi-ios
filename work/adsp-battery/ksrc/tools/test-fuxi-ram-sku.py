import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import adt

specification = importlib.util.spec_from_file_location('fuxi_ram_sku_layout', TOOLS / 'mkadt-fuxi.py')
layout = importlib.util.module_from_spec(specification)
specification.loader.exec_module(layout)
fixture_specification = importlib.util.spec_from_file_location('fuxi_ram_sku_fixture', TOOLS / 'test-fuxi-ram-inventory.py')
fixtures = importlib.util.module_from_spec(fixture_specification)
fixture_specification.loader.exec_module(fixtures)
layout.mkadt.d22ap_product = lambda: None


def nodes(capacity=12):
    result = fixtures.fixture_nodes(((layout.PHYS_BASE, 0xc0000000), (0x980000000, 0x180000000)))
    result['/']['model'] = b'Qualcomm Technologies, Inc. 8550 fuxi\0'
    result['/memory']['ddr_size'] = struct.pack('>I', capacity)
    result['/reserved-memory/splash_region'] = {'reg': fixtures.regs((layout.FB, layout.FB_SIZE))}
    result['/soc'] = {'#address-cells': fixtures.cells(1), '#size-cells': fixtures.cells(1)}
    result['/soc/interrupt-controller@17100000'] = {
        'reg': struct.pack('>4I', layout.GICD, 0x10000, layout.GICR, layout.GICR_SIZE)}
    result['/soc/ufshc@1d84000'] = {'reg': struct.pack('>II', 0x1d84000, 0x3000)}
    return result


class RamSkuTests(unittest.TestCase):
    def setUp(self):
        layout.configure_ram('9g')

    def validate(self, fixture, requested='auto', reservations=()):
        with tempfile.TemporaryDirectory(prefix='fuxi-ram-sku-') as temporary:
            capture = Path(temporary) / 'synthetic.dtb'
            capture.write_bytes(fixtures.fdt_blob(fixture, reservations))
            return layout.validate_live(capture, True, requested)

    def test_explicit_12gb_is_separate_from_9g_usable(self):
        for requested in ('auto', '12g'):
            result = self.validate(nodes(), requested)
            self.assertEqual(result['ram_sku'], '12g')
            self.assertEqual(result['xnu_usable_bytes'], 9184 * 1024**2)
            self.assertTrue(result['source_sku_verified'])
            self.assertFalse(result['runtime_sku_verified'])

    def test_requested_sku_mismatch(self):
        for fixture, requested in ((nodes(), '8g'), (nodes(8), '12g')):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, 'differs'):
                self.validate(fixture, requested)

    def test_8gb_cannot_use_12gb_geometry_even_if_advertised(self):
        for configuration in ('full', '9g'):
            layout.configure_ram(configuration)
            with self.subTest(configuration=configuration), self.assertRaisesRegex(ValueError, 'own measured'):
                self.validate(nodes(8))

    def test_missing_or_malformed_sku_is_not_inferred(self):
        for raw in (None, b'', b'\x0c', struct.pack('>Q', 12)):
            fixture = nodes()
            if raw is None:
                del fixture['/memory']['ddr_size']
            else:
                fixture['/memory']['ddr_size'] = raw
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'explicit u32'):
                self.validate(fixture)

    def test_unsupported_or_wrong_endian_sku(self):
        for capacity in (0, 4, 6, 16, 0x0c000000):
            with self.subTest(capacity=capacity), self.assertRaisesRegex(ValueError, 'unsupported'):
                self.validate(nodes(capacity))

    def test_layout_capacity_does_not_override_sku(self):
        fixture = nodes()
        fixture['/memory']['reg'] = fixtures.regs((layout.PHYS_BASE, 0x140000000))
        with self.assertRaisesRegex(ValueError, 'outside advertised'):
            self.validate(fixture)

    def test_reservations_remain_enforced(self):
        for reservations in (((layout.GPU_BASE, 0x4000),), ((layout.PHYS_BASE, 0x4000),)):
            with self.subTest(reservations=reservations), self.assertRaisesRegex(ValueError, 'reserve map'):
                self.validate(nodes(), reservations=reservations)

    def test_sku_tag_preserves_existing_root_mapping(self):
        tree = layout.build(smp=True, gpu_reserve=True)
        chosen = next(node for node in tree.children if node.name == 'chosen')
        chosen.props.append(('fuxi-root-extents', 0, b'host-only-root-mapping'))
        chosen.props = [prop for prop in chosen.props if prop[0] != 'fuxi,ram-sku']
        restored = layout.reserve_gpu(adt.parse(adt.serialize(tree))[0])
        chosen = next(node for node in restored.children if node.name == 'chosen')
        self.assertEqual(chosen.prop('fuxi,ram-sku'), struct.pack('<I', 12))
        self.assertEqual(chosen.prop('fuxi-root-extents'), b'host-only-root-mapping')
        before = len(chosen.props)
        layout.reserve_gpu(restored)
        self.assertEqual(len(chosen.props), before)
        chosen.props = [(name, flags, struct.pack('<I', 8) if name == 'fuxi,ram-sku' else value)
                        for name, flags, value in chosen.props]
        with self.assertRaisesRegex(ValueError, 'template ADT physical RAM SKU'):
            layout.reserve_gpu(restored)

    def test_configuration_names_are_not_skus(self):
        for requested in ('9g', 'full', '', None, 12):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, 'unsupported'):
                layout.validate_ram_sku(nodes(), requested)


if __name__ == '__main__':
    unittest.main()
