"""000 statusbar copy of guest-run.py: same, plus a read-only raw disk (vdc) holding pull.bin (vvfat FAT16 tops out near 500 MB).

usage: python sb-guest-run.py <overlay.qcow2> <share dir> <script name> <success token> <pull.bin> [port]
Same flow as prepare-layout0014-guest.py; the script's serial output is printed. Exit 1 if the token is missing.
"""
import pathlib
import socket
import subprocess
import sys
import time

overlay, share, script, token, pull = sys.argv[1:6]
port = int(sys.argv[6]) if len(sys.argv) > 6 else 34611
assert pathlib.Path(overlay).is_file() and (pathlib.Path(share) / script).is_file()
assert pull == '-' or pathlib.Path(pull).is_file()
q = r'D:\xiaomi13\fuxi_ios\candidates\vm-tools\qemu\qemu-system-x86_64.exe'
args = [q, '-accel', 'whpx', '-m', '2048', '-smp', '2', '-display', 'none',
        '-serial', f'tcp:127.0.0.1:{port},server=on,wait=off', '-no-reboot',
        '-kernel', r'D:\xiaomi13\fuxi_ios\candidates\vm-tools\alpine\boot\vmlinuz-lts',
        '-initrd', r'D:\xiaomi13\fuxi_ios\candidates\vm-tools\alpine\boot\initramfs-lts',
        '-append', 'modules=loop,squashfs,sd-mod,usb-storage console=ttyS0 quiet',
        '-cdrom', r'D:\xiaomi13\fuxi_ios\candidates\vm-tools\alpine-standard-3.24.4-x86_64.iso',
        '-drive', f'file={overlay},format=qcow2,if=virtio',
        '-drive', f'file=fat:ro:{share},format=raw,if=virtio,readonly=on',
        '-nic', 'user,model=virtio-net-pci']
if pull != '-' and pathlib.Path(pull).stat().st_size:
    args += ['-drive', f'file={pull},format=raw,if=virtio,readonly=on']
p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=0x08000000)
ok = False
try:
    for i in range(100):
        try:
            s = socket.create_connection(('127.0.0.1', port), 1)
            break
        except OSError:
            time.sleep(.2)
    else:
        raise RuntimeError('serial not listening')
    s.settimeout(1)

    def waitfor(tok, timeout=120, show=False):
        b = b''
        end = time.time() + timeout
        while time.time() < end:
            try:
                x = s.recv(65536)
                if not x:
                    raise RuntimeError('serial closed')
                b += x
                if tok in b:
                    if show:
                        print(b.decode(errors='replace'), flush=True)
                    return b
            except socket.timeout:
                pass
        print(b.decode(errors='replace')[-4000:], flush=True)
        raise TimeoutError(tok)

    def send(x):
        for c in (x + '\n').encode():
            s.send(bytes([c]))
            time.sleep(.012)

    waitfor(b'localhost login:')
    send('root'); waitfor(b'localhost:~#')
    send('mkdir -p /mnt/share && mount -o ro /dev/vdb1 /mnt/share && ls /mnt/share && cat /sys/block/vdb/ro'); waitfor(b'localhost:~#', show=True)
    send('ip link set eth0 up; udhcpc -i eth0 -q -n -t 5 -T 2'); waitfor(b'localhost:~#', 40)
    send("printf '%s\\n' https://dl-cdn.alpinelinux.org/alpine/v3.24/main https://dl-cdn.alpinelinux.org/alpine/v3.24/community > /etc/apk/repositories; apk update && apk add python3 hfsprogs"); waitfor(b'localhost:~#', 1200)
    send('command -v python3 && command -v fsck.hfsplus && modprobe hfsplus && echo PRECHECK_DONE'); waitfor(b'localhost:~#', 60, show=True)
    send('sh /mnt/share/' + script); out = waitfor(b'localhost:~#', 1500, show=True)
    ok = token.encode() in out
    time.sleep(2)
    send('poweroff'); p.wait(timeout=60)
finally:
    p.terminate(); p.wait(timeout=15)
print('GUEST_OK' if ok else 'GUEST_FAILED', flush=True)
sys.exit(0 if ok else 1)
