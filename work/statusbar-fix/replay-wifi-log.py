import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


DIRECTORY = Path(__file__).resolve().parent


def load(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def replay(source, output, details, port, focus=None):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if (source.parent != DIRECTORY or output.parent != DIRECTORY or output.exists()
            or not re.fullmatch(r'inspect-[a-z0-9-]+', output.name)):
        raise ValueError('Use an existing capture and a new inspect directory under statusbar-fix')
    provenance = json.loads((source / 'provenance.json').read_bytes())
    if (hashlib.sha256((source / 'powerlog-state.json').read_bytes()).hexdigest()
            != provenance.get('summary_sha256') or provenance.get('guest_root_overlay_writes') != 0):
        raise ValueError('Capture identity or read-only provenance differs')
    if not (source / 'read-cache').is_dir():
        raise ValueError('The source has no captured block cache')
    if focus is not None:
        if not 1 <= len(focus) <= 256:
            raise ValueError('The focus expression must contain 1 to 256 characters')
        re.compile(focus, re.I)
    phone = load('wifi_replay_phone', DIRECTORY / 'phone-readthrough.py')
    inspector = load('wifi_replay_inspector', DIRECTORY / 'inspect-powerlog-state.py')

    def cache_miss(index):
        raise RuntimeError(f'Captured cache lacks block {index}; live phone reads are prohibited')

    output.mkdir()
    share = output / 'share'
    share.mkdir()
    shutil.copy2(DIRECTORY / 'powerlog-state-guest.sh', share)
    (share / 'inspect-wifi-log').write_bytes(b'1\n')
    if details:
        (share / 'inspect-wifi-log-details').write_bytes(b'1\n')
    if focus is not None:
        (share / 'inspect-wifi-log-focus').write_text(focus, encoding='utf-8')
    blocks = phone.PhoneBlocks(output / 'unused-cache', cache_miss)
    blocks.directory = source / 'read-cache'
    with phone.nbd(blocks) as (address, failures):
        overlay = output / 'inspect.qcow2'
        phone.run([phone.QEMU_IMG, 'create', '-q', '-f', 'qcow2', '-b', address, '-F', 'raw', overlay])
        with (output / 'guest.log').open('wb') as logfile:
            subprocess.run([sys.executable, '-X', 'utf8', DIRECTORY / 'sb-guest-run.py', overlay, share,
                            'powerlog-state-guest.sh', inspector.SUCCESS, '-', str(port)],
                           stdout=logfile, stderr=subprocess.STDOUT, check=True, timeout=180)
        allocation = json.loads(phone.run([phone.QEMU_IMG, 'map', '--output=json', overlay]))
        if failures or blocks.reads or any(entry.get('depth') == 0 and entry.get('present') for entry in allocation):
            raise RuntimeError('Cached replay attempted an uncaptured read or a root write')
    result, payload = inspector.decode((output / 'guest.log').read_text(encoding='utf-8'))
    (output / 'powerlog-state.json').write_bytes(payload)
    (output / 'provenance.json').write_text(json.dumps({
        'method': 'offline captured-cache replay; cache miss aborts',
        'source': str(source), 'source_summary_sha256': provenance['summary_sha256'],
        'phone_operations': 0, 'guest_root_overlay_writes': 0,
        'focus': focus,
        'summary_sha256': hashlib.sha256(payload).hexdigest(),
    }, indent=2), encoding='utf-8')
    print('WIFI_LOG_CACHED_REPLAY_OK phone_operations=0 root_writes=0 records=',
          len(result['wifi_log']['records']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Replay a captured Wi-Fi log without connecting to the phone')
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--details', action='store_true')
    parser.add_argument('--focus', help='Select decision lines with a bounded regex; sensitive lines stay filtered')
    parser.add_argument('--port', type=int, default=34616)
    arguments = parser.parse_args()
    if not 1024 <= arguments.port <= 65535:
        parser.error('--port is outside the local unprivileged range')
    replay(arguments.source, arguments.output, arguments.details, arguments.port, arguments.focus)
