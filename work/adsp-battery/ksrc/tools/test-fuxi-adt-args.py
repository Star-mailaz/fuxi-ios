#!/usr/bin/env python3
"""補丁 0121 主機測試：Wi-Fi 開關可從 ADT /chosen fuxi,args 讀，命令列優先。不碰手機。

用法（WSL／Linux，需要 clang 與未套補丁的 XNU 8796 原始碼）：
  python3 tools/test-fuxi-adt-args.py /root/fuxi-build/src/xnu-8796.141.3
把補丁套到 pexpert/gen/bootargs.c 的副本，用替身 device tree 編成主機程式（ASan／UBSan）。
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'xnu/patches/0121-fuxi-adt-wifi-args.patch'

PEXPERT_H = r'''
#pragma once
#include <stdint.h>
#include <string.h>
typedef int boolean_t;
#define TRUE 1
#define FALSE 0
#define __DECONST(t, p) ((t)(uintptr_t)(const void *)(p))
char *PE_boot_args(void);
'''
DEVICE_TREE_H = r'''
#pragma once
typedef struct fake_entry *DTEntry;
enum { kSuccess = 0, kError = -1 };
int SecureDTLookupEntry(const DTEntry searchPoint, const char *pathName, DTEntry *foundEntry);
int SecureDTGetProperty(const DTEntry entry, const char *propertyName, void const **propertyValue, unsigned int *propertySize);
'''
DRIVER = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
static char cmdline[608];
static int dt_up = 1, has_prop = 1;
static unsigned char prop_bytes[512];
static unsigned int prop_size;
static unsigned lookups;
char *PE_boot_args(void) { return cmdline; }
boolean_t IODTGetDefault(const char *name, void *buffer, unsigned int size) { (void)name; (void)buffer; (void)size; return FALSE; }
int SecureDTLookupEntry(const DTEntry s, const char *path, DTEntry *found)
{
	(void)s;
	lookups++;
	if (!dt_up || strcmp(path, "/chosen")) { return kError; }
	*found = (DTEntry)prop_bytes;
	return kSuccess;
}
int SecureDTGetProperty(const DTEntry e, const char *name, void const **value, unsigned int *size)
{
	(void)e;
	if (!has_prop || strcmp(name, "fuxi,args")) { return kError; }
	*value = malloc(prop_size ? prop_size : 1);          /* ASan 抓越界讀 */
	memcpy((void *)*value, prop_bytes, prop_size);
	*size = prop_size;
	return kSuccess;
}
#undef __x86_64__                                       /* 走 embedded 分支 */
#include "bootargs.c"
static void set_prop(const char *text, unsigned extra_nul, int drop_nul)
{
	size_t n = strlen(text) + 1;
	memcpy(prop_bytes, text, n);
	prop_size = (unsigned)n + extra_nul;
	if (extra_nul) { memset(prop_bytes + n, 0, extra_nul); }
	if (drop_nul) { prop_size = (unsigned)n - 1; }
}
static int argn(const char *name, int fallback)
{
	int v = fallback;
	return PE_parse_boot_argn(name, &v, sizeof(v)) ? v : -1000 - fallback;
}
int main(void)
{
	char text[16];
	strcpy(cmdline, "serial=3 fuxiwlan=1 fuxiwlanmlo=64 -v");
	set_prop("fuxiwlanath=1 fuxiwlanmlo=192 fuxiwifiios=2 fuxiwlandwell=1 fuxiwlanbatch=1 sweetlog=0", 0, 0);
	assert(argn("fuxiwlan", 0) == 1);
	assert(argn("fuxiwlanmlo", 0) == 64);                 /* 命令列優先 */
	assert(argn("fuxiwifiios", 0) == 2);
	assert(argn("fuxiwlandwell", 0) == 1);
	assert(argn("fuxiwlanbatch", 0) == 1);
	assert(PE_parse_boot_arg_str("fuxiwlanath", text, sizeof(text)) && !strcmp(text, "1"));
	assert(argn("sweetlog", 7) == -1007);                  /* 非 Wi-Fi 名稱不讀 ADT */
	assert(argn("fuxiwlanx", 5) == -1005);
	unsigned before = lookups;
	assert(argn("serialx", 3) == -1003 && lookups == before); /* 不是 Wi-Fi 名稱連查都不查 */
	assert(argn("fuxiwlan", 0) == 1 && lookups == before);    /* 命令列有就不查 ADT */
	strcpy(cmdline, "serial=3");
	assert(argn("fuxiwlanmlo", 0) == 192);
	dt_up = 0;                                              /* device tree 未就緒 */
	assert(argn("fuxiwlanmlo", 9) == -1009);
	dt_up = 1;
	has_prop = 0;
	assert(argn("fuxiwlanmlo", 9) == -1009);
	has_prop = 1;
	set_prop("fuxiwlanmlo=192", 1, 0);                      /* 中間多一個 NUL：整份不信 */
	assert(argn("fuxiwlanmlo", 9) == -1009);
	set_prop("fuxiwlanmlo=192", 0, 1);                      /* 沒有結尾 NUL */
	assert(argn("fuxiwlanmlo", 9) == -1009);
	set_prop("", 0, 0);                                     /* 只有 NUL（1 byte） */
	assert(argn("fuxiwlanmlo", 9) == -1009);
	char big[300];
	memset(big, ' ', sizeof(big));
	memcpy(big, "fuxiwlanmlo=192", 15);
	big[sizeof(big) - 1] = 0;
	set_prop(big, 0, 0);                                    /* 超過 256 bytes */
	assert(argn("fuxiwlanmlo", 9) == -1009);
	big[255] = 0;
	set_prop(big, 0, 0);                                    /* 剛好 256 bytes */
	assert(argn("fuxiwlanmlo", 9) == 192);
	set_prop("fuxiwlanath=native_longer_than_buffer", 0, 0);
	assert(PE_parse_boot_arg_str("fuxiwlanath", text, sizeof(text)) && strlen(text) == sizeof(text) - 1);
	set_prop("fuxiwifiios", 0, 0);                          /* 沒有等號＝1 */
	assert(argn("fuxiwifiios", 0) == 1);
	strcpy(cmdline, "");                                    /* 命令列空白仍可讀 ADT */
	set_prop("fuxiwifiios=2", 0, 0);
	assert(argn("fuxiwifiios", 0) == 2);
	puts("PASS fuxi 0121: ADT fuxi,args fills Wi-Fi switches, command line first, malformed ignored");
	return 0;
}
'''


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = Path(sys.argv[1]) / 'pexpert/gen/bootargs.c'
    cc = os.environ.get('CC', 'clang')
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / 'pexpert/gen').mkdir(parents=True)
        shutil.copyfile(source, work / 'pexpert/gen/bootargs.c')
        subprocess.run(['git', 'init', '-q', '.'], cwd=work, check=True)
        subprocess.run(['git', 'apply', str(PATCH)], cwd=work, check=True)
        include = work / 'include/pexpert'
        include.mkdir(parents=True)
        (include / 'pexpert.h').write_text(PEXPERT_H)
        (include / 'device_tree.h').write_text(DEVICE_TREE_H)
        (work / 'driver.c').write_text(DRIVER)
        exe = work / 'driver'
        subprocess.run([cc, '-std=gnu11', '-g', '-O1', '-Wall', '-Werror', '-Wno-unused-function',
                        '-Wno-builtin-macro-redefined',
                        '-Wno-incompatible-pointer-types',  # 原版範圍解析：Linux int64_t 是 long
                        '-DFUXI=1', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-I', str(work / 'include'),
                        '-I', str(work / 'pexpert/gen'), str(work / 'driver.c'), '-o', str(exe)], check=True)
        # 替身每次查屬性都 malloc 一份（讓 ASan 抓越界），不回收
        subprocess.run([str(exe)], check=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))


if __name__ == '__main__':
    main()
