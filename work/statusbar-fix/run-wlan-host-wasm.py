import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys


WORKSPACE = Path(__file__).resolve().parents[2]
TOOLS = WORKSPACE / 'work/adsp-battery/ksrc/tools'
EMSCRIPTEN = Path(
    'C:/Program Files/Unity/Hub/Editor/6000.3.10f1/Editor/Data/PlaybackEngines/'
    'WebGLSupport/BuildTools/Emscripten/emscripten/emcc.bat')
ORIGINAL_RUN = subprocess.run


def run(arguments, **options):
    arguments = list(map(str, arguments))
    if '-std=c11' in arguments and '-o' in arguments:
        output = arguments.index('-o') + 1
        arguments[0] = str(EMSCRIPTEN)
        arguments[output] += '.js'
        arguments += [
            '-sALLOW_MEMORY_GROWTH=1', '-sSTACK_SIZE=8388608',
            '-sINITIAL_MEMORY=67108864', '-sEXIT_RUNTIME=1',
        ]
        environment = dict(options.pop('env', os.environ))
        environment['EM_CONFIG'] = str(EMSCRIPTEN.parents[1] / '.emscripten')
        options['env'] = environment
        print('Compiling production peer with Emscripten ASan/UBSan', flush=True)
        return ORIGINAL_RUN(arguments, **options)
    if len(arguments) == 1 and Path(arguments[0] + '.js').is_file():
        return ORIGINAL_RUN([shutil.which('node'), arguments[0] + '.js'], **options)
    return ORIGINAL_RUN(arguments, **options)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('suite', choices=('w18', 'm6i', 'rails'))
    args = parser.parse_args()
    if not EMSCRIPTEN.is_file() or shutil.which('node') is None:
        parser.error('The existing Unity Emscripten toolchain and Node are required')
    source = TOOLS / f'test-fuxi-wlan-{args.suite}.py'
    specification = importlib.util.spec_from_file_location('wlan_host_suite', source)
    suite = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(suite)
    subprocess.run = run
    if args.suite == 'w18':
        sys.argv = [str(source)]
    suite.main()
    print('PASS: wasm32 production peer; native 64-bit CI and device validation remain separate')


if __name__ == '__main__':
    main()
