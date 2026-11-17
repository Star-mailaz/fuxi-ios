import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = r'''
#include <assert.h>
#include <stdio.h>
#include "fuxi_ramtest_pattern.h"
int main(void) {
    uint64_t memory[1031], previous[1031];
    assert(!fuxi_ramtest_allocation_bytes(0));
    assert(fuxi_ramtest_allocation_bytes(1)==128ull*1024*1024);
    assert(fuxi_ramtest_allocation_bytes(2)==512ull*1024*1024);
    assert(!fuxi_ramtest_allocation_bytes(3));
    assert(!fuxi_ramtest_allocation_bytes(UINT32_MAX));
    assert(!fuxi_ramtest_page_allowed(0x8bfffc000ull,16384));
    assert(fuxi_ramtest_page_allowed(0x8c0000000ull,16384));
    assert(fuxi_ramtest_page_allowed(0xa00000000ull,16384));
    assert(fuxi_ramtest_page_allowed(0xafdffc000ull,16384));
    assert(!fuxi_ramtest_page_allowed(0xafe000000ull,16384));
    assert(!fuxi_ramtest_page_allowed(0xaffffc000ull,16384));
    assert(!fuxi_ramtest_page_allowed(UINT64_MAX,16384));
    assert(!fuxi_ramtest_page_allowed(0x8c0000001ull,16384));
    assert(!fuxi_ramtest_page_allowed(0x8c0000000ull,0));
    assert(!fuxi_ramtest_page_allowed(0x8c0000000ull,16383));
    assert(!fuxi_ramtest_verify(memory,0,0));
    for(unsigned pass=0;pass<4;pass++) {
        fuxi_ramtest_fill(memory,1031,pass);
        assert(fuxi_ramtest_verify(memory,1031,pass)==1031);
        for(size_t index=0;index<1031;index++) {
            if(pass) assert(previous[index]!=memory[index]);
            previous[index]=memory[index];
            for(unsigned bit=0;bit<64;bit++) {
                memory[index]^=1ull<<bit;
                assert(fuxi_ramtest_verify(memory,1031,pass)==index);
                memory[index]^=1ull<<bit;
            }
        }
        memory[1030]=memory[0];
        assert(fuxi_ramtest_verify(memory,1031,pass)==1030);
    }
    puts("PASS: real RAM patterns detect every injected bit flip and alias; range gate excludes reserved GPU and overflow");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='fuxi-ramtest-') as temporary:
    directory = Path(temporary)
    cfile, binary = directory / 'ramtest.c', directory / 'ramtest'
    cfile.write_text(source)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I' + str(root / 'xnu/fuxi-adsp'), str(cfile), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
