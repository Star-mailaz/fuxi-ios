import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "xnu" / "fuxi-audio-prep"


def compiler_environment():
    if os.environ.get("CC"):
        return shlex.split(os.environ["CC"], posix=os.name != "nt"), os.environ.copy()
    for name in ("cc", "clang", "gcc", "cl"):
        compiler = shutil.which(name)
        if compiler:
            return [compiler], os.environ.copy()
    if os.name == "nt":
        installer = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        locator = installer / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if locator.is_file():
            installation = subprocess.check_output([
                str(locator), "-latest", "-products", "*", "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"
            ], text=True).strip()
            setup = Path(installation) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
            if installation and setup.is_file():
                command = f'cmd.exe /d /s /c "call "{setup}" >nul && set"'
                output = subprocess.check_output(command, text=True)
                environment = os.environ.copy()
                for entry in output.splitlines():
                    name, separator, value = entry.partition("=")
                    if separator and name:
                        environment[name] = value
                compiler = shutil.which("cl", path=environment.get("Path", environment.get("PATH")))
                if compiler:
                    return [compiler], environment
    raise SystemExit("A C11 host compiler is required. Set CC or install MSVC, Clang, or GCC.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sanitize", action="store_true")
    arguments = parser.parse_args()
    compiler, environment = compiler_environment()
    msvc = Path(compiler[0].strip('"')).name.lower() in ("cl", "cl.exe")
    sources = [SOURCE / "fuxi_audio_prep_gpr.c", SOURCE / "test_gpr.c"]
    with tempfile.TemporaryDirectory(prefix="host-test-", dir=SOURCE) as directory:
        executable = Path(directory) / ("gpr-test.exe" if os.name == "nt" else "gpr-test")
        if msvc:
            flags = ["/nologo", "/TC", "/std:c11", "/W4", "/WX", "/Od", "/Zi", "/MD"]
            if arguments.sanitize:
                flags += ["/fsanitize=address"]
            command = compiler + flags + [str(source) for source in sources] + [f"/Fe:{executable}"]
        else:
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
            if arguments.sanitize:
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            command = compiler + flags + [str(source) for source in sources] + ["-o", str(executable)]
        subprocess.run(command, cwd=directory, env=environment, check=True)
        result = subprocess.run([str(executable)], cwd=directory, env=environment,
            capture_output=True, text=True, check=True)
        if not result.stdout.startswith("PASS fuxi-audio-prep GPR:"):
            raise SystemExit(result.stdout + result.stderr)
        print(result.stdout.strip())
        print(f"compiler={Path(compiler[0]).name}, sanitize={arguments.sanitize}")


if __name__ == "__main__":
    main()
