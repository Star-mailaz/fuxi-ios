import argparse
import os
from pathlib import Path
import runpy
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "xnu" / "fuxi-battery-prep"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sanitize", action="store_true")
    arguments = parser.parse_args()
    host_tools = runpy.run_path(str(ROOT / "tools" / "test-fuxi-audio-prep.py"))
    compiler, environment = host_tools["compiler_environment"]()
    msvc = Path(compiler[0].strip('"')).name.lower() in ("cl", "cl.exe")
    sources = [SOURCE / "fuxi_battery_freshness.c", SOURCE / "test_freshness.c"]
    with tempfile.TemporaryDirectory(prefix="host-test-", dir=SOURCE) as directory:
        executable = Path(directory) / ("freshness-test.exe" if os.name == "nt" else "freshness-test")
        if msvc:
            flags = ["/nologo", "/TC", "/std:c11", "/W4", "/WX", "/Od", "/Zi", "/MD"]
            if arguments.sanitize:
                flags += ["/fsanitize=address"]
            command = compiler + flags + [f"/I{ROOT / 'xnu/fuxi-adsp'}"] + [str(source) for source in sources] + [f"/Fe:{executable}"]
        else:
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
            if arguments.sanitize:
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            command = compiler + flags + ["-I", str(ROOT / "xnu/fuxi-adsp")] + [str(source) for source in sources] + ["-o", str(executable)]
        subprocess.run(command, cwd=directory, env=environment, check=True)
        result = subprocess.run([str(executable)], cwd=directory, env=environment,
            capture_output=True, text=True, check=True)
        if not result.stdout.startswith("PASS fuxi-battery-prep freshness:"):
            raise SystemExit(result.stdout + result.stderr)
        print(result.stdout.strip())
        print(f"compiler={Path(compiler[0]).name}, sanitize={arguments.sanitize}")


if __name__ == "__main__":
    main()
