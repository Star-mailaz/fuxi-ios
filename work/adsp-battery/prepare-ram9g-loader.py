import os
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

workspace = Path(r'D:\xiaomi13\fuxi_ios')
storage = workspace / 'work/Codex-Xiaomi13-GPU-20261109'
tools = workspace / 'work/adsp-battery/ksrc/tools'
compiler = Path(os.environ.get('LOCALAPPDATA', ''), r'Android\Sdk\ndk\26.1.10909125\toolchains\llvm\prebuilt\windows-x86_64\bin')
sys.path.insert(0, str(tools))
import adt
import mkpayload

parser = argparse.ArgumentParser()
parser.add_argument('name')
parser.add_argument('source')
parser.add_argument('artifact')
parser.add_argument('--live-fdt', type=Path,
                    default=workspace / 'work/hw-survey/fuxi-live-20261116.dtb')
pmic_options = parser.add_mutually_exclusive_group()
pmic_options.add_argument('--pmic-survey', action='store_true')
pmic_options.add_argument('--pmic-torch-pulse', action='store_true')
pmic_options.add_argument('--pmic-torch-runtime', action='store_true')
parser.add_argument('--torch-audit', action='store_true')
parser.add_argument('--battery-audit', action='store_true')
parser.add_argument('--battery-get-pause-ms', type=int, choices=(0, 130000), default=0)
parser.add_argument('--battery-get-pause-delay-ms', type=int, default=0)
parser.add_argument('--rtc-calibration', type=Path)
parser.add_argument('--rtc-adt', action='store_true',
                    help='Carry the calibrated offset in ADT /chosen fuxi,rtc-offset instead of the full command line')
parser.add_argument('--statusbar-height', type=int, choices=range(30, 151), metavar='PX')
parser.add_argument('--statusbar-check', action='store_true')
parser.add_argument('--idle', action='store_true')
parser.add_argument('--statusbar-inject', action='store_true')
parser.add_argument('--haptic-probe', action='store_true')
parser.add_argument('--bluetooth-survey', action='store_true')
parser.add_argument('--ram-layout', choices=('full', '9g'), default='9g')
parser.add_argument('--ram-sku', choices=('auto', '8g', '12g'), default='auto')
parser.add_argument('--ramtest', action='store_true')
parser.add_argument('--ramtest-mib', type=int, choices=(128, 512), default=128)
parser.add_argument('--tap-script')
parser.add_argument('--tap-script-adt', action='store_true')
args = parser.parse_args()
if args.idle and args.statusbar_check:
    raise ValueError('Idle observation and synthetic status bar input are mutually exclusive')
if not 0 <= args.battery_get_pause_delay_ms <= 60000:
    raise ValueError('Battery GET pause delay must be between 0 and 60000 ms')
if args.battery_get_pause_delay_ms and not args.battery_get_pause_ms:
    raise ValueError('Battery GET pause delay requires an explicit pause duration')
assert not args.ramtest or args.ram_layout == '9g'
assert args.ramtest or args.ramtest_mib == 128
assert not args.tap_script_adt or args.statusbar_check
assert not args.torch_audit or args.pmic_torch_runtime
pmic_mode = 3 if args.pmic_torch_runtime else 2 if args.pmic_torch_pulse else 1 if args.pmic_survey else 0
assert re.fullmatch(r'native-[a-z0-9-]+-loader', args.name)
assert re.fullmatch(r'native-[a-z0-9-]+-loader', args.source)
assert re.fullmatch(r'kernel-[a-z0-9-]+-artifact', args.artifact)
source = storage / args.source
artifact = storage / args.artifact
output = storage / args.name
assert not output.exists()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(path):
    return {name.strip().lstrip('*'): checksum
            for checksum, name in (line.split(maxsplit=1) for line in path.read_text().splitlines())}


source_sums = manifest(source / 'sha256.txt')
assert digest(source / 'payload.bin') == source_sums['payload.bin']
assert digest(source / 'boot.img') == source_sums['boot.img']
kernel = artifact / 'kernel.development.fuxi'
assert digest(kernel) == manifest(artifact / 'SHA256SUMS')['kernel.development.fuxi']
data = (source / 'payload.bin').read_bytes()
assert data[:8] == b'SWEETXNU' and struct.unpack_from('<I', data, 8)[0] == 1
adt_offset, adt_size = struct.unpack_from('<2Q', data, 32)
tree, consumed = adt.parse(data[adt_offset:adt_offset + adt_size])
assert consumed == adt_size
chosen = next(node for node in tree.children if node.name == 'chosen')
original_props = {name: value for name, _, value in chosen.props}
command_line = data[72:680].split(b'\0', 1)[0].decode('ascii')
if args.statusbar_check or args.idle:
    original_arguments = command_line.split()
    assert not any(argument.startswith(('fuxitaps=', 'fuxitapcmd=')) for argument in original_arguments)
    test_arguments = [argument for argument in original_arguments
                      if not argument.startswith(('fuxitour=', 'fuxitourhold='))]
    assert len(original_arguments) - len(test_arguments) == 2
    if args.idle:
        if args.tap_script is not None or args.tap_script_adt:
            raise ValueError('Idle observation cannot carry synthetic input')
        command_line = ' '.join(test_arguments)
    else:
        tap_script = args.tap_script or 's540,2390,540,999;t148,570'
        assert re.fullmatch(r'[a-z0-9,;]+', tap_script)
        if args.tap_script_adt:
            assert 1 <= len(tap_script.encode('ascii')) < 400
            assert b'FUXI TAPS: using ADT command' in kernel.read_bytes(), 'kernel lacks ADT tap commands'
            command_line = ' '.join(test_arguments + ['fuxitaps=85'])
        else:
            command_line = ' '.join(test_arguments + ['fuxitaps=85', 'fuxitapcmd=' + tap_script])
    assert len(command_line.encode('ascii')) < 608
else:
    assert args.tap_script is None

if args.bluetooth_survey:
    assert not any(argument.startswith('fuxibt=') for argument in command_line.split())
    assert b'FUXI BT: survey status=' in kernel.read_bytes(), 'kernel lacks the Bluetooth survey'
    command_line += ' fuxibt=1'
    assert len(command_line.encode('ascii')) < 608

if any(argument.startswith(('fuxibatpause=', 'fuxibatpausedelay='))
       for argument in command_line.split()):
    raise ValueError('Source already carries a battery GET pause diagnostic')
if args.battery_get_pause_ms:
    if b'FUXI BATTERY: poll-pause %s' not in kernel.read_bytes():
        raise ValueError('Kernel lacks the production battery GET pause diagnostic')
    command_line += f' fuxibatpause={args.battery_get_pause_ms}'
    if args.battery_get_pause_delay_ms:
        command_line += f' fuxibatpausedelay={args.battery_get_pause_delay_ms}'
    if len(command_line.encode('ascii')) >= 608:
        raise ValueError('Battery GET pause diagnostic exceeds the v1 command line')

rtc_record = None
if any(argument.startswith(('fuxirtc=', 'fuxirtcoffset=')) for argument in command_line.split()):
    raise ValueError('Source already carries an RTC override; fresh calibration is required')
if args.rtc_calibration:
    rtc_spec = importlib.util.spec_from_file_location('rtc_calibration', Path(__file__).with_name('rtc-calibration.py'))
    rtc_module = importlib.util.module_from_spec(rtc_spec)
    rtc_spec.loader.exec_module(rtc_module)
    rtc_record = rtc_module.load(args.rtc_calibration)
    if b'FUXI RTC: clock set, now=' not in kernel.read_bytes():
        raise ValueError('Kernel lacks the measured RTC offset path')
    if args.rtc_adt:
        # Daily command lines are already 607 bytes; the kernel falls back to this ADT property.
        if b'fuxi,rtc-offset' not in kernel.read_bytes():
            raise ValueError('Kernel lacks the ADT RTC offset fallback')
    else:
        command_line += f' fuxirtcoffset={rtc_record["offset_seconds"]}'
    if len(command_line.encode('ascii')) >= 608:
        raise ValueError('RTC calibration exceeds the v1 command line')
elif args.rtc_adt:
    raise ValueError('--rtc-adt needs --rtc-calibration')

spec = importlib.util.spec_from_file_location('ram9g_adt', tools / 'mkadt-fuxi.py')
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)
layout.configure_ram(args.ram_layout)
sku_metadata = layout.validate_live(args.live_fdt, True, args.ram_sku)
tree = layout.reserve_gpu(tree)
chosen = next(node for node in tree.children if node.name == 'chosen')
new_props = {name: value for name, _, value in chosen.props}
assert {name: value for name, value in original_props.items()
        if name not in ('dram-size', 'fuxi-gpu-memory', 'fuxi,ram-sku')} == {
            name: value for name, value in new_props.items()
            if name not in ('dram-size', 'fuxi-gpu-memory', 'fuxi,ram-sku')}
if pmic_mode:
    chosen.props = [(name, flags, value) for name, flags, value in chosen.props
                    if name != 'fuxi,pmic']
    chosen.props.append(('fuxi,pmic', 0, struct.pack('<I', pmic_mode)))
    new_props = {name: value for name, _, value in chosen.props}
    assert new_props['fuxi,pmic'] == struct.pack('<I', pmic_mode)
    assert {name: value for name, value in original_props.items()
            if name not in ('dram-size', 'fuxi-gpu-memory', 'fuxi,pmic', 'fuxi,ram-sku')} == {
                name: value for name, value in new_props.items()
                if name not in ('dram-size', 'fuxi-gpu-memory', 'fuxi,pmic', 'fuxi,ram-sku')}
if args.statusbar_height is not None:
    previous_shape = chosen.prop('fuxi,sbshape') or struct.pack('<I', 300098)
    assert len(previous_shape) == 4
    previous_value = struct.unpack('<I', previous_shape)[0] or 300098
    width = previous_value // 1000
    assert 30 <= width <= 627 and 30 <= previous_value % 1000 <= 150
    shape = struct.pack('<I', width * 1000 + args.statusbar_height)
    chosen.props = [(name, flags, value) for name, flags, value in chosen.props
                    if name != 'fuxi,sbshape']
    chosen.props.append(('fuxi,sbshape', 0, shape))
    assert chosen.prop('fuxi,sbshape') == shape
if args.tap_script_adt:
    chosen.props = [(name, flags, value) for name, flags, value in chosen.props
                    if name != 'fuxi,tapcmd']
    chosen.props.append(('fuxi,tapcmd', 0, tap_script.encode('ascii') + b'\0'))
    assert chosen.prop('fuxi,tapcmd') == tap_script.encode('ascii') + b'\0'
for name, enabled in (('fuxi,inject', args.statusbar_inject), ('fuxi,ramtest', args.ramtest),
                      ('fuxi,haptic', args.haptic_probe), ('fuxi,torchaudit', args.torch_audit),
                      ('fuxi,batteryaudit', args.battery_audit)):
    if enabled:
        chosen.props = [(key, flags, value) for key, flags, value in chosen.props if key != name]
        value = 2 if name == 'fuxi,inject' else 2 if name == 'fuxi,ramtest' and args.ramtest_mib == 512 else 1
        chosen.props.append((name, 0, struct.pack('<I', value)))
final_props = {name: value for name, _, value in chosen.props}
if rtc_record is not None and args.rtc_adt:
    chosen.props = [(key, flags, value) for key, flags, value in chosen.props if key != 'fuxi,rtc-offset']
    chosen.props.append(('fuxi,rtc-offset', 0, struct.pack('<I', rtc_record['offset_seconds'])))
    final_props = {name: value for name, _, value in chosen.props}
allowed_props = ('dram-size', 'fuxi-gpu-memory', 'fuxi,pmic', 'fuxi,sbshape', 'fuxi,inject', 'fuxi,rtc-offset',
                 'fuxi,ramtest', 'fuxi,tapcmd', 'fuxi,haptic', 'fuxi,torchaudit', 'fuxi,ram-sku',
                 'fuxi,batteryaudit')
assert {name: value for name, value in original_props.items() if name not in allowed_props} == {
    name: value for name, value in final_props.items() if name not in allowed_props}
public_tree, _ = adt.parse((artifact / 'fuxi.adt').read_bytes())
public_chosen = next(node for node in public_tree.children if node.name == 'chosen')
assert public_chosen.prop('dram-size') == struct.pack('<Q', layout.MEM_SIZE)
assert public_chosen.prop('fuxi-gpu-memory') == struct.pack('<2Q', layout.GPU_BASE, layout.GPU_SIZE)
expected_memory, expected_gpu = ((0x23e000000, 0xafe000000) if args.ram_layout == '9g'
                                 else (0x13e000000, 0x9fe000000))
assert layout.MEM_SIZE == expected_memory and layout.GPU_BASE == expected_gpu
output.mkdir()
if rtc_record is not None:
    (output / 'rtc-calibration.json').write_text(json.dumps(rtc_record, ensure_ascii=False, indent=2) + '\n',
                                               encoding='utf-8', newline='\n')
private_tree = output / 'private.adt'
private_tree.write_bytes(adt.serialize(tree))
payload = output / 'payload.bin'
subprocess.run([sys.executable, str(tools / 'mkpayload.py'), str(kernel), str(private_tree), str(payload),
                '--cmdline', command_line], check=True, stdout=subprocess.DEVNULL)
packed = payload.read_bytes()
assert struct.unpack_from('<2Q', packed, 56) == (layout.PHYS_BASE, layout.MEM_SIZE)
assert packed[72:680] == command_line.encode('ascii').ljust(608, b'\0')
packed_offset, packed_size = struct.unpack_from('<2Q', packed, 32)
assert packed[packed_offset:packed_offset + packed_size] == private_tree.read_bytes()

firmware = [workspace / 'firmware/gmu_gen70200.bin', workspace / 'firmware/a740_sqe_sheng.fw',
            workspace / 'work/xiaomi13-ios-gpu-20261108/a740-zap-active-odm.mbn']
pinned_firmware = ['1a2a419c39046d3141fc5fed5aa7f971de2db40cc7a1d89693c3e26fad64dd98',
                   '6d38046654333a6a5a4ee77ab67abc24e3c0c5c68237513afe98e94da8fc9fcc',
                   'cad0dcb2daaa382eebc94ef65f3285b91b045c8976781f6a80910ca21c933a05']
assembly = ['.section .gpu_fw,"a"']
for label, path, expected in zip(('gpu', 'sqe', 'zap'), firmware, pinned_firmware):
    assert digest(path) == expected
    assembly += ['.balign 4', f'.global _{label}_fw_start', f'_{label}_fw_start:',
                 '.incbin ' + json.dumps(path.as_posix()),
                 f'.global _{label}_fw_end', f'_{label}_fw_end:']
(output / 'gpu-fw.S').write_text('\n'.join(assembly) + '\n', encoding='utf-8', newline='\n')
(output / 'payload.S').write_text('.section .payload,"a"\n.incbin ' +
                                  json.dumps(payload.as_posix()) + '\n', encoding='utf-8', newline='\n')

shim = workspace / 'ios-fuxi/shim'
flags = ['--target=aarch64-none-elf', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
         '-fno-pic', '-fno-stack-protector', '-mgeneral-regs-only', '-mstrict-align',
         '-Wall', '-Wextra', '-Werror', '-DFUXI=1', '-DFUXI_XNU_LOADER=1',
         '-I' + str(shim)]
if args.ram_layout == '9g':
    flags.append('-DFUXI_RAM_9G=1')
sources = [shim / 'fuxi-loader/start.S', shim / 'fuxi-loader/loader.c', shim / 'console.c',
           shim / 'fuxi-probe/probe.c', output / 'gpu-fw.S', output / 'payload.S']
objects = []
for path in sources:
    target = output / (path.stem + '.o')
    subprocess.run([str(compiler / 'clang.exe'), *flags, '-c', str(path), '-o', str(target)], check=True)
    if path.suffix == '.c':
        relocations = subprocess.check_output([str(compiler / 'llvm-readelf.exe'), '-r', str(target)], text=True)
        assert 'R_AARCH64_ABS' not in relocations, path
    objects.append(target)
subprocess.run([str(compiler / 'ld.lld.exe'), '-T', str(shim / 'fuxi-loader/loader.ld'),
                '--build-id=none', *map(str, objects), '-o', str(output / 'loader.elf')], check=True)
subprocess.run([str(compiler / 'llvm-objcopy.exe'), '-O', 'binary', str(output / 'loader.elf'),
                str(output / 'Image')], check=True)
image = (output / 'Image').read_bytes()
assert struct.unpack_from('<Q', image, 16)[0] == len(image) and image[56:60] == b'ARM\x64'
assert image.count(packed) == 1
for path in firmware:
    assert image.count(path.read_bytes()) == 1
subprocess.run([sys.executable, str(workspace / 'uefi-fuxi/Resources/Scripts/mkbootimg.py'),
                '--header_version', '4', '--kernel', str(output / 'Image'), '--os_version', '16.0.0',
                '--os_patch_level', '2026-08', '-o', str(output / 'boot.img')], check=True)
boot = (output / 'boot.img').read_bytes()
assert boot[:8] == b'ANDROID!' and boot.count(image) == 1
(output / 'sha256.txt').write_text(
    f'{digest(kernel)}  kernel.development.fuxi\n{digest(payload)}  payload.bin\n'
    f'{digest(output / "boot.img")}  boot.img\n', encoding='utf-8', newline='\n')
(output / 'source.txt').write_text(f'{args.source}\n{args.artifact}\n', encoding='utf-8', newline='\n')
(output / 'memory-layout.json').write_text(json.dumps({
    'layout': args.ram_layout, 'base': layout.PHYS_BASE, 'usable': layout.MEM_SIZE,
    **sku_metadata,
    'scratch': layout.GPU_BASE, 'scratch_size': layout.GPU_SIZE,
    'live_fdt_sha256': digest(args.live_fdt),
    'pmic_survey': args.pmic_survey,
    'pmic_mode': struct.unpack('<I', chosen.prop('fuxi,pmic') or bytes(4))[0],
    'torch_audit': args.torch_audit,
    'battery_audit': args.battery_audit,
    'battery_get_pause_ms': args.battery_get_pause_ms,
    'battery_get_pause_delay_ms': args.battery_get_pause_delay_ms,
    'rtc_calibration_sha256': digest(output / 'rtc-calibration.json') if rtc_record is not None else None,
    'haptic_probe': args.haptic_probe,
    'bluetooth_survey': args.bluetooth_survey,
    'statusbar_shape': struct.unpack('<I', chosen.prop('fuxi,sbshape') or bytes(4))[0],
    'statusbar_check': args.statusbar_check,
    'idle': args.idle,
    'tap_script_adt': args.tap_script_adt,
    'ramtest': args.ramtest,
    'ramtest_mib': args.ramtest_mib if args.ramtest else 0,
}, indent=2) + '\n', encoding='utf-8', newline='\n')
inputs = sorted({path for path in shim.rglob('*') if path.is_file()
                 and path.suffix in ('.c', '.h', '.S', '.ld')})
(output / 'source-input-sha256.txt').write_text(
    ''.join(f'{digest(path)}  {path.relative_to(shim).as_posix()}\n' for path in inputs),
    encoding='utf-8', newline='\n')
print('LOADER_BUILT', args.ram_layout, output)
print('RAM', hex(layout.PHYS_BASE), hex(layout.MEM_SIZE), 'GPU', hex(layout.GPU_BASE))
print('boot.img', digest(output / 'boot.img'))
