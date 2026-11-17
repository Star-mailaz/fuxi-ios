import os
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.request

DIRECTORY = Path(__file__).resolve().parent
specification = importlib.util.spec_from_file_location('phone_readthrough', DIRECTORY / 'phone-readthrough.py')
phone = importlib.util.module_from_spec(specification)
specification.loader.exec_module(phone)
ROOT_PATH = '/data/gsi/codexnative1108b/codexnative_root_1108b.img.0000'


def decode_file(record, directory, contents=None):
    name = record['runtime_path']
    if name not in ('/usr/sbin/BlueTool', '/usr/sbin/bluetoothd') and not name.startswith('/usr/local/share/fuxi/wlan/'):
        raise ValueError('Unexpected runtime asset path')
    path = (directory / name.lstrip('/')).resolve()
    if directory.resolve() not in path.parents or '..' in Path(name).parts:
        raise ValueError('Runtime asset escapes output directory')
    if contents is None:
        contents = base64.b64decode(record['data_base64'], validate=True)
    if len(contents) != record['bytes'] or hashlib.sha256(contents).hexdigest() != record['sha256']:
        raise ValueError('Extracted asset checksum or length differs')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(contents)
    return {key: value for key, value in record.items() if key != 'data_base64'} | {'host_path': str(path)}


@contextmanager
def receiver(directory):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/asset' or self.headers.get('X-Fuxi-Token') != self.server.token:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 4 <= length <= 32 * 1024 * 1024 + 8196:
                    raise ValueError('Invalid transfer length')
                header = self.rfile.read(4)
                if len(header) != 4:
                    raise ValueError('Short transfer header')
                metadata_size = struct.unpack('>I', header)[0]
                if not 1 <= metadata_size <= 8192 or metadata_size > length - 4:
                    raise ValueError('Invalid metadata length')
                metadata = self.rfile.read(metadata_size)
                contents = self.rfile.read(length - metadata_size - 4)
                if len(metadata) + len(contents) + 4 != length:
                    raise ValueError('Short asset transfer')
                record = json.loads(metadata)
                if record['runtime_path'] in self.server.files:
                    raise ValueError('Repeated runtime file')
                self.server.files[record['runtime_path']] = decode_file(record, self.server.directory, contents)
                phone.say('ASSET_RECEIVED', record['runtime_path'], record['bytes'])
            except Exception as error:
                self.server.failures.append(str(error))
                self.send_error(400)
                return
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'OK')

        def log_message(self, format, *arguments):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.directory = directory
    server.files = {}
    server.failures = []
    server.token = secrets.token_hex(24)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def self_test():
    with tempfile.TemporaryDirectory(prefix='fuxi-root-assets-') as temporary:
        directory = Path(temporary)
        contents = b'bounded-read-only-asset'
        record = {'runtime_path': '/usr/sbin/BlueTool', 'bytes': len(contents),
                  'sha256': hashlib.sha256(contents).hexdigest(),
                  'data_base64': base64.b64encode(contents).decode('ascii')}
        result = decode_file(record, directory)
        assert Path(result['host_path']).read_bytes() == contents and 'data_base64' not in result
        for changes in ({'runtime_path': '/usr/local/share/fuxi/wlan/../../../../outside'},
                        {'runtime_path': '/private/var/anything'}, {'bytes': 0}, {'sha256': '0' * 64}):
            try:
                decode_file(record | changes, directory)
            except ValueError:
                pass
            else:
                raise AssertionError('Invalid asset accepted')
        with receiver(directory / 'transferred') as server:
            metadata = json.dumps({key: value for key, value in record.items() if key != 'data_base64'}).encode('utf-8')
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/asset',
                                             data=struct.pack('>I', len(metadata)) + metadata + contents,
                                             headers={'X-Fuxi-Token': server.token}, method='POST')
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200 and response.read() == b'OK'
            assert not server.failures and len(server.files) == 1
            assert Path(server.files['/usr/sbin/BlueTool']['host_path']).read_bytes() == contents
    print('ROOT_ASSETS_SELF_TEST_OK')


def inspect(arguments):
    output = Path(arguments.output).resolve()
    if output.parent != DIRECTORY or output.exists() or not re.fullmatch('inspect-[a-z0-9-]+', output.name):
        raise ValueError('Use a new inspect directory under statusbar-fix')
    if phone.run(['adb', '-s', arguments.serial, 'shell', 'getprop', 'sys.boot_completed']).strip() != b'1':
        raise RuntimeError('Android is not ready')
    output.mkdir()
    mapped = False
    with phone.phone_locks(output.name):
        try:
            phone.say('PHONE_READ_ONLY_START', output.name)
            phone.say(phone.adb(arguments.serial, f'{phone.MANAGER} map').decode().strip())
            mapped = True
            verification = phone.run([sys.executable, '-X', 'utf8',
                                      phone.ROOT / 'work/xiaomi13-ios-gpu-20261108/verify-native-map.py'],
                                     cwd=phone.ROOT / 'work/Codex-Xiaomi13-GPU-20261109', timeout=120)
            (output / 'mapping.txt').write_bytes(verification)
            device = phone.adb(arguments.serial, f'readlink -f {phone.MAPPER}').decode().strip()
            if not re.fullmatch('/dev/block/dm-[0-9]+', device):
                raise RuntimeError('Unexpected mapped device')
            if int(phone.adb(arguments.serial, f'blockdev --getsize64 {phone.MAPPER}')) != phone.SIZE:
                raise RuntimeError('Unexpected root size')
            mounts = phone.adb(arguments.serial, 'cat /proc/mounts').decode().splitlines()
            if any(line.split()[0] in (device, phone.MAPPER) for line in mounts):
                raise RuntimeError('The root is mounted on the phone')
            share = output / 'share'
            share.mkdir()
            shutil.copy2(DIRECTORY / 'root-assets-guest.sh', share)
            blocks = phone.PhoneBlocks(output / 'read-cache', lambda index: phone.adb(
                arguments.serial, f'dd if={phone.MAPPER} bs={phone.BLOCK} skip={index} count=1 2>/dev/null'))
            with phone.nbd(blocks) as (address, failures), receiver(output / 'files') as server:
                (share / 'transfer.json').write_text(json.dumps({'port': server.server_port, 'token': server.token}) + '\n',
                                                     encoding='ascii', newline='\n')
                overlay = output / 'inspect.qcow2'
                phone.run([phone.QEMU_IMG, 'create', '-q', '-f', 'qcow2', '-b', address, '-F', 'raw', overlay])
                with (output / 'guest.log').open('wb') as logfile:
                    subprocess.run([sys.executable, '-X', 'utf8', DIRECTORY / 'sb-guest-run.py',
                                    overlay, share, 'root-assets-guest.sh', 'ROOT_ASSETS_INSPECT_SUCCESS', '-', '34614'],
                                   stdout=logfile, stderr=subprocess.STDOUT, check=True, timeout=1500)
                if failures or server.failures:
                    raise IOError(f'Inspection transfer failure: {(failures + server.failures)[:3]}')
                files = dict(server.files)
            text = (output / 'guest.log').read_text(encoding='utf-8', errors='strict')
            if 'ROOT_ASSETS_INSPECT_SUCCESS' not in text or 'GUEST_OK' not in text:
                raise RuntimeError('Guest inspection did not complete')
            count = re.findall(r'^ROOT_FILE_COUNT ([0-9]+)\r?$', text, re.MULTILINE)
            if len(count) != 1 or len(files) != int(count[0]):
                raise ValueError('Guest file count differs from extracted records')
            version = re.findall(r'^ROOT_VERSION (\{[^\n]*\})\r?$', text, re.MULTILINE)
            manifest = {'provenance': {'method': 'read-only phone NBD and HFS mount',
                                       'captured_at': datetime.now().astimezone().isoformat(),
                                       'mapping_evidence': str(output / 'mapping.txt'),
                                       'guest_log': str(output / 'guest.log')},
                        'root_path': ROOT_PATH, 'root_bytes': phone.SIZE,
                        'version': json.loads(version[0]) if len(version) == 1 else None,
                        'phone_read_blocks': blocks.reads, 'files': files,
                        'bdf_selection_verified': False}
            (output / 'assets.json').write_text(json.dumps(manifest, indent=2) + '\n',
                                               encoding='utf-8', newline='\n')
            phone.say('ROOT_ASSETS_INSPECT_OK', len(files), 'files', blocks.reads * 4, 'MiB read')
            for name, record in files.items():
                phone.say('ASSET', name, record['bytes'], record['sha256'])
        finally:
            if mapped:
                phone.say(phone.adb(arguments.serial, f'{phone.MANAGER} unmap').decode().strip())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--serial', default=os.environ.get('FUXI_ANDROID_SERIAL', ''))
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
    elif arguments.output:
        inspect(arguments)
    else:
        parser.error('--output or --self-test is required')
