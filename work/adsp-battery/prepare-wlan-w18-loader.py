#!/usr/bin/env python3
"""Inspect or build the controlled iOS 16 W18 loader using local host inputs."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

WORKSPACE = Path(__file__).resolve().parents[2]
STORAGE = WORKSPACE / 'work/Codex-Xiaomi13-GPU-20261109'
TOOLS = WORKSPACE / 'work/adsp-battery/ksrc/tools'
COMPILER = Path(os.environ.get('LOCALAPPDATA', ''), r'Android\Sdk\ndk\26.1.10909125\toolchains\llvm\prebuilt\windows-x86_64\bin')
SOURCE = 'native-dly-ram9g-sb127-user-loader'
ARTIFACT = 'kernel-adsp-iter2-ram9g-artifact'
ROOT_PATH = '/data/gsi/codexnative1108b/codexnative_root_1108b.img.0000'
ROOT_BYTES = 20 * 1024**3
RAM_BASE, RAM_SIZE, GPU_BASE, GPU_SIZE = 0x8c0000000, 0x23e000000, 0xafe000000, 0x2000000
WLAN_ARGS = ('fuxiadsp=0', 'fuxiwlan=1', 'fuxiwlanclk=1', 'fuxiwlanprobe=civac',
             'fuxiwlanseq=cycle,parf,dbi,eq,hostirq,msi,por,prefix',
             'fuxiwlanqrtr=5', 'fuxiwlanw18=1')
DROP_KEYS = {'debug', 'fuxivsynctoff', 'sweetlog', 'sweetfb_noconsole', 'sweetnull',
             'fuxiswapwait', 'fuxiperf', 'fuxicores', 'fuxitudebug', 'fuxitcache',
             'fuxiadsp', 'fuxiamp', 'fuxipmic', 'fuxiramtest', 'fuxihaptic', 'fuxiaudiospf',
             'fuxitaps', 'fuxitapcmd', 'fuxitour', 'fuxitourhold', 'fuxibt'}
OFF_PROPS = ('fuxi,adsp', 'fuxi,amp', 'fuxi,pmic', 'fuxi,ramtest', 'fuxi,haptic', 'fuxi,audio-spf', 'fuxi,bt')
# 日常 chain-v7 的流暢度參數，取自 native-dly-ram9g-rtctorch-sb127-loader 的命令列（vsync 偏移、關持久 console ring、
# swap 不等、perf 2、核心遮罩、Turnip nocb、tcache）。全部都在 DROP_KEYS 裡，來源的同名值會先被丟掉。
DAILY_TUNING = ('fuxivsynctoff=6000', 'sweetlog=0', 'fuxiswapwait=0', 'fuxiperf=2', 'fuxicores=0x7c',
                'fuxitudebug=nocb', 'fuxitcache=1')
# 補丁 0121：命令列上找不到的 fuxiwlan*／fuxiwifi* 開關改讀 ADT /chosen fuxi,args（2..256 bytes，唯一 NUL 在結尾）。
# 只搬這幾個由驅動啟動後才讀的開關；fuxiwlan=1 與測試用 fuxiwifitest* 留在命令列。
ADT_WIFI_KEYS = ('fuxiwlanath', 'fuxiwlanmlo', 'fuxiwifiios', 'fuxiwlandwell', 'fuxiwlancache', 'fuxiwifitrace',
                 'fuxiwlanbatch')
GPU_INPUTS = (
    ('gpu', 'firmware/gmu_gen70200.bin', '1a2a419c39046d3141fc5fed5aa7f971de2db40cc7a1d89693c3e26fad64dd98'),
    ('sqe', 'firmware/a740_sqe_sheng.fw', '6d38046654333a6a5a4ee77ab67abc24e3c0c5c68237513afe98e94da8fc9fcc'),
    ('zap', 'work/xiaomi13-ios-gpu-20261108/a740-zap-active-odm.mbn', 'cad0dcb2daaa382eebc94ef65f3285b91b045c8976781f6a80910ca21c933a05'))
NATIVE_OBJECTS = {
    '78178a345c8573a13aa1781221b18ea993b0b8716defb09ba4543e494ad4f6e1': None,
    'fbfdc220a37eca52e0db0a8f85a918bbfbbe512e6e4d698144e5a036587cff67':
        'a12107927728e05f4c9e31820a9562cb581355c65d50b9ffa0c2b48d7d503804',
    'dc0694f49e8557b6dce943fe07711e272579b8ffc0e67196499d6f6ec3b83931':
        '4abc2793df722c3fc03fd098118cc1731301b5523a5c8f8b28d04228b8ec95bb',
}

sys.path.insert(0, str(TOOLS))
import adt
import mkpayload


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sums(path):
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        checksum, name = line.split(maxsplit=1)
        name = name.strip().lstrip('*')
        require(re.fullmatch('[0-9a-fA-F]{64}', checksum), f'invalid checksum in {path}')
        require(name not in result, f'duplicate checksum entry {name}')
        result[name] = checksum.lower()
    return result


def checked_file(path, checksums, name=None):
    key = name or path.name
    require(key in checksums, f'missing checksum for {key}')
    require(path.is_file() and digest(path) == checksums[key], f'checksum mismatch or missing file {path}')
    return checksums[key]


def chosen_node(tree):
    matches = [node for node in tree.children if node.name == 'chosen']
    require(len(matches) == 1, 'ADT needs one chosen node')
    chosen = matches[0]
    require(len({name for name, _, _ in chosen.props}) == len(chosen.props), 'duplicate chosen property')
    return chosen


def wifi_ux_value(value, wifi_ios, kernel):
    """ADT /chosen fuxi,wifi-ux 的 4 bytes：1..31，要 native iOS Wi-Fi 與核心的 fuxi_wifi_ux() 標記。
    bit 3（記住國家碼）與 bit 4（同狀態電源不重開）要核心印出這兩欄的版本。"""
    require(wifi_ios is True, '--wifi-ux needs the native iOS Wi-Fi backend')
    require(type(value) is int and 1 <= value <= 31, '--wifi-ux must be 1..31')
    require(b'FUXI WIFI IOS: ux options 0x%x' in kernel and b'fuxi,wifi-ux' in kernel,
            'artifact lacks the fuxi,wifi-ux Wi-Fi options')
    require(value < 8 or b'country %u, power-same %u)' in kernel,
            'artifact lacks the fuxi,wifi-ux country/power-same bits')
    return struct.pack('<I', value)


def wifi_args_value(text, kernel):
    """ADT /chosen fuxi,args：補丁 0121 的格式，空白分隔的 name=value、只收 fuxiwlan*／fuxiwifi*，結尾唯一 NUL，2..256 bytes。"""
    require(isinstance(text, str) and b'fuxi,args' in kernel, 'artifact lacks the 0121 ADT Wi-Fi arguments')
    tokens = text.split(' ')
    require(tokens and all(re.fullmatch(r'(fuxiwlan|fuxiwifi)[a-z]*=[A-Za-z0-9]+', token) for token in tokens),
            'invalid ADT Wi-Fi argument string')
    keys = [token.partition('=')[0] for token in tokens]
    require(len(set(keys)) == len(keys) and all(key in ADT_WIFI_KEYS for key in keys),
            'ADT Wi-Fi arguments must be distinct movable switches')
    value = text.encode('ascii') + b'\0'
    require(2 <= len(value) <= 256, 'ADT Wi-Fi arguments outside 2..256 bytes')
    return value


def audio_spf_choice(enabled, with_adsp, kernel, wire_format='apm'):
    require(type(enabled) is bool and type(with_adsp) is bool, 'invalid audio SPF selector')
    require(wire_format in ('apm', 'bare') and (enabled or wire_format == 'apm'),
            'invalid audio SPF format selector')
    require(not enabled or with_adsp, 'audio SPF query needs the ADSP owner')
    require(not enabled or (b'FUXI AUDIO SPF: state query queued bytes' in kernel and
                           b'fuxi,audio-spf' in kernel), 'artifact lacks the query-only audio SPF client')
    return (2 if wire_format == 'bare' else 1) if enabled else 0


def parse_tree(data):
    tree, consumed = adt.parse(data)
    require(consumed == len(data) and adt.serialize(tree) == data, 'ADT parsing/serialization mismatch')
    return tree


def verify_map(record, chosen):
    matches = [item for item in record['items'] if item['path'] == ROOT_PATH]
    require(len(matches) == 1, 'recorded native root identity missing or duplicated')
    item = matches[0]
    require(item['size'] == ROOT_BYTES and item['flags'] & 0x800000, 'recorded root size/pin flags differ')
    require(ROOT_PATH in record['pin'] and 'flags_rc=0' in record['pin'] and
            'pin_rc=0 moved=0' in record['pin'], 'recorded root pin check failed')
    words, position, ranges = [], 0, []
    for logical, physical, length, flags in item['extents']:
        require(logical == position and physical >= 0 and length > 0 and
                not (logical | physical | length) & 4095 and not flags & ~0x1001,
                'invalid recorded root extent')
        words.extend((logical // 4096, physical // 4096, length // 4096))
        ranges.append((physical, physical + length))
        position += length
    require(position == ROOT_BYTES and len(ranges) <= 512, 'recorded extents do not cover the root')
    ordered = sorted(ranges)
    require(all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:])), 'root extents overlap')
    expected = struct.pack(f'<{len(words)}Q', *words)
    require(chosen.prop('fuxi-root-extents') == expected, 'source ADT differs from recorded root extents')
    require(chosen.prop('fuxi-root-blocks') == struct.pack('<Q', ROOT_BYTES // 4096), 'source ADT root size differs')
    targets = record['dm']
    require(len(targets) == len(ranges) + 1, 'recorded DM target count differs')
    header = re.fullmatch(r'targets=(\d+) flags=0x[0-9a-fA-F]+', targets[0])
    require(header and int(header[1]) == len(ranges), 'recorded DM header differs')
    for line, (logical, physical, length, _) in zip(targets[1:], item['extents']):
        match = re.fullmatch(r'target=linear start=(\d+) length=(\d+) backing=259:16 offset=(\d+)', line)
        require(match and tuple(map(int, match.groups())) == (logical // 512, length // 512, physical // 512),
                'recorded DM differs from FIEMAP')
    return {'recorded_at': record['time'], 'root_path': ROOT_PATH, 'inode': item['inode'],
            'root_bytes': ROOT_BYTES, 'extents': len(ranges), 'extents_sha256': hashlib.sha256(expected).hexdigest()}


def arguments(source_line, bdf, mlo=0, host_cap_secondary=False, omit_nm_modem=False, sleep_clock=None,
              big_mem=False, cnss_pdc=False, errdec=False, native_ath12k=False, wifi_ios=False,
              wifi_self_test=False, tap_script=None, tap_delay=85, wifi_join_ssid=None,
              wifi_ui_only=None, quiet_screen=False, quiet_boot=False, sample=None, crash_strings=None, hybrid_turnip=False,
              profile=None, profile_delay=60, scan_dwell=False, scan_cache=False, wifi_trace=False,
              scan_batch=False, stderr_log=None, privs=False, daily_tuning=False, wifi_args_adt=False):
    """回傳 (命令列, 被丟掉的來源參數)；wifi_args_adt 時多回傳要放進 ADT fuxi,args 的字串（不含 NUL）。"""
    tokens = source_line.split()
    require(source_line == ' '.join(tokens), 'source command line is not normalized')
    keys = [token.partition('=')[0] for token in tokens]
    require(len(set(keys)) == len(keys), 'duplicate source boot argument')
    require(type(host_cap_secondary) is bool, 'invalid HOST_CAP SECONDARY selector')
    require(type(omit_nm_modem) is bool and (not omit_nm_modem or host_cap_secondary),
            'nm_modem omission requires the SECONDARY baseline')
    require('fuxiwlancap' not in keys, 'inherited fuxiwlancap is not allowed')
    removed = [token for token in tokens if token.partition('=')[0] in DROP_KEYS or token.startswith('fuxiwlan')]
    kept = [token for token in tokens if token not in removed]
    required = ('serial=3', 'cpus=7', 'rd=ufsroot0', 'ufsroot=userdata', 'ufsrw=1', 'rootrw=1',
                'fuxigpu=1', 'fuxigpuabi=1', 'fuximetal=native', 'fuxigpuncimport=2405960',
                'fuxibbgpu=2', 'fuxigpulevel=24', 'fuxigpuscanout=1', 'fuxiscandouble=1',
                'fuxiscantriple=1', 'fuxipanel120=1', 'fuxivsyncte=1', 'fuxiperfidle=1000', 'fuxibacklight=4')
    require(all(token in kept for token in required), 'source differs from the controlled display/root bootstrap')
    require(type(native_ath12k) is bool, 'invalid native ath12k selector')
    require(type(hybrid_turnip) is bool and (not hybrid_turnip or native_ath12k),
            'hybrid Turnip is an isolated native ath12k test option')
    require(type(wifi_ios) is bool and (not wifi_ios or native_ath12k),
            'native iOS station needs the native ath12k variant')
    require(type(scan_dwell) is bool and (not scan_dwell or wifi_ios),
            'scan dwell needs the native iOS station and negotiated module support')
    require(type(scan_cache) is bool and (not scan_cache or wifi_ios),
            'scan cache needs the native iOS station')
    require(type(wifi_trace) is bool and (not wifi_trace or wifi_ios),
            'Wi-Fi caller trace needs the native iOS station')
    require(type(scan_batch) is bool and (not scan_batch or (wifi_ios and scan_dwell)),
            'scan batching needs the native iOS station and negotiated scan dwell')
    require(type(wifi_self_test) is bool and (not wifi_self_test or wifi_ios),
            'native Wi-Fi self-test needs the iOS station bridge')
    require(tap_script is None or (wifi_ios and not wifi_self_test and
            isinstance(tap_script, str) and 1 <= len(tap_script.encode('ascii')) < 400 and
            re.fullmatch(r'[a-z0-9,;]+', tap_script)), 'UI taps need the isolated native iOS station')
    require(type(tap_delay) is int and 30 <= tap_delay <= 300, 'UI tap delay outside bounds')
    # 加入測試只帶網路名稱，密碼由核心以假值代入，預期結果是 EAUTH；真實密碼不進開機參數。
    require(wifi_join_ssid is None or (wifi_ios and not wifi_self_test and tap_script is None and
            isinstance(wifi_join_ssid, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', wifi_join_ssid)),
            'native Wi-Fi join test needs the isolated iOS station and a plain SSID')
    require(not any(key.startswith(('fuxiwifiios', 'fuxiwifitest')) for key in keys),
            'Wi-Fi iOS selectors must be explicit, not inherited')
    # UI 測試專用：wifid 只聽得到這個名稱的網路（fuxiwifitest=3），腳本點清單第一列就是它；密碼仍由畫面輸入假值。
    require(wifi_ui_only is None or (wifi_ios and tap_script is not None and wifi_join_ssid is None and
            not wifi_self_test and isinstance(wifi_ui_only, str) and
            re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', wifi_ui_only)),
            'UI list filter needs the native iOS station, a tap script and a plain SSID')
    require(type(quiet_screen) is bool, 'invalid quiet-screen selector')
    # 0119 sweetfb_noconsole=2：從 vcattach 起不畫核心跑碼也不重播 msgbuf（=1 只在進 SpringBoard 後停）；
    # persistent log／mtdblk 照收，panic 仍會顯示。與 =1 互斥。
    # 來源的 sweetfb_noconsole 在 DROP_KEYS，先丟掉再依選項重加。
    require(type(quiet_boot) is bool and not (quiet_boot and quiet_screen), 'quiet boot is exclusive with quiet screen')
    require(sample is None or (isinstance(sample, str) and len(sample) <= 60 and
            re.fullmatch(r'[A-Za-z0-9._-]+(,[A-Za-z0-9._-]+)*', sample) and 'sweetsample' not in keys),
            'invalid or inherited process sampler list')
    # 這些程序寫到 /dev/null 的 stderr 也轉進核心紀錄（0048 sweetnull，預設只有 backboardd,SpringBoard）；
    # 來源已有 sweetnull 時沿用它的名單再補上新的。
    require(stderr_log is None or (native_ath12k and isinstance(stderr_log, str) and len(stderr_log) <= 40 and
            re.fullmatch(r'[A-Za-z0-9._-]+(,[A-Za-z0-9._-]+)*', stderr_log) and
            not {'backboardd', 'SpringBoard'} & set(stderr_log.split(','))),
            'invalid or inherited stderr log list')
    require(type(profile_delay) is int and 30 <= profile_delay <= 300 and
            (profile is not None or profile_delay == 60), 'invalid process profiler delay')
    require(profile is None or (native_ath12k and isinstance(profile, str) and
            re.fullmatch(r'[A-Za-z0-9._-]{1,31}', profile) and
            not any(key in keys for key in ('sweetprof', 'sweetprofname'))),
            'invalid or inherited process profiler target')
    # SIGABRT 時掃這些程序的 heap 字串（核心 sweetscan=），用來看未攔截 ObjC 例外的原因。
    require(crash_strings is None or (isinstance(crash_strings, str) and len(crash_strings) <= 60 and
            re.fullmatch(r'[A-Za-z0-9._-]+(,[A-Za-z0-9._-]+)*', crash_strings) and 'sweetscan' not in keys),
            'invalid or inherited crash string scan list')
    # 0107 fuxiprivs=1：程序自己的簽章帶有對應 entitlement 時才給權限（HackiOS minisandbox 對照表，
    # 例如 WebKit.Networking／mDNSResponder 的 socket-delegate）。預設關，需明寫，不從來源繼承。
    require(type(privs) is bool and (not privs or native_ath12k) and 'fuxiprivs' not in keys,
            'entitlement privileges are an explicit native ath12k test option')
    # chain-v7 調校：與 hybrid Turnip（fuxitudebug=hyb）互斥；同名來源值都在 DROP_KEYS，所以不會重複。
    require(type(daily_tuning) is bool and (not daily_tuning or (native_ath12k and not hybrid_turnip)),
            'daily tuning is a native ath12k option and exclusive with hybrid Turnip')
    require(all(token.partition('=')[0] in DROP_KEYS for token in DAILY_TUNING), 'daily tuning key not dropped')
    require(type(wifi_args_adt) is bool and (not wifi_args_adt or wifi_ios),
            'ADT Wi-Fi arguments need the native iOS station')
    if native_ath12k:
        require(bdf is None and type(mlo) is int and mlo == 0 and
                host_cap_secondary is False and omit_nm_modem is False and
                sleep_clock == 'on' and big_mem is False and cnss_pdc is False and errdec is False,
                'native ath12k needs sleep-clock on and no legacy BDF/MLO/HOST_CAP/memory/PDC selectors')
        require(not any(key.startswith('fuxiwlan') for key in keys),
                'native ath12k cannot inherit legacy WLAN selectors')
        tee = []
        if stderr_log:
            inherited = [token for token in kept if token.startswith('sweetnull=')]
            names = (inherited[0].partition('=')[2] if inherited else 'backboardd,SpringBoard').split(',')
            names += [name for name in stderr_log.split(',') if name not in names]
            kept = [token for token in kept if not token.startswith('sweetnull=')]
            tee = ['sweetnull=' + ','.join(names)]
        line = ' '.join(kept + ['fuxiwlan=1', 'fuxiwlanath=1', 'fuxiwlanmlo=192'] +
                        (list(DAILY_TUNING) if daily_tuning else []) +
                        (['fuxiwifiios=2'] if wifi_ios else []) +
                        (['fuxiwlandwell=1'] if scan_dwell else []) +
                        (['fuxiwlancache=1'] if scan_cache else []) +
                        (['fuxiwifitrace=1'] if wifi_trace else []) +
                        (['fuxiwlanbatch=1'] if scan_batch else []) +
                        (['fuxiwifitest=1'] if wifi_self_test else []) +
                        (['fuxiwifitest=2', 'fuxiwifitestssid=' + wifi_join_ssid] if wifi_join_ssid else []) +
                        (['fuxiwifitest=3', 'fuxiwifitestssid=' + wifi_ui_only] if wifi_ui_only else []) +
                        (['sweetfb_noconsole=1'] if quiet_screen else []) +
                        (['sweetfb_noconsole=2'] if quiet_boot else []) +
                        (['sweetsample=' + sample] if sample else []) +
                        (['sweetprof=' + str(profile_delay), 'sweetprofname=' + profile] if profile else []) +
                        (['sweetscan=' + crash_strings] if crash_strings else []) +
                        tee +
                        (['fuxitudebug=hyb'] if hybrid_turnip else []) +
                        (['fuxiprivs=1'] if privs else []) +
                        (['fuxitaps=' + str(tap_delay)] if tap_script else []))
        final = line.split(' ')
        require(len({token.partition('=')[0] for token in final}) == len(final), 'duplicate native boot argument')
        moved = [token for token in final if token.partition('=')[0] in ADT_WIFI_KEYS] if wifi_args_adt else []
        line = ' '.join(token for token in final if token not in moved)
        require(len(line.encode('ascii')) < 608, 'native ath12k command line exceeds the iOS 16 limit')
        if wifi_args_adt:
            require(2 <= len(' '.join(moved)) + 1 <= 256, 'ADT Wi-Fi arguments outside 2..256 bytes')
            return line, removed, ' '.join(moved)
        return line, removed
    require(wifi_ui_only is None and not quiet_screen and not quiet_boot and sample is None and crash_strings is None,
            'UI list filter, quiet screen, sampler and crash strings are native ath12k test options')
    result = kept + list(WLAN_ARGS)
    require(type(mlo) is int and mlo in (0, 1, 2), 'invalid existing MLO variant')
    require(not host_cap_secondary or (mlo == 0 and 'fuxiwlanmlo' not in keys),
            'HOST_CAP SECONDARY cannot be combined with an MLO override')
    if mlo:
        result.append(f'fuxiwlanmlo={mlo}')
    if bdf is not None:
        require(1 <= len(bdf) <= 63 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', bdf) and '..' not in bdf,
                'invalid explicit BDF basename')
        result.append('fuxiwlanbdf=' + bdf)
    if host_cap_secondary:
        result.append('fuxiwlancap=2' if omit_nm_modem else 'fuxiwlancap=1')
    require(sleep_clock in (None, 'check', 'on'), 'invalid sleep-clock selector')
    # P17 BIGMEM=0x200：直接配置韌體要求的大塊。只允許疊在「睡眠時脈開啟」之上，
    # 讓它相對於 trip 26（fuxiwlanmlo=192）是唯一變數；704 與 192 位元組數相同。
    require(type(errdec) is bool and (not errdec or big_mem is True),
            'target-memory summary requires the large-chunk baseline')
    require(type(big_mem) is bool and (not big_mem or sleep_clock == 'on'),
            'large-chunk grant requires the sleep-clock on baseline')
    if sleep_clock:
        # P17 CLKCHECK=0x40、CLKON=0x80（PMK8550 gpio3 的 32 kHz 睡眠時脈），MLO 低兩位維持 0。
        # 命令列空間不足，ADSP 關閉改由 build 強制寫入的 ADT fuxi,adsp=0 單獨承擔。
        require(mlo == 0 and 'fuxiwlanmlo' not in keys, 'sleep-clock selector cannot be combined with an MLO override')
        result.remove('fuxiadsp=0')
        # ERRDEC=0x100：只多診斷輸出（逾時後摘要韌體拿到的主機記憶體），不改任何請求；960 與 704 位元組數相同。
        result.append('fuxiwlanmlo=960' if errdec else 'fuxiwlanmlo=704' if big_mem else
                      'fuxiwlanmlo=192' if sleep_clock == 'on' else 'fuxiwlanmlo=64')
    # M6n AOP WLAN PDC（Android cnss2 在供電前送給 AOP 的 13 筆 wlan_pdc 設定）。只疊在第27趟基準
    # （睡眠時脈開＋大塊）之上，HOST_CAP 選項照舊可帶，讓它相對第27趟只多 PDC。
    require(type(cnss_pdc) is bool and (not cnss_pdc or big_mem),
            'AOP PDC requires the sleep-clock/large-chunk baseline')
    if cnss_pdc:
        # 基準已 591 位元組，再加 17 會到 608（上限 607）。拿掉 fuxiperfidle=1000（CPU 閒置降頻，與 WLAN 無關）騰出空間。
        result.remove('fuxiperfidle=1000')
        result.append('fuxiwlancnss=pdc')
    line = ' '.join(result)
    require(len(line.encode('ascii')) < 608, 'controlled command line exceeds the iOS 16 607-byte limit')
    return line, removed


def asset_report(path, bdf, native_ath12k=False):
    manifest = json.loads(path.read_text(encoding='utf-8')) if path else {}
    files = manifest.get('files', {})
    require(isinstance(files, dict), 'asset manifest files must be an object')
    normalized = {}
    prefix = '/usr/local/share/fuxi/wlan/'
    for name, entry in files.items():
        key = name.removeprefix(prefix)
        require(key not in normalized, 'duplicate WLAN asset record')
        normalized[key] = entry
    names = ['amss20.bin', 'amss.bin', 'regdb_xiaomi.bin', 'm3.bin']
    if native_ath12k:
        names.append('board-2.bin')
    if bdf:
        names.append(bdf)
    rows, gaps = [], []
    if not path:
        gaps.append('Fuxi WLAN runtime asset manifest is unavailable')
    if not bdf and not native_ath12k:
        gaps.append('explicit evidence-backed BDF basename is unresolved')
    provenance = manifest.get('provenance')
    root_match = manifest.get('root_path') == ROOT_PATH
    if path and not provenance:
        gaps.append('WLAN asset manifest provenance is missing')
    if path and not root_match:
        gaps.append('WLAN asset manifest association with the pinned native root is unverified')
    for name in names:
        entry = normalized.get(name)
        row = {'name': name, 'runtime_path': prefix + name, 'status': 'missing_manifest_entry'}
        if entry is None:
            gaps.append('runtime asset record missing for ' + name)
        else:
            require(isinstance(entry, dict) and re.fullmatch(r'[0-9a-fA-F]{64}', str(entry.get('sha256', ''))) and
                    type(entry.get('bytes')) is int and entry['bytes'] > 0, 'invalid asset record for ' + name)
            row.update(sha256=entry['sha256'].lower(), bytes=entry['bytes'], status='manifest_recorded')
            if entry.get('host_path'):
                host = Path(entry['host_path'])
                if not host.is_absolute():
                    host = path.parent / host
                require(host.is_file() and host.stat().st_size == entry['bytes'] and digest(host) == row['sha256'],
                        'local asset checksum/size mismatch for ' + name)
                row.update(host_path=str(host.resolve()), status='local_hash_verified')
        rows.append(row)
    return {'manifest': str(path.resolve()) if path else None, 'manifest_sha256': digest(path) if path else None,
            'provenance': provenance, 'root_match': root_match, 'files': rows, 'gaps': gaps,
            'bdf_recorded': bool(any(row['name'] == ('board-2.bin' if native_ath12k else bdf) and
                                     row['status'] != 'missing_manifest_entry' for row in rows))}


def inspect(args):
    source, artifact = STORAGE / args.source, STORAGE / args.artifact
    pinned = sums(source / 'sha256.txt')
    for name in ('payload.bin', 'boot.img'):
        checked_file(source / name, pinned)
    payload = (source / 'payload.bin').read_bytes()
    require(payload[:8] == b'SWEETXNU' and struct.unpack_from('<I', payload, 8)[0] == 1, 'source needs iOS 16 payload v1')
    offset, size = struct.unpack_from('<2Q', payload, 32)
    require(680 <= offset < len(payload) and offset + size <= len(payload), 'source ADT bounds differ')
    tree = parse_tree(payload[offset:offset + size])
    chosen = chosen_node(tree)
    require(chosen.prop('fuxi,ram-sku') in (None, struct.pack('<I', 12)),
            'source ADT physical RAM SKU differs from the measured 12GB profile')
    require(struct.unpack_from('<2Q', payload, 56) == (RAM_BASE, RAM_SIZE), 'source payload needs validated 9G RAM')
    require(chosen.prop('dram-base') == struct.pack('<Q', RAM_BASE) and
            chosen.prop('dram-size') == struct.pack('<Q', RAM_SIZE) and
            chosen.prop('fuxi-gpu-memory') == struct.pack('<2Q', GPU_BASE, GPU_SIZE), 'source ADT RAM/GPU geometry differs')
    require(chosen.prop('fuxi,sbshape') == struct.pack('<I', 300127) and
            chosen.prop('fuxi,inject') == struct.pack('<I', 2), 'source needs validated statusbar127/inject2')
    layout_record = json.loads((source / 'memory-layout.json').read_text(encoding='utf-8'))
    require(layout_record['layout'] == '9g' and layout_record['usable'] == RAM_SIZE and
            layout_record['scratch'] == GPU_BASE, 'source memory metadata differs')
    require(digest(args.live_fdt) == layout_record['live_fdt_sha256'], 'live-FDT capture differs from the source RAM evidence')
    spec = importlib.util.spec_from_file_location('w18_layout', TOOLS / 'mkadt-fuxi.py')
    layout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(layout)
    layout.configure_ram('9g')
    sku_metadata = layout.validate_live(args.live_fdt, True, args.ram_sku)
    mapping = verify_map(json.loads(args.map_record.read_text(encoding='utf-8')), chosen)
    built = arguments(payload[72:680].split(b'\0', 1)[0].decode('ascii'), args.bdf, args.mlo,
                      args.host_cap_secondary, args.omit_nm_modem, args.sleep_clock, args.big_mem, args.cnss_pdc,
                      args.errdec, args.native_ath12k, args.wifi_ios, args.wifi_self_test,
                      args.tap_script, args.tap_delay, args.wifi_join_test,
                      args.wifi_ui_only, args.quiet_screen, args.quiet_boot, args.sample, args.crash_strings,
                      args.hybrid_turnip, args.profile, args.profile_delay, args.scan_dwell, args.scan_cache,
                      args.wifi_trace, args.scan_batch, args.stderr_log, args.privs,
                      daily_tuning=args.daily_tuning, wifi_args_adt=args.wifi_args_adt)
    line, removed = built[:2]
    adt_args = built[2] if args.wifi_args_adt else None
    shim_reference = STORAGE / args.shim_reference if args.shim_reference else source
    shim_pins = sums(shim_reference / 'sha256.txt')
    for name in ('payload.bin', 'boot.img'):
        checked_file(shim_reference / name, shim_pins)
    inputs = sums(shim_reference / 'source-input-sha256.txt')
    shim = WORKSPACE / 'ios-fuxi/shim'
    for name, checksum in inputs.items():
        checked_file(shim / name, inputs, name)
    gpu = [{'path': str(WORKSPACE / name), 'sha256': checked_file(WORKSPACE / name, {Path(name).name: checksum})}
           for _, name, checksum in GPU_INPUTS]
    assets = asset_report(args.assets_manifest, args.bdf, args.native_ath12k)
    gaps = list(assets['gaps'])
    kernel_info = {'artifact': args.artifact, 'status': 'pending_download'}
    if artifact.is_dir():
        artifact_sums = sums(artifact / 'SHA256SUMS')
        checksum = checked_file(artifact / 'kernel.development.fuxi', artifact_sums)
        checked_file(artifact / 'fuxi.adt', artifact_sums)
        public = chosen_node(parse_tree((artifact / 'fuxi.adt').read_bytes()))
        require(public.prop('dram-size') == chosen.prop('dram-size') and
                public.prop('fuxi-gpu-memory') == chosen.prop('fuxi-gpu-memory'), 'artifact ADT needs matching 9G layout')
        kernel = (artifact / 'kernel.development.fuxi').read_bytes()
        if args.native_ath12k:
            checked_file(artifact / 'ath12k-link.json', artifact_sums)
            unstripped = checked_file(artifact / 'kernel.development.fuxi.unstripped', artifact_sums)
            linked = json.loads((artifact / 'ath12k-link.json').read_text(encoding='utf-8'))
            require(linked.get('schema') == 'fuxi-ath12k-link-v1' and
                    linked.get('object_sha256') in NATIVE_OBJECTS and
                    linked.get('scan_dwell_provenance_sha256') == NATIVE_OBJECTS.get(linked.get('object_sha256')) and
                    linked.get('kernel_build_target') == 'arm64-apple-macos15.5' and
                    linked.get('macho_platform') == 1 and linked.get('minimum_os') == '15.5' and
                    linked.get('entry_points_defined') is True and
                    linked.get('linked_kernel_sha256') == unstripped,
                    'artifact lacks the verified native ath12k link')
            require(b'FUXI ATH12K: start from PBL' in kernel and b'FUXI ATH12K: scan completed' in kernel,
                    'artifact lacks native ath12k runtime markers')
            if args.wifi_ios:
                require(b'FUXI WIFI IOS: native backend published' in kernel and
                        b'FUXI WIFI IOS: selftest round' in kernel,
                        'artifact lacks the native iOS station bridge')
            if args.wifi_join_test:
                require(b'FUXI WIFI IOS: selftest join with a made-up key' in kernel and
                        b'FUXI WIFI IOS: heard %u MHz' in kernel,
                        'artifact lacks the native iOS station join')
            if args.scan_dwell:
                require(linked.get('scan_dwell_provenance_sha256') is not None and
                        b'FUXI WIFI IOS: scan dwell opt-in %u module support %u' in kernel,
                        'artifact lacks negotiated scan dwell support')
            if args.scan_cache:
                require(b'FUXI WIFI IOS: scan cache opt-in %u max age %u ms' in kernel,
                        'artifact lacks bounded scan cache support')
            if args.wifi_trace:
                require(b'FUXI WIFI IOC383' in kernel,
                        'artifact lacks bounded Wi-Fi caller tracing')
            if args.scan_batch:
                require(b'FUXI WIFI IOS: scan batch opt-in %u budget %u ms' in kernel,
                        'artifact lacks bounded scan batching')
            if args.wifi_rssi_bounds:
                require(b'fuxi,wifi-rssi' in kernel, 'artifact lacks the opt-in RSSI_BOUNDS (106) answer')
            if args.quiet_boot:
                require(b'FUXI QUIET BOOT' in kernel, 'artifact lacks the 0119 quiet boot console')
            if args.wifi_args_adt:
                wifi_args_value(adt_args, kernel)
            if args.daily_tuning:
                # 核心端只有 vsync 偏移與核心遮罩讀得到字串；sweetlog／swapwait／tudebug／tcache 由 userland 讀 kern.bootargs。
                require(b'fuxivsynctoff' in kernel and b'fuxicores' in kernel,
                        'artifact lacks the chain-v7 vsync offset/core mask switches')
        if args.host_cap_secondary:
            require(b'W18 HOST_CAP TLV 0x20 host_build_type SECONDARY=2 len=4' in kernel,
                    'artifact lacks the HOST_CAP SECONDARY encoder marker')
        if args.omit_nm_modem:
            require(b'W18 HOST_CAP TLV 0x13 nm_modem omitted' in kernel,
                    'artifact lacks the HOST_CAP nm_modem omission marker')
        if args.sleep_clock:
            require(b'FUXI WLAN: P17 sleepclk pmk8550 gpio3' in kernel and
                    (args.sleep_clock == 'check' or b'FUXI WLAN: P17 sleepclk enable writes' in kernel),
                    'artifact lacks the P17 sleep-clock markers')
        if args.big_mem:
            require(b'FUXI WLAN: P17 bigmem grants' in kernel, 'artifact lacks the P17 large-chunk grant marker')
        if args.cnss_pdc:
            require(b'FUXI WLAN: M6n PDC consumed %u/13' in kernel, 'artifact lacks the AOP PDC marker')
        if args.errdec:
            require(b'FUXI WLAN: P17 target %u type %u size' in kernel,
                    'artifact lacks the target-memory summary marker')
        markers = (b'FUXI WLAN: W18 sample', b'FUXI WLAN: W15 wlan mode normal ok; stop before CE/HTC',
                   b'FUXI ADSP: fuxiadsp=%u refused with fuxiwlan')
        require(all(marker in kernel for marker in markers), 'artifact lacks W18/MODE milestone/joint-guard markers')
        require(mkpayload.parse_macho(kernel)['cputype'] == 0x0100000c, 'artifact needs arm64 Mach-O')
        kernel_info.update(status='hash_layout_markers_verified', sha256=checksum)
    else:
        gaps.append('kernel artifact pending download for ' + args.artifact)
    resolved_board = bool(args.bdf or args.native_ath12k)
    report = {'profile': 'controlled-ath12k-ram9g-sb127' if args.native_ath12k else 'controlled-w18-ram9g-sb127',
              'source': args.source, 'native_ath12k': args.native_ath12k,
              'wifi_ios': args.wifi_ios, 'wifi_self_test': args.wifi_self_test,
              'scan_dwell': args.scan_dwell,
              'scan_cache': args.scan_cache,
              'wifi_trace': args.wifi_trace,
              'scan_batch': args.scan_batch,
              'wifi_join_test': args.wifi_join_test,
              'wifi_ui_only': args.wifi_ui_only, 'quiet_screen': args.quiet_screen, 'quiet_boot': args.quiet_boot,
              'sample': args.sample,
              'crash_strings': args.crash_strings,
              'stderr_log': args.stderr_log,
              'privs': args.privs,
              'daily_tuning': list(DAILY_TUNING) if args.daily_tuning else None,
              'adt_wifi_args': adt_args,
              'hybrid_turnip': args.hybrid_turnip,
              'profile_process': args.profile, 'profile_delay': args.profile_delay if args.profile else None,
              'tap_script': args.tap_script, 'tap_delay': args.tap_delay if args.tap_script else None,
              'ram_sku_evidence': sku_metadata,
              'mlo_variant': args.mlo,
              'host_cap_secondary': args.host_cap_secondary,
              'omit_nm_modem': args.omit_nm_modem,
              'sleep_clock': args.sleep_clock,
              'big_mem': args.big_mem,
              'cnss_pdc': args.cnss_pdc,
              'errdec': args.errdec,
              'adsp_gate': 'adt-only fuxi,adsp=0' if args.sleep_clock else 'fuxiadsp=0 and adt fuxi,adsp=0',
              'source_payload_sha256': pinned['payload.bin'], 'source_boot_sha256': pinned['boot.img'],
              'kernel': kernel_info, 'command_line': line if resolved_board else None,
              'command_line_template': line + ' fuxiwlanbdf=BDF_FROM_MANIFEST' if not resolved_board else line,
              'command_line_bytes_without_unresolved_bdf': len(line),
              'remaining_bdf_basename_bytes': 607 - len(line) - len(' fuxiwlanbdf=') if not resolved_board else None,
              'removed_arguments': removed, 'shim_source_files_checked': len(inputs),
              'shim_reference': shim_reference.name,
              'shim_reference_boot_sha256': shim_pins['boot.img'],
              'adt_off': list(OFF_PROPS), 'statusbar_shape': 300127, 'root_mapping': mapping,
              'map_record_sha256': digest(args.map_record), 'live_fdt_sha256': digest(args.live_fdt),
              'gpu_inputs': gpu, 'wlan_assets': assets, 'gaps': gaps,
              'ready_to_build': kernel_info['status'] == 'hash_layout_markers_verified' and
                  assets['bdf_recorded'] and bool(assets['provenance']) and
                  (not args.native_ath12k or not assets['gaps']),
              'runtime_assets_recorded_for_root': not assets['gaps']}
    return report, tree, inputs


def tap_p_shots(script):
    """核心 fk_taps 對每個 t／s／p 指令各發一個「FUXI TOUR: shot N」；回傳 p 指令的 N。"""
    shots, number = [], 0
    for command in script.split(';'):
        if command[:1] in ('t', 's', 'p'):
            number += 1
            if command[0] == 'p':
                shots.append(number)
    return shots


def build(args, report, tree, source_inputs):
    require(report['ready_to_build'], 'build needs a verified kernel and board firmware record with provenance')
    output = STORAGE / args.name
    require(output.resolve().is_relative_to(STORAGE.resolve()) and not output.exists(), 'output must be a new loader directory')
    chosen = chosen_node(tree)
    original = {name: (flags, value) for name, flags, value in chosen.props}
    controlled = set(OFF_PROPS) | {'fuxi,tapcmd', 'fuxi,rtc-offset', 'fuxi,haptic-ui', 'fuxi,haptic-env',
                                   'fuxi,wifi-sb', 'fuxi,wifi-rssi', 'fuxi,haptic-amp', 'fuxi,wifi-ux', 'fuxi,args'}
    chosen.props = [(name, flags, value) for name, flags, value in chosen.props if name not in controlled]
    chosen.props.extend((name, 0, struct.pack('<I', 0)) for name in OFF_PROPS)
    require({name: (flags, value) for name, flags, value in chosen.props if name not in controlled} ==
            {name: value for name, value in original.items() if name not in controlled}, 'unplanned ADT property change')
    if args.wifi_ios:
        require(not any(child.name == 'wlan' for child in tree.children), 'source already contains a wlan node')
        address = chosen.prop('mac-address-wifi0')
        require(address is not None and len(address) == 6 and any(address) and not address[0] & 1,
                'native Wi-Fi needs the existing valid iOS identity MAC')
        wlan = adt.Node()
        wlan.props = [('name', 0, b'wlan\0'), ('compatible', 0, b'fuxi,wcn7850-ath12k\0'),
                      ('mac-address', 0, address)]
        tree.children.append(wlan)
    if args.tap_script:
        chosen.props.append(('fuxi,tapcmd', 0, args.tap_script.encode('ascii') + b'\0'))
    if args.statusbar_height is not None:
        # 狀態欄高度（ADT fuxi,sbshape＝寬×1000＋高）；只換高度、保留寬。實測時間中心 y ≈ 高度 − 39.5 px。
        shape = struct.unpack('<I', chosen.prop('fuxi,sbshape'))[0]
        require(30 <= args.statusbar_height <= 150 and 30 <= shape // 1000 <= 627, 'invalid statusbar height')
        chosen.props = [(name, flags, value) for name, flags, value in chosen.props if name != 'fuxi,sbshape']
        chosen.props.append(('fuxi,sbshape', 0, struct.pack('<I', shape // 1000 * 1000 + args.statusbar_height)))
        report['statusbar_shape'] = shape // 1000 * 1000 + args.statusbar_height
    kernel = STORAGE / args.artifact / 'kernel.development.fuxi'
    if args.with_adsp:
        # 聯合驗收：電量（ADSP 3）與手電筒（PMIC 3）跟 WLAN 同開；命令列的 fuxiadsp= 會蓋過 ADT，所以不得存在。
        kernel_bytes = kernel.read_bytes()
        require(b'alongside fuxiwlan (fuxi,adsp-wlan=1' in kernel_bytes and b'fuxi,adsp-wlan' in kernel_bytes,
                'artifact lacks the fuxi,adsp-wlan opt-in')
        require(not any(token.startswith(('fuxiadsp=', 'fuxipmic=')) for token in report['command_line'].split()),
                'command line pins fuxiadsp/fuxipmic, which would override the ADT')
        joint = {'fuxi,adsp': 3, 'fuxi,pmic': 3, 'fuxi,adsp-wlan': 1}
        chosen.props = [(name, flags, value) for name, flags, value in chosen.props if name not in joint]
        chosen.props.extend((name, 0, struct.pack('<I', value)) for name, value in joint.items())
        report['adsp_with_wlan'] = joint
        report['adt_off'] = [name for name in OFF_PROPS if name not in joint]
        report['adsp_gate'] = 'opted in: adt fuxi,adsp=3 fuxi,pmic=3 fuxi,adsp-wlan=1'
    audio_mode = audio_spf_choice(args.audio_spf, args.with_adsp, kernel.read_bytes(), args.audio_spf_format)
    report['audio_spf'] = bool(audio_mode)
    report['audio_spf_format'] = args.audio_spf_format if audio_mode else None
    if args.audio_spf:
        chosen.props = [(name, flags, value) for name, flags, value in chosen.props if name != 'fuxi,audio-spf']
        chosen.props.append(('fuxi,audio-spf', 0, struct.pack('<I', audio_mode)))
        report['adt_off'] = [name for name in report['adt_off'] if name != 'fuxi,audio-spf']
    if args.haptic:
        # 震動：ADT fuxi,haptic=2（DIRECT_PLAY 執行期，sysctl kern.fuxivibrate）或 3（另加開機自測三下 30/100/300 ms）。
        kernel_bytes = kernel.read_bytes()
        require(b'vibrate runtime ready; DIRECT_PLAY' in kernel_bytes and b'fuxivibrate' in kernel_bytes,
                'artifact lacks the HAP525 direct-play runtime')
        require(not any(token.startswith('fuxihaptic=') for token in report['command_line'].split()),
                'command line pins fuxihaptic, which would override the ADT')
        chosen.props = [(name, flags, value) for name, flags, value in chosen.props if name != 'fuxi,haptic']
        chosen.props.append(('fuxi,haptic', 0, struct.pack('<I', args.haptic)))
        report['haptic'] = args.haptic
        report['adt_off'] = [name for name in report['adt_off'] if name != 'fuxi,haptic']
    if args.bt:
        # 藍牙：ADT fuxi,bt=1 只讀調查；3 等 WLAN_EN 穩定 15 秒後開 SE6 時脈／腳位／BT_EN，送 QCA 版本查詢，結束全部還原。
        kernel_bytes = kernel.read_bytes()
        require(b'fuxi,bt' in kernel_bytes and b'board WLAN_EN steady after' in kernel_bytes,
                'artifact lacks the ADT fuxi,bt board probe')
        require(not any(token.startswith('fuxibt=') for token in report['command_line'].split()),
                'command line pins fuxibt, which would override the ADT')
        require(args.bt == 1 or args.native_ath12k, '--bt 3 waits for WLAN_EN, which only native ath12k drives')
        chosen.props = [(name, flags, value) for name, flags, value in chosen.props if name != 'fuxi,bt']
        chosen.props.append(('fuxi,bt', 0, struct.pack('<I', args.bt)))
        report['bt'] = args.bt
        report['adt_off'] = [name for name in report['adt_off'] if name != 'fuxi,bt']
    if args.inject_media:
        # mediaserverd 也注入 libfuxi-sb.dylib（fxinj bit 2）；SpringBoard 的 bit 1 保留。
        kernel_bytes = kernel.read_bytes()
        require(b'mediaserverd gets' in kernel_bytes, 'artifact lacks the mediaserverd injection bit')
        require(not any(token.startswith('fxinj=') for token in report['command_line'].split()),
                'command line pins fxinj, which would override the ADT')
        require(chosen.prop('fuxi,inject') == struct.pack('<I', 2), 'source needs inject2 before adding mediaserverd')
        chosen.props = [(name, flags, value) for name, flags, value in chosen.props if name != 'fuxi,inject']
        chosen.props.append(('fuxi,inject', 0, struct.pack('<I', 6)))
        report['inject'] = 6
    if args.wifi_audit:
        require(args.wifi_ios and b'wifid gets' in kernel.read_bytes(),
                '--wifi-audit needs the native iOS Wi-Fi backend and a kernel with opt-in wifid injection')
        require(not any(token.startswith('fxinj=') for token in report['command_line'].split()),
                'command line pins fxinj, which would override the ADT')
        current = chosen.prop('fuxi,inject')
        require(current in (struct.pack('<I', 2), struct.pack('<I', 6)), 'unexpected injection mode before Wi-Fi audit')
        mode = struct.unpack('<I', current)[0] | 8
        chosen.props = [(name, flags, value) for name, flags, value in chosen.props if name != 'fuxi,inject']
        chosen.props.append(('fuxi,inject', 0, struct.pack('<I', mode)))
        report['inject'] = mode
        report['wifi_audit'] = True
    if args.product_haptics:
        # /product/haptics closed-loop=1：MobileGestalt 的 DeviceSupportsClosedLoopHaptics 才會成立，
        # MediaExperience 才建立震動器（走 VibeSynthEngine → AVHapticServer playVibePattern，由注入的 hook 轉核心）。
        # 只放 closed-loop；supports-3rd-party-haptics 會讓 app 的 CoreHaptics 以為有 Actuator，先不給。
        require(args.haptic and args.inject_media, '--product-haptics needs --haptic and --inject-media')
        product = [node for node in tree.children if node.name == 'product']
        require(len(product) == 1, 'ADT needs one /product node')
        require(not any(node.name == 'haptics' for node in product[0].children), 'ADT already has /product/haptics')
        def max_phandle(node):
            value = node.prop('AAPL,phandle')
            own = struct.unpack('<I', value)[0] if value and len(value) == 4 else 0
            return max([own] + [max_phandle(child) for child in node.children])
        haptics = adt.Node()
        haptics.props = [('closed-loop', 0, struct.pack('<I', 1)), ('name', 0, b'haptics\0'),
                         ('AAPL,phandle', 0, struct.pack('<I', max_phandle(tree) + 1))]
        product[0].children.append(haptics)
        report['product_haptics'] = 'closed-loop'
    if args.haptic_ui_ms or args.haptic_envelope:
        # 震動調整（libfuxi-sb.dylib 讀 ADT /chosen，沒有就是關）：fuxi,haptic-ui＝SpringBoard 在 CoreHaptics engine
        # 從未建成時（AVHapticServer 起不來，client -4810）的 UI 回退脈衝毫秒；fuxi,haptic-env＝mediaserverd 把
        # Atoms 的 Envelope 面積換成等效全開時間（FuxiVibePattern.h fx_vibe_envelope）。
        require(args.haptic, '--haptic-ui-ms/--haptic-envelope need --haptic')
        require(not args.haptic_envelope or args.inject_media, '--haptic-envelope needs --inject-media')
        if args.haptic_ui_ms:
            require(8 <= args.haptic_ui_ms <= 40, '--haptic-ui-ms must be 8..40')
            chosen.props.append(('fuxi,haptic-ui', 0, struct.pack('<I', args.haptic_ui_ms)))
            report['haptic_ui_ms'] = args.haptic_ui_ms
        if args.haptic_envelope:
            chosen.props.append(('fuxi,haptic-env', 0, struct.pack('<I', 1)))
            report['haptic_envelope'] = True
    if args.haptic_amp is not None:
        # 震動振幅上限（ADT /chosen fuxi,haptic-amp，libfuxi-sb.dylib 讀）：DIRECT_PLAY 振幅 PTN 0x26（0xf126，0..255 線性乘上
        # VMAX）。核心 kern.fuxivibrate 的 bit 16..23 帶振幅，VMAX 0xf048 不改；包絡照 10 ms 一格分 16 階。
        require(args.haptic, '--haptic-amp needs --haptic')
        require(1 <= args.haptic_amp <= 255, '--haptic-amp must be 1..255')
        require(b'amplitude<<16' in kernel.read_bytes(), 'artifact lacks the DIRECT_PLAY amplitude field')
        chosen.props.append(('fuxi,haptic-amp', 0, struct.pack('<I', args.haptic_amp)))
        report['haptic_amp'] = args.haptic_amp
    if args.wifi_sb_audit:
        # 狀態欄 Wi-Fi 圖示診斷（libfuxi-sb.dylib FuxiWifiAudit.c，ADT /chosen fuxi,wifi-sb 非 0 才裝）：唯讀記錄
        # SBWiFiManager isPowered／isPrimaryInterface／isAssociated／格數與 provider setWifiActive: 的變化。
        chosen.props.append(('fuxi,wifi-sb', 0, struct.pack('<I', 1)))
        report['wifi_sb_audit'] = True
    if args.wifi_rssi_bounds:
        # wifid 的自動加入用 Apple80211 106（RSSI_BOUNDS）的門檻比對候選網路；核心沒回時門檻是 0，所有負 dBm 的網路都被判
        # 「Below minimum RSSI threshold」。ADT /chosen fuxi,wifi-rssi=1 讓核心回報 s8 上下限 -128／127、門檻 -128（UniXNU zizhan）。
        require(args.wifi_ios, '--wifi-rssi-bounds needs the native iOS Wi-Fi backend')
        chosen.props.append(('fuxi,wifi-rssi', 0, struct.pack('<I', 1)))
        report['wifi_rssi_bounds'] = True
    if args.wifi_ux is not None:
        # Wi-Fi 使用體驗（ADT /chosen fuxi,wifi-ux，核心 fuxi_wifi_ux() 讀一次）：bit 0 開關切換時 GET POWER 立刻回報要求的
        # 狀態、正要關就不再收掃描／加入（開關不彈回）；bit 1 沒指定 BSSID 時照 wpa_supplicant 的比較法以估計速率選 AP；
        # bit 2 已連線時又要求加入，選中的是同一台（或同名但沒有可換的）就不斷線。
        chosen.props.append(('fuxi,wifi-ux', 0, wifi_ux_value(args.wifi_ux, args.wifi_ios, kernel.read_bytes())))
        report['wifi_ux'] = args.wifi_ux
    if args.wifi_args_adt:
        # 補丁 0121：命令列只到 607 bytes，Wi-Fi 開關改放 ADT /chosen fuxi,args，空出位置給 chain-v7 調校參數。
        require(report['adt_wifi_args'] and not any(token.partition('=')[0] in ADT_WIFI_KEYS
                                                     for token in report['command_line'].split()),
                'ADT Wi-Fi arguments must not also stay on the command line')
        chosen.props.append(('fuxi,args', 0, wifi_args_value(report['adt_wifi_args'], kernel.read_bytes())))
    if args.display_gamut:
        # 廣色域：ADT 原為 D22AP 的 P3 → MobileGestalt 回報 deep colour（Aixt/MEN2O2B7f+8m4TxUA），WebKit 改用 b3a8/w30r、
        # MaterialKit 快照用 b3a8，Fuxi GPU 路徑收不下（Safari 黑屏、OutOfMemory(Device) 後 backboardd 改 CPU）。
        # 面板本來就是 8-bit BGRA 掃描，sRGB 才是實際能力。沿用 ksrc/tools/mkadt-fuxi.py set_display_gamut 的寫法。
        product = [node for node in tree.children if node.name == 'product']
        require(len(product) == 1, 'ADT needs one /product node')
        require(product[0].prop('artwork-display-gamut') == b'P3\0', 'source ADT gamut is not the D22AP P3')
        product[0].props = [(name, flags, b'sRGB\0' if name == 'artwork-display-gamut' else value)
                            for name, flags, value in product[0].props]
        report['display_gamut'] = args.display_gamut
    rtc_record = None
    if args.rtc_calibration:
        # 校時：offset 放 ADT /chosen（命令列不夠放），核心沒有 boot-arg 時會讀它；量測需在一小時內。
        spec = importlib.util.spec_from_file_location('rtc_calibration', Path(__file__).with_name('rtc-calibration.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rtc_record = module.load(args.rtc_calibration)
        kernel_bytes = kernel.read_bytes()
        require(b'FUXI RTC: clock set, now=' in kernel_bytes and b'fuxi,rtc-offset' in kernel_bytes,
                'artifact lacks the ADT RTC offset fallback')
        require(not any(token.startswith(('fuxirtc=', 'fuxirtcoffset=')) for token in report['command_line'].split()),
                'command line already carries an RTC override')
        chosen.props.append(('fuxi,rtc-offset', 0, struct.pack('<I', rtc_record['offset_seconds'])))
        report['rtc_offset_seconds'] = rtc_record['offset_seconds']
        report['rtc_captured_at_utc'] = rtc_record['captured_at_utc']
    shim = WORKSPACE / 'ios-fuxi/shim'
    with tempfile.TemporaryDirectory(prefix='.' + args.name + '-', dir=STORAGE) as temporary:
        stage = Path(temporary)
        private = stage / 'private.adt'
        private.write_bytes(adt.serialize(tree))
        payload = stage / 'payload.bin'
        subprocess.run([sys.executable, str(TOOLS / 'mkpayload.py'), str(kernel), str(private), str(payload),
                        '--cmdline', report['command_line']], check=True, stdout=subprocess.DEVNULL)
        packed = payload.read_bytes()
        require(struct.unpack_from('<2Q', packed, 56) == (RAM_BASE, RAM_SIZE) and
                packed[72:680] == report['command_line'].encode('ascii').ljust(608, b'\0'), 'packed RAM/arguments differ')
        offset, size = struct.unpack_from('<2Q', packed, 32)
        require(packed[offset:offset + size] == private.read_bytes(), 'packed private ADT differs')
        assembly = ['.section .gpu_fw,"a"']
        for label, name, _ in GPU_INPUTS:
            assembly.extend(('.balign 4', f'.global _{label}_fw_start', f'_{label}_fw_start:',
                             '.incbin ' + json.dumps((WORKSPACE / name).as_posix()),
                             f'.global _{label}_fw_end', f'_{label}_fw_end:'))
        (stage / 'gpu-fw.S').write_text('\n'.join(assembly) + '\n', encoding='utf-8', newline='\n')
        (stage / 'payload.S').write_text('.section .payload,"a"\n.incbin ' + json.dumps(payload.as_posix()) + '\n',
                                       encoding='utf-8', newline='\n')
        flags = ['--target=aarch64-none-elf', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib', '-fno-pic',
                 '-fno-stack-protector', '-mgeneral-regs-only', '-mstrict-align', '-Wall', '-Wextra', '-Werror',
                 '-DFUXI=1', '-DFUXI_XNU_LOADER=1', '-DFUXI_RAM_9G=1', '-I' + str(shim)]
        sources = [shim / 'fuxi-loader/start.S', shim / 'fuxi-loader/loader.c', shim / 'console.c',
                   shim / 'fuxi-probe/probe.c', stage / 'gpu-fw.S', stage / 'payload.S']
        objects = []
        for source in sources:
            target = stage / (source.stem + '.o')
            subprocess.run([str(args.compiler_dir / 'clang.exe'), *flags, '-c', str(source), '-o', str(target)], check=True)
            if source.suffix == '.c':
                relocations = subprocess.check_output([str(args.compiler_dir / 'llvm-readelf.exe'), '-r', str(target)], text=True)
                require('R_AARCH64_ABS' not in relocations, 'absolute C relocation in ' + str(source))
            objects.append(target)
        subprocess.run([str(args.compiler_dir / 'ld.lld.exe'), '-T', str(shim / 'fuxi-loader/loader.ld'),
                        '--build-id=none', *map(str, objects), '-o', str(stage / 'loader.elf')], check=True)
        subprocess.run([str(args.compiler_dir / 'llvm-objcopy.exe'), '-O', 'binary', str(stage / 'loader.elf'),
                        str(stage / 'Image')], check=True)
        image = (stage / 'Image').read_bytes()
        require(struct.unpack_from('<Q', image, 16)[0] == len(image) and image[56:60] == b'ARM\x64' and
                image.count(packed) == 1, 'loader Image header/payload differs')
        for _, name, _ in GPU_INPUTS:
            require(image.count((WORKSPACE / name).read_bytes()) == 1, 'loader GPU asset embedding differs')
        subprocess.run([sys.executable, str(WORKSPACE / 'uefi-fuxi/Resources/Scripts/mkbootimg.py'),
                        '--header_version', '4', '--kernel', str(stage / 'Image'), '--os_version', '16.0.0',
                        '--os_patch_level', '2026-08', '-o', str(stage / 'boot.img')], check=True)
        boot = (stage / 'boot.img').read_bytes()
        require(boot[:8] == b'ANDROID!' and boot.count(image) == 1, 'boot image embedding differs')
        checked_file(kernel, {'kernel.development.fuxi': report['kernel']['sha256']})
        for name in source_inputs:
            checked_file(shim / name, source_inputs, name)
        require(digest(args.map_record) == report['map_record_sha256'] and
                digest(args.live_fdt) == report['live_fdt_sha256'], 'mapping/FDT input changed during build')
        for item in report['gpu_inputs']:
            require(digest(Path(item['path'])) == item['sha256'], 'GPU input changed during build')
        if args.assets_manifest:
            require(digest(args.assets_manifest) == report['wlan_assets']['manifest_sha256'], 'asset manifest changed during build')
        (stage / 'sha256.txt').write_text(f'{digest(kernel)}  kernel.development.fuxi\n{digest(payload)}  payload.bin\n'
                                          f'{digest(stage / "boot.img")}  boot.img\n', encoding='utf-8', newline='\n')
        (stage / 'source.txt').write_text(args.source + '\n' + args.artifact + '\n', encoding='utf-8', newline='\n')
        if rtc_record is not None:
            (stage / 'rtc-calibration.json').write_text(json.dumps(rtc_record, ensure_ascii=False, indent=2) + '\n',
                                                       encoding='utf-8', newline='\n')
        p_shots = tap_p_shots(args.tap_script) if args.tap_script else []
        if p_shots:
            # fuxi-xnu-monitor.py 只截這幾號（每個 t／s 也會發標記，全截會讓 USB 一直斷）
            (stage / 'tour-shots.txt').write_text(','.join(map(str, p_shots)) + '\n', encoding='ascii', newline='\n')
        (stage / 'source-input-sha256.txt').write_text(''.join(checksum + '  ' + name + '\n'
                                                           for name, checksum in sorted(source_inputs.items())),
                                                       encoding='utf-8', newline='\n')
        (stage / 'memory-layout.json').write_text(json.dumps({'layout': '9g', 'base': RAM_BASE, 'usable': RAM_SIZE,
            **report['ram_sku_evidence'],
            'scratch': GPU_BASE, 'scratch_size': GPU_SIZE, 'live_fdt_sha256': report['live_fdt_sha256'],
            'statusbar_shape': report['statusbar_shape'], 'pmic_mode': 0, 'ramtest': False, 'statusbar_check': False},
            indent=2) + '\n',
                                                   encoding='utf-8', newline='\n')
        report.update(output=str(output), payload_sha256=digest(payload), boot_sha256=digest(stage / 'boot.img'))
        profile_name = 'wlan-ath12k-profile.json' if args.native_ath12k else 'wlan-w18-profile.json'
        (stage / profile_name).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
        os.rename(stage, output)


def self_test():
    ux_marker = b'FUXI WIFI IOS: ux options 0x%x\0fuxi,wifi-ux'
    ux_marker5 = ux_marker + b'\0FUXI WIFI IOS: ux options 0x%x (power-asked %u, pick-rate %u, keep-link %u, ' \
                             b'country %u, power-same %u)\n'
    require(wifi_ux_value(7, True, ux_marker) == struct.pack('<I', 7) and
            wifi_ux_value(1, True, ux_marker) == struct.pack('<I', 1) and
            wifi_ux_value(31, True, ux_marker5) == struct.pack('<I', 31) and
            wifi_ux_value(16, True, ux_marker5) == struct.pack('<I', 16), 'wifi-ux value differs')
    for selectors in ((0, True, ux_marker), (8, True, ux_marker), (31, True, ux_marker), (32, True, ux_marker5),
                      (True, True, ux_marker), ('3', True, ux_marker),
                      (3, False, ux_marker), (3, 1, ux_marker), (3, True, b'fuxi,wifi-ux'),
                      (3, True, b'FUXI WIFI IOS: ux options 0x%x')):
        try:
            wifi_ux_value(*selectors)
        except ValueError:
            continue
        raise ValueError('invalid wifi-ux accepted')
    args_marker = b'fuxi,args'
    require(wifi_args_value('fuxiwlanath=1 fuxiwifiios=2', args_marker) == b'fuxiwlanath=1 fuxiwifiios=2\0',
            'ADT Wi-Fi argument value differs')
    for selectors in (('fuxiwlanath=1', b''), ('', args_marker), ('fuxiwlan=1', args_marker),
                      ('fuxiwifitest=1', args_marker), ('fuxiwlanath=1  fuxiwifiios=2', args_marker),
                      ('fuxiwlanath=1 fuxiwlanath=2', args_marker), ('fuxiwlanath=1\0', args_marker),
                      ('sweetlog=0', args_marker), ('fuxiwlanath=' + '1' * 260, args_marker), (b'fuxiwlanath=1', args_marker)):
        try:
            wifi_args_value(*selectors)
        except (ValueError, TypeError):
            continue
        raise ValueError('invalid ADT Wi-Fi arguments accepted')
    marker = b'FUXI AUDIO SPF: state query queued bytes\0fuxi,audio-spf'
    require(audio_spf_choice(False, False, b'') == 0 and
            audio_spf_choice(True, True, marker) == 1 and
            audio_spf_choice(True, True, marker, 'bare') == 2, 'audio SPF gate differs')
    for selectors in ((True, False, marker), (True, True, b''),
                      (1, True, marker), (False, 1, marker),
                      (False, False, marker, 'bare'), (True, True, marker, 'invalid')):
        try:
            audio_spf_choice(*selectors)
        except ValueError:
            continue
        raise ValueError('invalid audio SPF gate accepted')
    payload = (STORAGE / SOURCE / 'payload.bin').read_bytes()
    original = payload[72:680].split(b'\0', 1)[0].decode('ascii')
    line, removed = arguments(original, 'fixture.elf')
    require(len(line) < 608 and 'fuxiadsp=0' in line and 'fuxiwlanw18=1' in line and
            'fuxiwlanqrtr=5' in line and not any(token.startswith('fuxiwlanw16=') for token in line.split()), 'profile selector test failed')
    require('serial=3' in line and 'fuxigpuncimport=2405960' in line and 'debug=12' in removed, 'bootstrap test failed')
    require(len(arguments(original, 'a' * 30)[0]) == 607, 'BDF command-line boundary test failed')
    for invalid in ('../board.elf', '', 'board file', 'a' * 31, 'a' * 64):
        try:
            arguments(original, invalid)
        except ValueError:
            continue
        raise ValueError('invalid/oversized BDF accepted')
    try:
        arguments(original + ' cpus=7', 'fixture.elf')
    except ValueError:
        pass
    else:
        raise ValueError('duplicate boot argument accepted')
    offset, size = struct.unpack_from('<2Q', payload, 32)
    chosen = chosen_node(parse_tree(payload[offset:offset + size]))
    record = json.loads((WORKSPACE / 'work/xiaomi13-ios-gpu-20261108/managed-native-map-current.json').read_text(encoding='utf-8'))
    verify_map(record, chosen)
    for mutation in ('pin', 'extent', 'dm', 'flags'):
        altered = copy.deepcopy(record)
        if mutation == 'pin':
            altered['pin'] = 'pin_rc=1 moved=1'
        elif mutation == 'extent':
            altered['items'][0]['extents'][0][1] += 4096
        elif mutation == 'dm':
            altered['dm'][1] = 'invalid'
        else:
            altered['items'][0]['flags'] = 0
        try:
            verify_map(altered, chosen)
        except ValueError:
            continue
        raise ValueError('changed mapping accepted for ' + mutation)
    require(not asset_report(None, None)['bdf_recorded'], 'missing BDF test failed')
    source_line = payload[72:680].split(b'\0', 1)[0].decode('ascii')
    for variant in (0, 1, 2):
        line, _ = arguments(source_line, 'bd_m3.elf', variant)
        require(len(line.encode('ascii')) < 608 and 'fuxiadsp=0' in line.split(), 'MLO profile bounds/ADSP gate failed')
        require(('fuxiwlanmlo=' + str(variant) in line.split()) == bool(variant), 'MLO selector differs')
    for variant in (-1, 3, True):
        try:
            arguments(source_line, 'bd_m3.elf', variant)
        except ValueError:
            continue
        raise ValueError('invalid MLO profile accepted')
    baseline, baseline_removed = arguments(source_line, 'bd_m3.elf')
    disabled, disabled_removed = arguments(source_line, 'bd_m3.elf', host_cap_secondary=False)
    require(disabled == baseline and disabled_removed == baseline_removed and
            not any(token.startswith('fuxiwlancap') for token in disabled.split()), 'HOST_CAP default-off changed')
    secondary, secondary_removed = arguments(source_line, 'bd_m3.elf', host_cap_secondary=True)
    require(secondary == baseline + ' fuxiwlancap=1' and secondary_removed == baseline_removed and
            secondary.split().count('fuxiwlancap=1') == 1 and
            not any(token.startswith('fuxiwlanmlo') for token in secondary.split()), 'HOST_CAP single-variable test failed')
    omitted, omitted_removed = arguments(source_line, 'bd_m3.elf', host_cap_secondary=True, omit_nm_modem=True)
    require(omitted == secondary.replace('fuxiwlancap=1', 'fuxiwlancap=2') and
            omitted_removed == secondary_removed and len(omitted) == len(secondary),
            'nm_modem omission must change only the selector in the SECONDARY baseline')
    for secondary_selector, omitted_selector in ((False, True), (True, 0), (True, 1), (True, None), (True, '1')):
        try:
            arguments(source_line, 'bd_m3.elf', host_cap_secondary=secondary_selector,
                      omit_nm_modem=omitted_selector)
        except ValueError:
            continue
        raise ValueError('invalid nm_modem omission profile accepted')
    remaining = 607 - len(arguments(source_line, None, host_cap_secondary=True)[0]) - len(' fuxiwlanbdf=')
    require(1 <= remaining <= 63 and
            len(arguments(source_line, 'a' * remaining, host_cap_secondary=True)[0]) == 607,
            'HOST_CAP command-line boundary test failed')
    invalid_profiles = [(source_line, variant, True) for variant in (1, 2)]
    invalid_profiles += [(source_line + f' fuxiwlanmlo={variant}', 0, True) for variant in (0, 1, 2)]
    invalid_profiles += [(source_line, 0, selector) for selector in (0, 1, None, '1')]
    for token in ('fuxiwlancap', 'fuxiwlancap=', 'fuxiwlancap=0', 'fuxiwlancap=1', 'fuxiwlancap=2',
                  'fuxiwlancap=01', 'fuxiwlancap=-1', 'fuxiwlancap=invalid'):
        invalid_profiles.extend((source_line + ' ' + token, 0, selector) for selector in (False, True))
    for candidate, variant, selector in invalid_profiles:
        try:
            arguments(candidate, 'bd_m3.elf', variant, selector)
        except ValueError:
            continue
        raise ValueError('inherited/mixed/invalid HOST_CAP profile accepted')
    try:
        arguments(source_line, 'a' * (remaining + 1), host_cap_secondary=True)
    except ValueError:
        pass
    else:
        raise ValueError('oversized HOST_CAP command line accepted')
    for selector, token in (('check', 'fuxiwlanmlo=64'), ('on', 'fuxiwlanmlo=192')):
        clocked, clocked_removed = arguments(source_line, 'bd_m3.elf', host_cap_secondary=True, omit_nm_modem=True,
                                             sleep_clock=selector)
        expected = [item for item in omitted.split() if item != 'fuxiadsp=0'] + [token]
        require(clocked.split() == expected and clocked_removed == omitted_removed and
                len(clocked.encode('ascii')) < 608, 'sleep-clock profile must only swap the ADSP token for the P17 selector')
        plain, _ = arguments(source_line, 'bd_m3.elf', sleep_clock=selector)
        require(plain.split() == [item for item in baseline.split() if item != 'fuxiadsp=0'] + [token],
                'sleep-clock baseline profile differs')
    require(arguments(source_line, 'bd_m3.elf', sleep_clock=None)[0] == baseline, 'sleep-clock default-off changed')
    clock_on, _ = arguments(source_line, 'bd_m3.elf', sleep_clock='on')
    big, _ = arguments(source_line, 'bd_m3.elf', sleep_clock='on', big_mem=True)
    require(big.split() == clock_on.split()[:-1] + ['fuxiwlanmlo=704'] and clock_on.split()[-1] == 'fuxiwlanmlo=192' and
            len(big) == len(clock_on), 'large-chunk profile must differ from sleep-clock on only by the selector value')
    for selector, flag in ((None, True), ('check', True), ('on', 1), ('on', 'yes')):
        try:
            arguments(source_line, 'bd_m3.elf', sleep_clock=selector, big_mem=flag)
        except ValueError:
            continue
        raise ValueError('invalid large-chunk profile accepted')
    dec, _ = arguments(source_line, 'bd_m3.elf', sleep_clock='on', big_mem=True, errdec=True)
    require(dec.split() == big.split()[:-1] + ['fuxiwlanmlo=960'] and len(dec) == len(big),
            'target-memory summary profile must differ from the large-chunk profile only by its selector')
    for options in ({'sleep_clock': 'on', 'errdec': True}, {'errdec': True},
                    {'sleep_clock': 'on', 'big_mem': True, 'errdec': 1}):
        try:
            arguments(source_line, 'bd_m3.elf', **options)
        except ValueError:
            continue
        raise ValueError('invalid target-memory summary profile accepted')
    pdc, _ = arguments(source_line, 'bd_m3.elf', sleep_clock='on', big_mem=True, cnss_pdc=True)
    require(pdc.split() == [item for item in big.split() if item != 'fuxiperfidle=1000'] + ['fuxiwlancnss=pdc'] and
            'fuxiperfidle=1000' in big.split() and len(pdc.encode('ascii')) < 608,
            'AOP PDC profile must only swap the idle-governor token for its selector')
    big_cap, _ = arguments(source_line, 'bd_m3.elf', host_cap_secondary=True, omit_nm_modem=True, sleep_clock='on', big_mem=True)
    pdc_cap, _ = arguments(source_line, 'bd_m3.elf', host_cap_secondary=True, omit_nm_modem=True, sleep_clock='on',
                           big_mem=True, cnss_pdc=True)
    require(pdc_cap.split() == [item for item in big_cap.split() if item != 'fuxiperfidle=1000'] + ['fuxiwlancnss=pdc'] and
            'fuxiwlancap=2' in pdc_cap.split() and len(pdc_cap.encode('ascii')) < 608,
            'AOP PDC profile with the HOST_CAP selector differs from the trip-27 profile by more than its selector')
    for options in ({'sleep_clock': 'on'}, {}, {'sleep_clock': 'on', 'big_mem': True, 'cnss_pdc': 1}):
        options.setdefault('cnss_pdc', True)
        try:
            arguments(source_line, 'bd_m3.elf', **options)
        except ValueError:
            continue
        raise ValueError('invalid AOP PDC profile accepted')
    for variant, selector in ((1, 'on'), (2, 'check'), (0, 'off'), (0, True), (0, 192)):
        try:
            arguments(source_line, 'bd_m3.elf', variant, sleep_clock=selector)
        except ValueError:
            continue
        raise ValueError('invalid sleep-clock profile accepted')
    try:
        arguments(source_line + ' fuxiwlanmlo=1', 'bd_m3.elf', sleep_clock='on')
    except ValueError:
        pass
    else:
        raise ValueError('inherited MLO accepted with the sleep-clock selector')
    with tempfile.TemporaryDirectory(prefix='fuxi-w18-assets-test-') as temporary:
        directory = Path(temporary)
        asset = directory / 'fixture.elf'
        asset.write_bytes(b'host-test-asset')
        manifest = directory / 'assets.json'
        manifest.write_text(json.dumps({'provenance': '合成主機測試資料', 'root_path': ROOT_PATH,
            'files': {'fixture.elf': {'sha256': digest(asset), 'bytes': asset.stat().st_size, 'host_path': asset.name}}},
                                      ensure_ascii=False), encoding='utf-8', newline='\n')
        result = asset_report(manifest, asset.name)
        require(result['bdf_recorded'] and result['files'][-1]['status'] == 'local_hash_verified', 'asset verification failed')
        asset.write_bytes(b'changed')
        try:
            asset_report(manifest, asset.name)
        except ValueError:
            pass
        else:
            raise ValueError('changed asset accepted')
    native, native_removed = arguments(original, None, sleep_clock='on', native_ath12k=True)
    native_tokens = native.split()
    require([token for token in native_tokens if token.startswith('fuxiwlan')] ==
            ['fuxiwlan=1', 'fuxiwlanath=1', 'fuxiwlanmlo=192'] and
            not any(token.startswith(('fuxiadsp=', 'fuxitap', 'fuxitour')) for token in native_tokens) and
            len(native.encode('ascii')) < 608 and native_removed,
            'native ath12k must exclusively own the protocol path without synthetic input')
    native_ios, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                              wifi_ios=True, wifi_self_test=True)
    require(native_ios == native + ' fuxiwifiios=2 fuxiwifitest=1' and len(native_ios) < 608,
            'native iOS station selectors differ')
    native_join, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                               wifi_ios=True, wifi_join_ssid='test-net_5G')
    require(native_join == native + ' fuxiwifiios=2 fuxiwifitest=2 fuxiwifitestssid=test-net_5G' and
            len(native_join) < 608, 'native Wi-Fi join test selectors differ')
    for options in ({'wifi_join_ssid': 'test-net'}, {'wifi_ios': True, 'wifi_join_ssid': 'two words'},
                    {'wifi_ios': True, 'wifi_join_ssid': ''}, {'wifi_ios': True, 'wifi_join_ssid': 'x' * 33},
                    {'wifi_ios': True, 'wifi_self_test': True, 'wifi_join_ssid': 'test-net'},
                    {'wifi_ios': True, 'tap_script': 'p1000', 'wifi_join_ssid': 'test-net'}):
        try:
            arguments(original, None, sleep_clock='on', native_ath12k=True, **options)
        except ValueError:
            continue
        raise ValueError('unbacked native Wi-Fi join test accepted')
    native_ui, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                             wifi_ios=True, tap_script='t837,953;p1000', tap_delay=85)
    require(native_ui == native + ' fuxiwifiios=2 fuxitaps=85' and len(native_ui) < 608,
            'native UI taps selectors differ')
    dwell, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                         wifi_ios=True, scan_dwell=True)
    require(dwell == native + ' fuxiwifiios=2 fuxiwlandwell=1' and len(dwell) < 608,
            'scan dwell selector differs')
    cached, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                          wifi_ios=True, scan_cache=True)
    require(cached == native + ' fuxiwifiios=2 fuxiwlancache=1' and len(cached) < 608,
            'scan cache selector differs')
    traced, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                          wifi_ios=True, wifi_trace=True)
    require(traced == native + ' fuxiwifiios=2 fuxiwifitrace=1' and len(traced) < 608,
            'Wi-Fi trace selector differs')
    teed, _ = arguments(original, None, sleep_clock='on', native_ath12k=True, stderr_log='mediaserverd')
    inherited_tee = [token for token in native.split() if token.startswith('sweetnull=')]
    expected_tee = (inherited_tee[0] if inherited_tee else 'sweetnull=backboardd,SpringBoard') + ',mediaserverd'
    require(teed == ' '.join(token for token in native.split() if not token.startswith('sweetnull=')) +
            ' ' + expected_tee and len(teed) < 608,
            'stderr log selector differs')
    for bad in ('SpringBoard', 'a b', 'x;y', ''):
        try:
            arguments(original, None, sleep_clock='on', native_ath12k=True, stderr_log=bad)
        except ValueError:
            continue
        raise ValueError('invalid stderr log list accepted')
    batched, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                           wifi_ios=True, scan_dwell=True, scan_batch=True)
    require(batched == native + ' fuxiwifiios=2 fuxiwlandwell=1 fuxiwlanbatch=1' and len(batched) < 608,
            'scan batch selector differs')
    for options in ({'scan_dwell': True}, {'wifi_ios': True, 'scan_dwell': 1},
                    {'scan_cache': True}, {'wifi_ios': True, 'scan_cache': 1},
                    {'wifi_trace': True}, {'wifi_ios': True, 'wifi_trace': 1},
                    {'scan_batch': True}, {'wifi_ios': True, 'scan_batch': True},
                    {'wifi_ios': True, 'scan_dwell': True, 'scan_batch': 1}):
        try:
            arguments(original, None, sleep_clock='on', native_ath12k=True, **options)
        except ValueError:
            continue
        raise ValueError('invalid scan dwell selector accepted')
    privileged, _ = arguments(original, None, sleep_clock='on', native_ath12k=True, wifi_ios=True,
                              privs=True, tap_script='p1000')
    require(privileged == native + ' fuxiwifiios=2 fuxiprivs=1 fuxitaps=85' and len(privileged) < 608,
            'entitlement privilege selector differs')
    for source, options in ((original, {'privs': 1}), (original, {'native_ath12k': False, 'privs': True}),
                            (original + ' fuxiprivs=1', {'privs': True}), (original + ' fuxiprivs=1', {})):
        try:
            arguments(source, None, sleep_clock='on', **({'native_ath12k': True} | options))
        except ValueError:
            continue
        raise ValueError('invalid entitlement privilege selector accepted')
    hybrid, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                          wifi_ios=True, hybrid_turnip=True, tap_script='p1000')
    require(hybrid == native + ' fuxiwifiios=2 fuxitudebug=hyb fuxitaps=85' and len(hybrid) < 608,
            'hybrid Turnip selector differs')
    for source, options in ((original, {'hybrid_turnip': 1}),
                            (original, {'native_ath12k': False, 'hybrid_turnip': True}),
                            (original + ' fuxitudebug=hyb', {'hybrid_turnip': True})):
        try:
            arguments(source, None, sleep_clock='on', **({'native_ath12k': True} | options))
        except ValueError:
            continue
        raise ValueError('invalid or inherited hybrid Turnip selector accepted')
    native_ui_only, _ = arguments(original, None, sleep_clock='on', native_ath12k=True, wifi_ios=True,
                                  tap_script='p1000', wifi_ui_only='test-net', quiet_screen=True,
                                  sample='coreduetd')
    require(native_ui_only == native + ' fuxiwifiios=2 fuxiwifitest=3 fuxiwifitestssid=test-net '
            'sweetfb_noconsole=1 sweetsample=coreduetd fuxitaps=85' and len(native_ui_only) < 608,
            'native UI list filter selectors differ')
    quiet, _ = arguments(original, None, sleep_clock='on', native_ath12k=True, wifi_ios=True, quiet_boot=True)
    require(quiet == native + ' fuxiwifiios=2 sweetfb_noconsole=2' and len(quiet) < 608, 'quiet boot selector differs')
    # chain-v7 調校＋ADT Wi-Fi 參數：上一趟 wifiux 的組合（去掉 trace、stderr 只留 wifid）加上 7 個調校 token。
    tuned, _, moved = arguments(original, None, sleep_clock='on', native_ath12k=True, wifi_ios=True, scan_dwell=True,
                                scan_batch=True, quiet_boot=True, stderr_log='wifid', daily_tuning=True,
                                wifi_args_adt=True)
    tuned_tokens = tuned.split()
    base_tokens = [token for token in native.split() if not token.startswith(('sweetnull=', 'fuxiwlanath=', 'fuxiwlanmlo='))]
    require(tuned_tokens[:len(base_tokens)] == base_tokens and 'fuxiwlan=1' in tuned_tokens and
            all(token in tuned_tokens for token in DAILY_TUNING) and 'sweetfb_noconsole=2' in tuned_tokens and
            any(token.startswith('sweetnull=') and token.endswith(',wifid') for token in tuned_tokens) and
            not any(token.partition('=')[0] in ADT_WIFI_KEYS for token in tuned_tokens) and
            len(tuned.encode('ascii')) < 608, 'daily tuning with ADT Wi-Fi arguments differs')
    require(moved == 'fuxiwlanath=1 fuxiwlanmlo=192 fuxiwifiios=2 fuxiwlandwell=1 fuxiwlanbatch=1' and
            wifi_args_value(moved, args_marker) == moved.encode('ascii') + b'\0', 'ADT Wi-Fi argument split differs')
    plain_tuned, _ = arguments(original, None, sleep_clock='on', native_ath12k=True, wifi_ios=True, daily_tuning=True)
    require(plain_tuned == native + ' ' + ' '.join(DAILY_TUNING) + ' fuxiwifiios=2' and len(plain_tuned) < 608,
            'daily tuning selector differs')
    for options in ({'daily_tuning': True, 'hybrid_turnip': True}, {'daily_tuning': 1},
                    {'wifi_args_adt': True}, {'wifi_ios': True, 'wifi_args_adt': 1}):
        try:
            arguments(original, None, sleep_clock='on', native_ath12k=True, **options)
        except ValueError:
            continue
        raise ValueError('invalid daily tuning or ADT Wi-Fi selector accepted')
    for options in ({'daily_tuning': True}, {'wifi_args_adt': True}):
        try:
            arguments(original, 'fixture.elf', **options)
        except ValueError:
            continue
        raise ValueError('daily tuning or ADT Wi-Fi arguments accepted outside native ath12k')
    require('sweetfb_noconsole' in DROP_KEYS and not any(token.startswith('sweetfb_noconsole=') for token in native.split()),
            'inherited console selector survives')
    for options in ({'quiet_boot': True, 'quiet_screen': True}, {'quiet_boot': 1}):
        try:
            arguments(original, None, sleep_clock='on', native_ath12k=True, **options)
        except ValueError:
            continue
        raise ValueError('invalid or inherited quiet boot selector accepted')
    try:
        arguments(original, 'fixture.elf', quiet_boot=True)
    except ValueError:
        pass
    else:
        raise ValueError('quiet boot accepted outside native ath12k')
    profiled, _ = arguments(original, None, sleep_clock='on', native_ath12k=True,
                            profile='coreduetd', profile_delay=60)
    require(profiled == native + ' sweetprof=60 sweetprofname=coreduetd' and len(profiled) < 608,
            'named process profiler selectors differ')
    for options in ({'profile': ''}, {'profile': 'a b'}, {'profile': 'x' * 32},
                    {'profile': 'coreduetd', 'profile_delay': True},
                    {'profile': 'coreduetd', 'profile_delay': 0},
                    {'profile': 'coreduetd', 'profile_delay': 301}, {'profile_delay': 30}):
        try:
            arguments(original, None, sleep_clock='on', native_ath12k=True, **options)
        except ValueError:
            continue
        raise ValueError('invalid process profiler selector accepted')
    for inherited in ('sweetprof=60', 'sweetprofname=coreduetd'):
        try:
            arguments(original + ' ' + inherited, None, sleep_clock='on', native_ath12k=True,
                      profile='coreduetd')
        except ValueError:
            continue
        raise ValueError('inherited process profiler selector accepted')
    require(tap_p_shots('s1,2,3,4,300;w100;t1,2;p300;w9;t5,6;p500') == [3, 5] and tap_p_shots('t1,2;w5') == [],
            'tour shot numbering differs from fk_taps')
    for options in ({'wifi_ios': True, 'wifi_ui_only': 'test-net'},
                    {'wifi_ios': True, 'tap_script': 'p1000', 'wifi_ui_only': 'two words'},
                    {'wifi_ios': True, 'tap_script': 'p1000', 'sample': 'a b'}):
        try:
            arguments(original, None, sleep_clock='on', native_ath12k=True, **options)
        except ValueError:
            continue
        raise ValueError('unbacked native UI test option accepted')
    for options in ({'wifi_ios': True}, {'wifi_self_test': True},
                    {'native_ath12k': True, 'sleep_clock': 'on', 'wifi_self_test': True}):
        try:
            arguments(original, None, **options)
        except ValueError:
            continue
        raise ValueError('unbacked native iOS station selector accepted')
    for options in ({'bdf': 'board.elf'}, {'mlo': 1}, {'host_cap_secondary': True},
                    {'big_mem': True}, {'cnss_pdc': True}, {'errdec': True},
                    {'sleep_clock': None}, {'sleep_clock': 'check'}, {'native_ath12k': 1}):
        selected = dict(bdf=None, sleep_clock='on', native_ath12k=True)
        selected.update(options)
        try:
            arguments(original, **selected)
        except ValueError:
            continue
        raise ValueError('incompatible native ath12k profile accepted')
    for inherited in ('fuxiwlan=1', 'fuxiwlanprobe=civac', 'fuxiwlanqrtr=5',
                      'fuxiwifiios=1', 'fuxiwifiios=2', 'fuxiwifitest=1'):
        try:
            arguments(original + ' ' + inherited, None, sleep_clock='on', native_ath12k=True)
        except ValueError:
            continue
        raise ValueError('inherited native ath12k selector accepted')
    require(not asset_report(None, None, True)['bdf_recorded'],
            'native ath12k must require a board-2.bin record')
    print('PASS W18 and native ath12k host profiles, selector refusals/bounds, board records, ADT round trip, recorded pin/extents/DM and asset hashes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'build', 'self-test'))
    parser.add_argument('--source', default=SOURCE)
    parser.add_argument('--shim-reference',
                        help='Pin current shim files to a separately verified loader; retain the controlled payload source')
    parser.add_argument('--artifact', default=ARTIFACT)
    parser.add_argument('--name', default='native-wlan-w18-ram9g-sb127-loader')
    parser.add_argument('--bdf')
    parser.add_argument('--native-ath12k', action='store_true',
                        help='Use the verified native module from PBL with board-2.bin and no legacy MHI/QMI selectors')
    parser.add_argument('--wifi-ios', action='store_true',
                        help='Enable the native iOS station bridge and wlan DT discovery node')
    parser.add_argument('--scan-dwell', action='store_true',
                        help='Opt in to bounded scan dwell via the negotiated ath12k extension')
    parser.add_argument('--scan-cache', action='store_true',
                        help='Allow FAST scans to reuse a covered completed scan for at most five seconds')
    parser.add_argument('--wifi-trace', action='store_true',
                        help='Trace at most two unsupported native wifid ioctl 383 calls without reading their data')
    parser.add_argument('--scan-batch', action='store_true',
                        help='Split dwell scans within each module timeout and a 25-second total budget')
    parser.add_argument('--wifi-self-test', action='store_true',
                        help='Run two native station power and scan rounds; requires --wifi-ios')
    parser.add_argument('--wifi-join-test', metavar='SSID',
                        help='Join this network once with a made-up passphrase (expects EAUTH); requires --wifi-ios')
    parser.add_argument('--wifi-ui-only', metavar='SSID',
                        help='UI test: wifid hears only this network, so the first list row is it; needs --tap-script')
    parser.add_argument('--quiet-screen', action='store_true',
                        help='Keep the kernel console off the GUI (sweetfb_noconsole=1) for clean screenshots')
    parser.add_argument('--quiet-boot', action='store_true',
                        help='0119 sweetfb_noconsole=2: no kernel console on screen from vcattach on (panics still '
                             'show; the persistent log is unchanged); exclusive with --quiet-screen')
    parser.add_argument('--hybrid-turnip', action='store_true',
                        help='Use the separately staged hybrid ICD with fuxitudebug=hyb')
    parser.add_argument('--sample', metavar='PROCS',
                        help='Thread sampler for these processes (sweetsample=, comma separated)')
    parser.add_argument('--profile', metavar='PROCESS',
                        help='Collect a 60-second CPU profile of this process; needs sweetprofname kernel support')
    parser.add_argument('--profile-delay', type=int, default=60, metavar='SECONDS',
                        help='Start the process CPU profile after 30..300 seconds (default: 60)')
    parser.add_argument('--crash-strings', metavar='PROCS',
                        help='On SIGABRT, print the heap strings of these processes (sweetscan=, comma separated)')
    parser.add_argument('--stderr-log', metavar='PROCS',
                        help='Also tee the /dev/null stderr of these programs into the kernel log (sweetnull), '
                             'after backboardd and SpringBoard')
    parser.add_argument('--privs', action='store_true',
                        help='fuxiprivs=1: grant a privilege when the asking process carries its entitlement (0107)')
    parser.add_argument('--rtc-calibration', type=Path,
                        help='Fresh rtc-calibration.py capture; carried as ADT /chosen fuxi,rtc-offset')
    parser.add_argument('--tap-script', help='Isolated native iOS UI test; store commands in the ADT')
    parser.add_argument('--tap-delay', type=int, default=85, help='UI test delay in seconds, 30..300')
    parser.add_argument('--statusbar-height', type=int, metavar='PX',
                        help='Replace the height part of ADT fuxi,sbshape (time centre y is about height - 39.5 px)')
    parser.add_argument('--with-adsp', action='store_true',
                        help='Combined test: ADT fuxi,adsp=3 (battery) and fuxi,pmic=3 (torch) alongside WLAN, opted in '
                             'with fuxi,adsp-wlan=1; needs a kernel with that opt-in and no fuxiadsp= on the command line')
    parser.add_argument('--audio-spf', action='store_true',
                        help='Query DSP SPF state once through adsp_apps; requires --with-adsp')
    parser.add_argument('--audio-spf-format', choices=('apm', 'bare'), default='apm',
                        help='Select the 40-byte APM or isolated 24-byte bare state query')
    parser.add_argument('--haptic', type=int, choices=(2, 3),
                        help='HAP525 vibration: ADT fuxi,haptic=2 runtime (sysctl kern.fuxivibrate) or 3 with a boot self-test')
    parser.add_argument('--bt', type=int, choices=(1, 3),
                        help='WCN7850 Bluetooth: ADT fuxi,bt=1 read-only survey, or 3 board power-up and QCA version '
                             'probe once WLAN_EN has been steady for 15 s (needs --native-ath12k); everything is restored')
    parser.add_argument('--inject-media', action='store_true',
                        help='ADT fuxi,inject=6: mediaserverd also gets libfuxi-sb.dylib (haptic server hooks)')
    parser.add_argument('--wifi-audit', action='store_true',
                        help='Opt-in wifid injection for bounded CoreWiFi scan conversion/filter diagnostics; '
                             'requires --wifi-ios and a kernel that supports injection bit 8')
    parser.add_argument('--product-haptics', action='store_true',
                        help='Add /product/haptics closed-loop=1 so MediaExperience creates its vibrator; '
                             'needs --haptic and --inject-media')
    parser.add_argument('--haptic-ui-ms', type=int, default=0,
                        help='ADT fuxi,haptic-ui: SpringBoard pulses this many ms (8..40) per UI feedback while no '
                             'CoreHaptics engine has been created; needs --haptic')
    parser.add_argument('--haptic-envelope', action='store_true',
                        help='ADT fuxi,haptic-env=1: mediaserverd shortens Atoms to their Envelope area; '
                             'needs --haptic and --inject-media')
    parser.add_argument('--wifi-sb-audit', action='store_true',
                        help='ADT fuxi,wifi-sb=1: SpringBoard logs the status bar Wi-Fi inputs (read only)')
    parser.add_argument('--wifi-rssi-bounds', action='store_true',
                        help='ADT fuxi,wifi-rssi=1: answer Apple80211 RSSI_BOUNDS (106) with s8 bounds and a -128 '
                             'threshold so wifid auto-join stops rejecting every network; requires --wifi-ios')
    parser.add_argument('--wifi-ux', type=int, metavar='BITS',
                        help='ADT fuxi,wifi-ux 1..31: bit 0 reports the asked radio power at once and refuses scans/joins '
                             'while switching off; bit 1 picks the access point by estimated rate (wpa_supplicant order); '
                             'bit 2 keeps the link when a join picks the access point already joined; bit 3 keeps the '
                             'country code wifid sets; bit 4 leaves the radio alone when asked for the power it already '
                             'has; requires --wifi-ios')
    parser.add_argument('--daily-tuning', action='store_true',
                        help='Add the chain-v7 smoothness tokens of native-dly-ram9g-rtctorch-sb127-loader '
                             '(fuxivsynctoff=6000 sweetlog=0 fuxiswapwait=0 fuxiperf=2 fuxicores=0x7c fuxitudebug=nocb '
                             'fuxitcache=1); exclusive with --hybrid-turnip')
    parser.add_argument('--wifi-args-adt', action='store_true',
                        help='Patch 0121: carry the Wi-Fi switches (fuxiwlanath/mlo/dwell/cache/batch, fuxiwifiios/trace) '
                             'in ADT /chosen fuxi,args instead of the command line; fuxiwlan=1 stays; requires --wifi-ios')
    parser.add_argument('--haptic-amp', type=int, metavar='LEVEL',
                        help='ADT fuxi,haptic-amp: DIRECT_PLAY amplitude ceiling 1..255 (0xf126, scales VMAX); '
                             'Atoms envelopes are stepped under it; needs --haptic')
    parser.add_argument('--display-gamut', choices=('sRGB',),
                        help='/product artwork-display-gamut sRGB: MobileGestalt answers no deep colour, so WebKit, '
                             'MaterialKit and CA stay on 8-bit BGRA instead of b3a8/w30r surfaces (mkadt-fuxi.py)')
    parser.add_argument('--mlo', type=int, choices=(0, 1, 2), default=0)
    parser.add_argument('--host-cap-secondary', action='store_true',
                        help='Add SECONDARY with fuxiwlancap=1; refuse inherited cap tokens and MLO overrides')
    parser.add_argument('--omit-nm-modem', action='store_true',
                        help='Use fuxiwlancap=2 to omit only nm_modem from the SECONDARY baseline')
    parser.add_argument('--sleep-clock', choices=('check', 'on'),
                        help='P17 PMK8550 gpio3 32 kHz sleep clock: check reads only (fuxiwlanmlo=64), '
                             'on also enables it when off (fuxiwlanmlo=192); ADSP stays off through the ADT')
    parser.add_argument('--big-mem', action='store_true',
                        help='P17 BIGMEM with --sleep-clock on (fuxiwlanmlo=704): grant the large REQUEST_MEM chunks '
                             'with aligned IOVAs instead of negotiating small chunks')
    parser.add_argument('--errdec', action='store_true',
                        help='P17 ERRDEC with --big-mem (fuxiwlanmlo=960): diagnostics only, summarize granted '
                             'target memory after a WLFW timeout')
    parser.add_argument('--cnss-pdc', action='store_true',
                        help='Add fuxiwlancnss=pdc (AOP WLAN PDC table before rails) to --sleep-clock on --big-mem; '
                             'cannot be combined with --host-cap-secondary')
    parser.add_argument('--ram-sku', choices=('auto', '8g', '12g'), default='auto')
    parser.add_argument('--assets-manifest', type=Path)
    parser.add_argument('--live-fdt', type=Path, default=WORKSPACE / 'work/hw-survey/fuxi-live-20261116.dtb')
    parser.add_argument('--map-record', type=Path,
                        default=WORKSPACE / 'work/xiaomi13-ios-gpu-20261108/managed-native-map-current.json')
    parser.add_argument('--compiler-dir', type=Path, default=COMPILER)
    parser.add_argument('--like', metavar='LOADER',
                        help='Take source, shim reference, asset manifest, native and sleep-clock choices from an '
                             'earlier loader profile; options given explicitly still win')
    args = parser.parse_args()
    try:
        if args.like:
            # 省掉每次手抄上一顆 loader 的平台選項；測試相關開關（wifi/tap）仍須明寫。
            require(re.fullmatch(r'native-[a-z0-9-]+-loader', args.like), 'invalid --like loader name')
            with open(STORAGE / args.like / 'wlan-ath12k-profile.json', encoding='utf-8') as handle:
                earlier = json.load(handle)
            if args.source == SOURCE:
                args.source = earlier['source']
            if args.shim_reference is None:
                args.shim_reference = earlier.get('shim_reference')
            if args.assets_manifest is None and (earlier.get('wlan_assets') or {}).get('manifest'):
                args.assets_manifest = Path(earlier['wlan_assets']['manifest'])
            args.native_ath12k = args.native_ath12k or bool(earlier.get('native_ath12k'))
            if args.sleep_clock is None:
                args.sleep_clock = earlier.get('sleep_clock')
        require(re.fullmatch(r'native-[a-z0-9-]+-loader', args.source) and
                re.fullmatch(r'native-[a-z0-9-]+-loader', args.name) and
                re.fullmatch(r'kernel-[a-z0-9-]+-artifact', args.artifact), 'invalid loader/artifact name')
        require(args.shim_reference is None or re.fullmatch(r'native-[a-z0-9-]+-loader', args.shim_reference),
                'invalid shim reference loader name')
        if args.action == 'self-test':
            self_test()
            return
        report, tree, source_inputs = inspect(args)
        if args.action == 'build':
            build(args, report, tree, source_inputs)
        print(json.dumps(report, indent=2))
    except (ValueError, OSError, KeyError, UnicodeError, struct.error, AssertionError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error


if __name__ == '__main__':
    main()
