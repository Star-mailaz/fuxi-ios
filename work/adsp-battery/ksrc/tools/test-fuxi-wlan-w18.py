#!/usr/bin/env python3
"""Compile the production WLAN timeline with the existing independent W16 peer.

--standalone stages source fixtures in a temporary directory for parallel work.
The default also validates the repository's canonical source mirrors.

HOST_CAP SECONDARY=2 matches the same-device exported cnss2 module, SHA256
32f9cbf282f00ce1447942a78668d53b3023b3e8119eca61a8cf19cff03e5390.
Its inlined caller stores valid=1 at request+0x130 and enum=2 at +0x134,
matching the primary AArch64 schema. Loaded-buffer identity is not established.
"""
from pathlib import Path
import argparse
import importlib.util
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('w16', ROOT / 'tools/test-fuxi-wlan-w16.py')
w16 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w16)

CAP_PEER = r'''
static unsigned cap_strip(const uint8_t *body,unsigned length,uint8_t *baseline,bool enabled,bool omit_nm_modem) {
    unsigned cursor=0,output=0,found=0,nm_found=0;
    assert(length<=512);
    while(cursor<length) {
        assert(length-cursor>=3);
        unsigned size=body[cursor+1]|((unsigned)body[cursor+2]<<8);
        assert(size<=length-cursor-3);
        assert(body[cursor]!=0x11 && body[cursor]!=0x1f);
        if(body[cursor]==0x13) {
            assert(!omit_nm_modem && ++nm_found==1 && size==1 && body[cursor+3]==0x0e);
        }
        if(body[cursor]==0x14 && omit_nm_modem) {
            const uint8_t omitted[]={0x13,1,0,0x0e};
            assert(++nm_found==1);
            memcpy(baseline+output,omitted,sizeof(omitted));output+=sizeof(omitted);
        }
        if(body[cursor]==0x20) {
            const uint8_t expected[]={2,0,0,0};
            assert(enabled && ++found==1 && size==sizeof(expected));
            assert(!memcmp(body+cursor+3,expected,sizeof(expected)));
        } else {
            memcpy(baseline+output,body+cursor,size+3);output+=size+3;
        }
        cursor+=size+3;
    }
    assert(found==(unsigned)enabled && nm_found==1);
    return output;
}
'''

peer = CAP_PEER + w16.TESTS.split('int main(void) {', 1)[0]
peer = peer.replace('if(msg==0x34) {', r'''
    if(msg==0x34) {
        uint8_t baseline[519];
        assert(len>=7);
        memcpy(baseline,q,7);
        bool enabled=cap_arg && (!strcmp(cap_arg,"1") || !strcmp(cap_arg,"2"));
        bool omit_nm_modem=cap_arg && !strcmp(cap_arg,"2");
        unsigned size=cap_strip(q+7,len-7,baseline+7,enabled,omit_nm_modem);
        baseline[5]=(uint8_t)size;baseline[6]=(uint8_t)(size>>8);
        q=baseline;len=size+7;
''')
peer = peer.replace('static unsigned start_case,', 'static unsigned timeline_case;\nstatic unsigned start_case,')
peer = peer.replace('unsigned step=seen15++;', r'''
        unsigned step=seen15++;
        if((timeline_case==1 && step==1) || (timeline_case==2 && step==2)) {
            crash_regs(2,0x200);
        }
        if(timeline_case==3 && step==2)crash_regs(3,0xff05);
''')

TESTS = peer + r'''
static unsigned occurrences(const char *needle) {
    unsigned count=0;
    const char *cursor=logbuf;
    while((cursor=strstr(cursor,needle))) { count++;cursor+=strlen(needle); }
    return count;
}
static void sample_line(const char *phase,const char *expected) {
    const char *line=strstr(logbuf,phase);
    assert(line);
    const char *match=strstr(line,expected);
    const char *end=strchr(line,'\n');
    if(!match || !end || match>=end)fprintf(stderr,"phase %s expected %s\n%s",phase,expected,line);
    assert(match && end && match<end);
}
static void boot18(unsigned variant,unsigned failure,unsigned injection) {
    w18_arg=1;timeline_case=injection;boot16(variant,failure,true);
    assert(wl18_enabled);
}
static void readonly18(void) {
    uint8_t contexts[16384];
    memcpy(contexts,(void *)wl_contexts.va,sizeof(contexts));
    uint8_t *ipcr=malloc(wl_ipcr.size);assert(ipcr);
    memcpy(ipcr,(void *)wl_ipcr.va,wl_ipcr.size);
    unsigned before=ne,tx=wl_tx_read,rx=wl_rx_read,rxwrite=wl_rx_write;
    track_reads=true;nreads=0;
    wl18_snapshot("read-only test");
    track_reads=false;
    const unsigned offsets[]={0x128,0x48,0x130,0x134,0x138,0x13c};
    assert(ne==before && nreads==6);
    for(unsigned index=0;index<6;index++)assert(reads[index]==WL_BAR0+offsets[index]);
    assert(wl_tx_read==tx && wl_rx_read==rx && wl_rx_write==rxwrite);
    assert(!memcmp(contexts,(void *)wl_contexts.va,sizeof(contexts)));
    assert(!memcmp(ipcr,(void *)wl_ipcr.va,wl_ipcr.size));free(ipcr);
}
static void host_cap_selectors(void) {
    const char *values[]={NULL,"0","1","2","-1","3","01","+1","0x1","1junk","","2147483648","1000000000000000000000000000000"};
    for(int qrtr=0;qrtr<=6;qrtr++)for(int variant=0;variant<=1;variant++) {
        for(unsigned index=0;index<sizeof(values)/sizeof(values[0]);index++) {
            cap_arg=values[index];qrtr_arg=qrtr;w18_arg=variant;w16_arg=0;
            unsigned before=ne;
            wl_probe_configure();
            bool selected=qrtr==5 && variant==1;
            bool invalid=selected && index>=4;
            assert(wl_variant_invalid==invalid && ne==before);
            assert(wl18_cap_invalid==invalid);
            assert(wl18_host_cap==(selected && (index==2 || index==3)));
            assert(wl18_omit_nm_modem==(selected && index==3));
            assert(wl18_cap_refused()==invalid && ne==before);
            if(invalid)assert(wl5_step(17)==0x6c && ne==before);
        }
    }
    cap_arg=NULL;qrtr_arg=5;w18_arg=1;wl_probe_configure();
    assert(!wl18_host_cap && !wl18_omit_nm_modem && !wl_variant_invalid);
}
static void host_cap_wire(void) {
    const unsigned policies[]={0,WL17_HOSTMEM,WL17_MLOALL};
    for(unsigned variant=0;variant<=2;variant++) {
        for(unsigned policy=0;policy<sizeof(policies)/sizeof(policies[0]);policy++) {
            if(variant==2 && policies[policy]==WL17_MLOALL)continue;
            struct wl12_encoder baseline={0},selected={0};uint8_t stripped[512];
            wl12_mlo_variant=variant;wl17_bits=policies[policy];
            wl12_mlo_enabled=true;wl12_num_phy=2;wl18_host_cap=false;wl18_omit_nm_modem=false;
            assert(!wl12_host_cap(&baseline));
            unsigned size=cap_strip(baseline.data,baseline.len,stripped,false,false);
            assert(size==baseline.len && !memcmp(stripped,baseline.data,size));
            for(unsigned selector=1;selector<=2;selector++) {
                selected=(struct wl12_encoder){0};
                wl18_host_cap=true;wl18_omit_nm_modem=selector==2;
                assert(!wl12_host_cap(&selected));
                size=cap_strip(selected.data,selected.len,stripped,true,selector==2);
                assert(selected.len==baseline.len+7-(selector==2 ? 4u : 0u) && size==baseline.len);
                assert(!memcmp(stripped,baseline.data,size));
            }
        }
    }
    wl12_mlo_variant=wl17_bits=0;wl18_host_cap=wl18_omit_nm_modem=false;
}
int main(void) {
    host_cap_selectors();host_cap_wire();
    for(int qrtr=0;qrtr<=6;qrtr++)for(int variant=-1;variant<=2;variant++) {
        qrtr_arg=qrtr;w16_arg=0;w18_arg=variant;wl_probe_configure();
        assert(wl_variant_invalid==(qrtr==5 && (variant<0 || variant>1)));
        assert(wl18_enabled==(qrtr==5 && variant==1));
    }
    timeline_case=0;w18_arg=0;boot16(3,0,true);
    assert(!finish_step() && !strstr(logbuf,"W18") && !wl18_samples);
    check_no_ce();contain();
    for(unsigned variant=0;variant<=4;variant++) {
        boot18(variant,0,0);
        assert(!finish_step() && seen15==3 && wl12_txn==15 && wl_w11_ok);
        assert(wl18_samples==6 && occurrences("W18 MODE TX EOT ptr")==1);
        assert(!wl18_mode_tre);
        assert(strstr(logbuf,"sample 1 phase FW_READY before INI"));
        sample_line("phase MODE before doorbell","txn 15 msg 0x22 reply 0");
        sample_line("phase MODE TX EOT","reply 1");
        sample_line("phase MODE reply/TX drained","reply 1");
        assert(observe_ticks==200 && late_indications==3);
        check_no_ce();readonly18();
        assert(wl18_samples==7);
        wl12_stage=WL15_MODE;
        for(unsigned index=0;index<140;index++) {
            assert(!wl_qrtr_control(7,7,1,0x4000));
            assert(!wl_w11_events());
        }
        assert(occurrences("W18 MODE TX EOT ptr")==1);
        wl12_stage=WL15_OBSERVE;
        wl_channel(20)->rp=0x100000001ull;wl_channel(21)->rp=0x100000002ull;
        readonly18();
        contain();
    }
    for(unsigned injection=0;injection<=2;injection++) {
        boot18(3,22,injection);
        assert(finish_step() && seen15==3 && !observe_ticks && !frees);
        assert(wl18_samples==8 && occurrences("W18 MODE TX EOT ptr")==1);
        assert(strstr(logbuf,"sample 1 phase FW_READY before INI"));
        sample_line("phase MODE pending 100 ms","elapsed 100 ms");
        sample_line("phase MODE pending 1000 ms","elapsed 1000 ms");
        sample_line("phase MODE timeout","elapsed 10000 ms");
        sample_line("phase MODE timeout","valid 1 access-faults 0");
        if(injection==1)sample_line("phase CFG reply/TX drained","changed 0x3c");
        if(injection==2) {
            sample_line("phase MODE before doorbell","changed 0");
            sample_line("phase MODE TX EOT","changed 0x3c");
        }
        check_no_ce();contain();
    }
    boot18(3,22,0);crash_regs(2,0x201);
    assert(finish_step());
    sample_line("phase FW_READY before INI","ERRCODE 0xcafecace ERRDBG 0xcafecace/0x14feeb3/0x496");
    sample_line("phase FW_READY before INI","prior-valid 0 changed 0");
    sample_line("phase MODE TX EOT","changed 0");
    contain();
    boot18(3,0,3);assert(finish_step() && !frees);
    sample_line("phase QMI wait transport failure","EE 0x3 MHISTATUS 0xff05");
    assert(!occurrences("W18 MODE TX EOT ptr"));
    contain();
    boot18(3,0,0);assert(!finish_step());
    read_fault_pa=WL_BAR0+0x138;readonly18();
    assert(!wl18_previous_valid && fw_faults);
    sample_line("phase read-only test","valid 0 access-faults 1");
    read_fault_pa=0;fw_faults=0;loglen=0;logbuf[0]=0;readonly18();
    assert(wl18_previous_valid);
    sample_line("phase read-only test","valid 1 access-faults 0 prior-valid 0 changed 0");
    contain();
    boot18(3,22,0);assert(finish_step());
    fail_bm=fail_perst=true;wl5_abort(28);
    assert(!frees && wl_ipcr.va && wl14_m3.va);
    fail_bm=fail_perst=false;contain();
    const char *profiles[]={NULL,"0","1","2"};
    for(unsigned profile=0;profile<sizeof(profiles)/sizeof(profiles[0]);profile++) {
        for(unsigned failure=0;failure<=22;failure+=22) {
            cap_arg=profiles[profile];boot18(3,failure,0);
            assert(wl18_host_cap==(profile>=2));
            assert(wl18_omit_nm_modem==(profile==3));
            assert((finish_step()!=0)==(failure!=0) && seen15==3);
            assert(!!strstr(logbuf,"HOST_CAP TLV 0x20")== (profile>=2));
            assert(!!strstr(logbuf,"HOST_CAP TLV 0x13 nm_modem omitted")== (profile==3));
            if(failure)sample_line("phase MODE timeout","elapsed 10000 ms");
            check_no_ce();contain();
        }
    }
    cap_arg=NULL;
    puts("W18 selectors, exact QMI, SECONDARY and single-TLV omission, phase transitions, exact MODE EOT, bounded silence, six read-only accesses, faults, RDDM and quarantine passed");
    return 0;
}
'''


def run():
    driver = (ROOT / 'xnu/fuxi-wlan/fuxi_wlan.c').read_text()
    assert 'fw_run(unsigned limit)\n{\n\tif (wl18_cap_refused()) { return; }' in driver
    m6 = w16.w15.w14.w12.w11.w10.m6o.m6
    m6.PREAMBLE = m6.PREAMBLE.replace('static bool PE_parse_boot_argn(',
                                     'static int w18_arg;\nstatic const char *cap_arg;\nstatic bool PE_parse_boot_argn(')
    m6.PREAMBLE = m6.PREAMBLE.replace(
        'static bool PE_parse_boot_arg_str(const char *name, char *out, int size) {',
        'static bool PE_parse_boot_arg_str(const char *name, char *out, int size) {\n'
        '    if(!strcmp(name,"fuxiwlancap")) {\n'
        '        if(cap_arg) { strncpy(out,cap_arg,size); return true; }\n'
        '        return false;\n'
        '    }')
    m6.PREAMBLE = m6.PREAMBLE.replace(
        'if(!strcmp(name,"fuxiwlanw18")) { assert(size==sizeof(int)); return false; }',
        'if(!strcmp(name,"fuxiwlanw18")) { assert(size==sizeof(int)); memcpy(out,&w18_arg,size); return true; }')
    w16.TESTS = TESTS
    w16.main()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standalone', action='store_true')
    arguments = parser.parse_args()
    if not arguments.standalone:
        run()
        return
    m6o = w16.w15.w14.w12.w11.w10.m6o
    with tempfile.TemporaryDirectory(prefix='fuxi-wlan-w18-source-') as temporary:
        fixture = Path(temporary)
        sources = {'xnu/fuxi-wlan/fuxi_wlan.c': 'fuxi_wlan.c',
                   'shim/fuxi-probe/wlan.c': 'wlan.c'}
        hunks = []
        for source, destination in sources.items():
            contents = (ROOT / source).read_text()
            target = fixture / source
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)
            lines = contents.splitlines()
            hunks.append(f'--- a/bsd/dev/{destination}\n+++ b/bsd/dev/{destination}\n'
                         f'@@ -0,0 +1,{len(lines)} @@\n' +
                         ''.join('+' + line + '\n' for line in lines))
        target = fixture / 'xnu/patches/0099-fuxi-wlan.patch'
        target.parent.mkdir(parents=True)
        target.write_text(''.join(hunks))
        target = fixture / 'tools/ci/build.sh'
        target.parent.mkdir(parents=True)
        target.write_text((ROOT / 'tools/ci/build.sh').read_text())
        m6o.ROOT = fixture
        print('W18 standalone source fixtures staged in temporary storage')
        run()


if __name__ == '__main__':
    main()
