import os
from pathlib import Path
import subprocess
import tempfile


root = Path(__file__).resolve().parents[1]
production = (root / 'xnu/fuxi-h1/fuxi_keys.c').read_text()
start = production.index('static int\nfk_taps_command(')
finish = production.index('\nstatic void\nfk_taps(', start)
helper = production[start:finish]
source = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef void *DTEntry;
enum { kSuccess = 0 };
static const char *boot_command;
static const void *adt_property;
static unsigned adt_length;
static int lookup_error, property_error;
static int PE_parse_boot_argn(const char *name, char *output, int capacity) {
    assert(!strcmp(name, "fuxitapcmd"));
    if (!boot_command) return 0;
    assert(strlen(boot_command) < (size_t)capacity);
    strcpy(output, boot_command);
    return 1;
}
static int SecureDTLookupEntry(void *parent, const char *path, DTEntry *entry) {
    assert(!parent && !strcmp(path, "/chosen"));
    *entry = (void *)1;
    return lookup_error;
}
static int SecureDTGetProperty(DTEntry entry, const char *name, void **value, unsigned *length) {
    assert(entry == (void *)1 && !strcmp(name, "fuxi,tapcmd"));
    *value = (void *)adt_property;
    *length = adt_length;
    return property_error;
}
''' + helper + r'''
int main(void) {
    char output[400], expected[400], maximum[401];
    memset(expected, 0x5a, sizeof(expected));
    memcpy(output, expected, sizeof(output));
    boot_command = "t414,1535";
    assert(fk_taps_command(output, sizeof(output)));
    assert(!strcmp(output, boot_command));
    boot_command = NULL;
    assert(!fk_taps_command(output, sizeof(output)));
    adt_property = "s999,0,999,999;t414,1535;w3000;t414,1535";
    adt_length = (unsigned)strlen(adt_property) + 1;
    assert(fk_taps_command(output, sizeof(output)));
    assert(!strcmp(output, adt_property));
    boot_command = "@3";
    assert(fk_taps_command(output, sizeof(output)));
    assert(!strcmp(output, "@3"));
    boot_command = NULL;
    memcpy(output, expected, sizeof(output));
    lookup_error = 1;
    assert(!fk_taps_command(output, sizeof(output)));
    lookup_error = 0;
    property_error = 1;
    assert(!fk_taps_command(output, sizeof(output)));
    property_error = 0;
    adt_property = "";
    adt_length = 0;
    assert(!fk_taps_command(output, sizeof(output)));
    adt_length = 1;
    assert(!fk_taps_command(output, sizeof(output)));
    adt_property = "t1,2";
    adt_length = 4;
    assert(!fk_taps_command(output, sizeof(output)));
    adt_property = "t1,2\0t3,4";
    adt_length = 10;
    assert(!fk_taps_command(output, sizeof(output)));
    assert(!memcmp(output, expected, sizeof(output)));
    memset(maximum, 'x', sizeof(maximum));
    maximum[399] = '\0';
    adt_property = maximum;
    adt_length = 400;
    assert(fk_taps_command(output, sizeof(output)));
    assert(!memcmp(output, maximum, sizeof(output)));
    adt_length = 401;
    memcpy(output, expected, sizeof(output));
    assert(!fk_taps_command(output, sizeof(output)));
    assert(!memcmp(output, expected, sizeof(output)));
    adt_property = NULL;
    adt_length = 4;
    assert(!fk_taps_command(output, sizeof(output)));
    puts("PASS: production ADT tap command bounds, termination, missing properties and boot-argument priority");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='fuxi-tap-command-') as temporary:
    directory = Path(temporary)
    cfile, binary = directory / 'tap-command.c', directory / 'tap-command'
    cfile.write_text(source)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-D_POSIX_C_SOURCE=200809L',
                    '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', str(cfile), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
