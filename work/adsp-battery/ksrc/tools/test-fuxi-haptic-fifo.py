import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'xnu' / 'fuxi-haptic-prep'
MSVC_ROOT = Path(r'C:\Program Files\Microsoft Visual Studio\18\Enterprise')


def find_compiler(requested, syntax_only):
    if requested:
        return requested
    names = ('clang',) if syntax_only else ('cc', 'clang', 'gcc', 'cl')
    for name in names:
        compiler = shutil.which(name)
        if compiler:
            return compiler
    if not syntax_only:
        candidates = sorted((MSVC_ROOT / 'VC' / 'Tools' / 'MSVC').glob(
            '*/bin/Hostx64/x64/cl.exe'), reverse=True)
        if candidates:
            return str(candidates[0])
    raise SystemExit('C compiler unavailable for this mode; run in CI with CC=clang. '
                     'Windows host assertions also support MSVC /std:c11.')


def msvc_environment(compiler):
    environment = os.environ.copy()
    if environment.get('INCLUDE') and environment.get('LIB'):
        return environment
    compiler_path = Path(shutil.which(compiler) or compiler).resolve()
    for parent in compiler_path.parents:
        vcvars = parent / 'VC' / 'Auxiliary' / 'Build' / 'vcvars64.bat'
        if vcvars.is_file():
            break
    else:
        raise SystemExit('MSVC found but vcvars64.bat unavailable; run from an x64 developer prompt.')
    command = f'"{environment.get("COMSPEC", "cmd.exe")}" /d /s /c "call "{vcvars}" >nul && set"'
    result = subprocess.run(command, check=True, capture_output=True,
                            text=True, errors='replace', timeout=120)
    for line in result.stdout.splitlines():
        name, separator, value = line.partition('=')
        if separator and name:
            environment[name.upper()] = value
    return environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cc', default=os.environ.get('CC'))
    parser.add_argument('--syntax-only', action='store_true')
    parser.add_argument('--target', default='arm64-apple-darwin')
    args = parser.parse_args()
    compiler = find_compiler(args.cc, args.syntax_only)
    microsoft = Path(compiler).name.lower() in ('cl', 'cl.exe')
    implementation = SOURCE / 'fuxi_haptic_fifo.c'
    if args.syntax_only:
        if microsoft:
            raise SystemExit('ARM64 syntax requires clang; MSVC is supported for host assertions only.')
        subprocess.run([compiler, '-target', args.target, '-ffreestanding', '-mgeneral-regs-only',
                        '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsyntax-only',
                        '-I' + str(SOURCE), str(implementation)], check=True, timeout=120)
        print('PASS: actual FIFO helper ARM64 freestanding syntax; active write gate remains zero')
        return
    environment = msvc_environment(compiler) if microsoft else os.environ.copy()
    with tempfile.TemporaryDirectory(prefix='fuxi-haptic-fifo-') as temporary:
        directory = Path(temporary).resolve()
        binary = directory / ('fifo.exe' if os.name == 'nt' else 'fifo')
        sources = [str(implementation), str(SOURCE / 'test_fifo.c')]
        if microsoft:
            command = [compiler, '/nologo', '/std:c11', '/W4', '/WX', '/TC',
                       '/I' + str(SOURCE), '/Fo' + str(directory) + os.sep,
                       '/Fe' + str(binary), *sources]
        else:
            command = [compiler, '-std=c11', '-g', '-O1', '-Wall', '-Wextra', '-Werror',
                       '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                       '-fno-sanitize-recover=all', '-I' + str(SOURCE), *sources, '-o', str(binary)]
        subprocess.run(command, check=True, cwd=directory, env=environment, timeout=120)
        subprocess.run([str(binary)], check=True, cwd=directory, env=environment, timeout=120)
    if microsoft:
        print('MSVC host assertions passed; ASan/UBSan and ARM64 syntax remain separate clang/CI checks.')


if __name__ == '__main__':
    main()
