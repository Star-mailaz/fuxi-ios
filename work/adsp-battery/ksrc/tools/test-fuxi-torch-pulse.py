import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "fuxi_torch_pulse.h"
struct model {
    uint8_t registers[256], original[256];
    uint8_t postdisable_status;
    unsigned reads, writes, fail_read, fail_write, drop_write, quarantine, dead, fault;
    unsigned now, start, pulses, peak_current, expired, level;
    unsigned off_delay_reads, pending_off_reads, timer_fault, timer_source;
    uint64_t drop_mask;
};
static unsigned mainline_timer_us(uint8_t timer) {
    return (timer&0x80) ? (timer&0x7f)*10000u : 0;
}
static unsigned oem_timer_us(uint8_t timer) {
    return (timer&0x80) ? ((timer&0x7f)+1u)*10000u : 0;
}
static unsigned modeled_timer_us(const struct model *state) {
    return state->timer_source ? oem_timer_us(state->registers[0x3e]) :
        mainline_timer_us(state->registers[0x3e]);
}
static int active(struct model *state) {
    return (state->registers[0x46]&0x80) && (state->registers[0x4e]&1) && !state->expired;
}
static int read_register(void *context, unsigned offset, uint8_t *value) {
    struct model *state=context;
    assert(offset<256);
    if(++state->reads==state->fail_read) return -1;
    if(state->fault && state->pulses && offset==6) {*value=1; return 0;}
    if(state->timer_fault && state->expired && offset==9) {*value=1; return 0;}
    if(state->postdisable_status && state->pulses && offset==9 &&
       !state->registers[0x4e] && !(state->registers[0x46]&0x80)) {
        *value=state->postdisable_status; return 0;
    }
    *value=state->registers[offset];
    if(offset==0x4e && state->pending_off_reads && !--state->pending_off_reads)
        state->registers[offset]=0;
    return 0;
}
static int write_register(void *context, unsigned offset, uint8_t value) {
    struct model *state=context;
    assert(offset==0x3e || offset==0x42 || offset==0x49 || offset==0x4a || offset==0x46 || offset==0x4e);
    state->writes++;
    if(state->dead) return -1;
    if(state->writes==state->fail_write && !state->quarantine) return -1;
    if(state->writes!=state->drop_write && !(state->drop_mask&(1ull<<state->writes))) {
        if(active(state) && offset!=0x46 && offset!=0x4e) assert(0);
        if(offset==0x4e && value) {
            assert(value==1 && state->registers[0x3e]==0x89 && (state->registers[0x49]&1));
            assert(mainline_timer_us(state->registers[0x3e])==90000u);
            assert(oem_timer_us(state->registers[0x3e])==100000u);
            assert(mainline_timer_us(state->registers[0x3e])<=100000u);
            assert(oem_timer_us(state->registers[0x3e])<=100000u);
            assert((state->registers[0x4a]&7)==1 && state->registers[0x42]==state->level*4-1);
            assert(state->registers[0x46]&0x80);
            state->start=state->now; state->pulses++; state->expired=0; state->peak_current=state->level*20;
        }
        if(offset==0x4e && !value && state->registers[offset] && state->off_delay_reads)
            state->pending_off_reads=state->off_delay_reads;
        else state->registers[offset]=value;
    }
    if(state->writes==state->fail_write) {state->dead=1; return -1;}
    return 0;
}
static void wait_us(void *context, unsigned microseconds) {
    struct model *state=context;
    state->now+=microseconds;
    if(state->pulses && (state->registers[0x3e]&0x80) &&
       state->now-state->start>=modeled_timer_us(state)) state->expired=1;
}
static void fixture(struct model *state, unsigned timer_source) {
    memset(state,0,sizeof(*state));
    state->timer_source=timer_source;
    state->level=2;
    state->registers[4]=0x18; state->registers[5]=7;
    state->registers[0x3e]=11; state->registers[0x42]=23;
    state->registers[0x49]=0x0a; state->registers[0x4a]=1; state->registers[0x46]=0x20;
    memcpy(state->original,state->registers,256);
}
static int run(struct model *state) {
    FuxiTorchIo io={state,read_register,write_register,wait_us};
    int result=state->level==2 ? fuxi_torch_pulse(&io) : fuxi_torch_pulse_level(&io,state->level);
    assert(!active(state) && state->pulses<=1 && state->peak_current<=80);
    return result;
}
static void test_primary(unsigned timer_source) {
    struct model state;
    fixture(&state,timer_source); assert(!run(&state));
    assert(state.pulses==1 && state.now==81000 && state.writes==12);
    assert(!memcmp(state.registers,state.original,256));
    unsigned reads=state.reads;
    fixture(&state,timer_source); state.registers[4]=0; assert(run(&state)<0 && !state.writes);
    fixture(&state,timer_source); state.registers[5]=4; assert(run(&state)<0 && !state.writes);
    fixture(&state,timer_source); state.registers[0x46]|=0x80;
    FuxiTorchIo busy={&state,read_register,write_register,wait_us};
    assert(fuxi_torch_pulse(&busy)==-2 && !state.writes);
    fixture(&state,timer_source); state.registers[0x4e]=2; assert(run(&state)==-2 && !state.writes);
    fixture(&state,timer_source); state.registers[6]=1; assert(run(&state)==-2 && !state.writes);
    fixture(&state,timer_source); state.registers[9]=0x10; assert(run(&state)==-2 && !state.writes);
    for(unsigned index=1;index<=reads;index++) {
        fixture(&state,timer_source); state.fail_read=index; assert(run(&state)<0);
    }
    for(unsigned index=1;index<=12;index++) {
        fixture(&state,timer_source); state.fail_write=index; assert(run(&state)<0);
    }
    for(unsigned index=1;index<=12;index++) {
        fixture(&state,timer_source); state.drop_write=index; run(&state);
        fixture(&state,timer_source); state.fail_write=index; state.quarantine=1; assert(run(&state)<0);
    }
    fixture(&state,timer_source); state.drop_mask=(1ull<<7)|(1ull<<8);
    assert(run(&state)==-6 && state.expired && state.now==193000);
    assert(state.registers[0x3e]==0x89 && state.writes==8);
    for(unsigned delayed_reads=1;delayed_reads<=2;delayed_reads++) {
        fixture(&state,timer_source); state.off_delay_reads=delayed_reads;
        assert(!run(&state) && state.now==81000+delayed_reads*1000);
        assert(!memcmp(state.registers,state.original,256));
        unsigned delayed_read_count=state.reads;
        for(unsigned failure=1;failure<=delayed_read_count;failure++) {
            fixture(&state,timer_source); state.off_delay_reads=delayed_reads; state.fail_read=failure;
            assert(run(&state)<0);
        }
    }
    fixture(&state,timer_source); state.off_delay_reads=3;
    assert(run(&state)==-6 && state.registers[0x3e]==0x89 && state.writes==8);
    fixture(&state,timer_source); state.drop_mask=(1ull<<7)|(1ull<<8); state.timer_fault=1;
    assert(run(&state)==-6 && state.expired && state.registers[0x3e]==0x89);
    fixture(&state,timer_source); state.fault=1; assert(run(&state)==-5);
    assert(!memcmp(state.registers,state.original,256));
    fixture(&state,timer_source); state.postdisable_status=0x10;
    assert(run(&state)==-5 && state.pulses==1 && state.writes==12);
    assert(!memcmp(state.registers,state.original,256));
    for(unsigned level=0;level<=5;level++) {
        fixture(&state,timer_source); state.level=level;
        if(!level || level>4) assert(run(&state)<0 && !state.writes);
        else {
            assert(!run(&state) && state.peak_current==level*20);
            assert(!memcmp(state.registers,state.original,256));
        }
    }
    fixture(&state,timer_source);
    state.registers[0x3e]=0x89; state.registers[0x46]|=0x80;
    state.registers[0x4e]=1; state.pulses=1;
    unsigned deadline=modeled_timer_us(&state);
    assert(deadline>=80000u && deadline<=100000u);
    wait_us(&state,deadline-1u); assert(active(&state) && !state.expired);
    wait_us(&state,1); assert(!active(&state) && state.expired && state.now==deadline);
}
int main(void) {
    for(unsigned code=0;code<128;code++) {
        uint8_t enabled=(uint8_t)(code|0x80);
        assert(!mainline_timer_us((uint8_t)code) && !oem_timer_us((uint8_t)code));
        assert(mainline_timer_us(enabled)==code*10000u);
        assert(oem_timer_us(enabled)==(code+1u)*10000u);
    }
    assert(mainline_timer_us(0x89)==90000u && oem_timer_us(0x89)==100000u);
    assert(mainline_timer_us(0x8a)==100000u && oem_timer_us(0x8a)>100000u);
    for(unsigned timer_source=0;timer_source<2;timer_source++) test_primary(timer_source);
    puts("PASS: production torch pulse, 0x89 dual-primary decode models (OEM 100ms/mainline 90ms), four 20..80mA levels, 80ms wait, timer-before-enable, bounded two-sample disable, delayed readback, every read/write failure, retained-timer cleanup and postdisable 0x09 bit4 refusal; no device cutoff proof");
    return 0;
}
'''
specification = importlib.util.spec_from_file_location('audio_compiler', root / 'tools/test-fuxi-audio-prep.py')
module = importlib.util.module_from_spec(specification)
specification.loader.exec_module(module)
compiler, environment = module.compiler_environment()
microsoft = Path(compiler[0]).name.lower() in ('cl', 'cl.exe')
with tempfile.TemporaryDirectory(prefix='fuxi-torch-pulse-') as temporary:
    directory = Path(temporary)
    cfile = directory / 'pulse.c'
    binary = directory / ('pulse.exe' if os.name == 'nt' else 'pulse')
    cfile.write_text(source, encoding='utf-8', newline='\n')
    if microsoft:
        command = compiler + ['/nologo', '/std:c11', '/W4', '/WX', '/Zi', '/Od', '/fsanitize=address',
                   '/I' + str(root / 'xnu/fuxi-adsp'), str(cfile), '/Fe' + str(binary)]
    else:
        command = compiler + ['-std=c11', '-g', '-Wall', '-Wextra', '-Werror',
                   '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                   '-I' + str(root / 'xnu/fuxi-adsp'), str(cfile), '-o', str(binary)]
    subprocess.run(command, cwd=directory, env=environment, check=True)
    subprocess.run([str(binary)], cwd=directory, env=environment, check=True, timeout=60)
