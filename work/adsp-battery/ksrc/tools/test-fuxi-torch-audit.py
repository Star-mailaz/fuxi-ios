import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "fuxi_torch_audit.h"
#include "fuxi_torch_pulse.h"

typedef struct {
    uint8_t registers[256];
    uint8_t postdisable_status;
    unsigned reads;
    unsigned fail_read;
    uint64_t now;
    FuxiTorchAudit audit;
} Model;

static int read_register(void *context, unsigned offset, uint8_t *value)
{
    Model *model = context;
    int result = ++model->reads == model->fail_read ? -1 : 0;
    assert(offset < 256);
    if (!result) *value = model->registers[offset];
    if (!result && model->postdisable_status && offset == 9 &&
        model->now > model->audit.started && !model->registers[0x4e] &&
        !(model->registers[0x46] & 0x80)) *value = model->postdisable_status;
    fuxi_torch_audit_record(&model->audit, 'R', offset, result ? 0 : *value, result, model->now);
    return result;
}

static int write_register(void *context, unsigned offset, uint8_t value)
{
    Model *model = context;
    assert(offset < 256);
    model->registers[offset] = value;
    fuxi_torch_audit_record(&model->audit, 'W', offset, value, 0, model->now);
    return 0;
}

static void wait_us(void *context, unsigned duration)
{
    Model *model = context;
    fuxi_torch_audit_record(&model->audit, 'S', duration, 0, 0, model->now);
    model->now += (uint64_t)duration * 1000;
    fuxi_torch_audit_record(&model->audit, 'E', duration, 0, 0, model->now);
}

static void fixture(Model *model)
{
    memset(model, 0, sizeof(*model));
    model->registers[4] = 0x18;
    model->registers[5] = 7;
    model->registers[0x42] = 23;
    model->registers[0x49] = 0x0a;
    model->registers[0x4a] = 1;
    model->now = 1000000;
    fuxi_torch_audit_begin(&model->audit, model->now);
}

int main(void)
{
    Model model;
    fixture(&model);
    uint8_t original[256];
    memcpy(original, model.registers, sizeof(original));
    FuxiTorchIo io = {&model, read_register, write_register, wait_us};
    assert(!fuxi_torch_pulse_level(&io, 4));
    assert(!memcmp(original, model.registers, sizeof(original)));
    assert(model.audit.count < FUXI_TORCH_AUDIT_CAPACITY && !model.audit.dropped);
    assert(model.audit.events[0].operation == 'R' && model.audit.events[0].offset == 4);
    assert(model.audit.events[model.audit.count - 1].elapsed_us == 81000);
    unsigned wait_events = 0;
    unsigned timer_event = FUXI_TORCH_AUDIT_CAPACITY;
    unsigned timer_verified = FUXI_TORCH_AUDIT_CAPACITY;
    unsigned module_event = FUXI_TORCH_AUDIT_CAPACITY;
    unsigned channel_event = FUXI_TORCH_AUDIT_CAPACITY;
    for (unsigned index = 0; index < model.audit.count; index++) {
        const FuxiTorchAuditEvent *event = &model.audit.events[index];
        assert(!event->result);
        if (event->offset == 0x3e && event->value == 0x89) {
            if (event->operation == 'W') {
                assert(timer_event == FUXI_TORCH_AUDIT_CAPACITY);
                timer_event = index;
                unsigned code = event->value & 0x7fu;
                unsigned mainline_us = code * 10000u;
                unsigned oem_us = (code + 1u) * 10000u;
                assert(event->value & 0x80);
                assert(mainline_us == 90000u && oem_us == 100000u);
                assert(mainline_us <= 100000u && oem_us <= 100000u);
            } else if (event->operation == 'R') {
                assert(timer_verified == FUXI_TORCH_AUDIT_CAPACITY);
                timer_verified = index;
            }
        }
        if (event->operation == 'W' && event->offset == 0x46 && (event->value & 0x80))
            module_event = index;
        if (event->operation == 'W' && event->offset == 0x4e && event->value == 1)
            channel_event = index;
        if (event->operation == 'S' || event->operation == 'E') {
            assert(event->offset == 80000 || event->offset == 1000);
            wait_events++;
        }
    }
    assert(wait_events == 4);
    assert(timer_event < timer_verified && timer_verified < module_event);
    assert(module_event < channel_event && channel_event < model.audit.count);
    unsigned read_count = model.reads;
    for (unsigned failure = 1; failure <= read_count; failure++) {
        fixture(&model);
        model.fail_read = failure;
        assert(fuxi_torch_pulse_level(&io, 4) < 0);
        unsigned errors = 0;
        for (unsigned index = 0; index < model.audit.count; index++) {
            const FuxiTorchAuditEvent *event = &model.audit.events[index];
            if (event->result) {
                assert(event->operation == 'R' && event->result == -1 && !event->value);
                errors++;
            }
        }
        assert(errors == 1 && !model.audit.dropped);
    }
    fixture(&model);
    model.postdisable_status = 0x10;
    assert(fuxi_torch_pulse_level(&io, 4) == -5);
    assert(!memcmp(original, model.registers, sizeof(original)));
    unsigned postdisable_events = 0;
    for (unsigned index = 0; index < model.audit.count; index++) {
        const FuxiTorchAuditEvent *event = &model.audit.events[index];
        assert(!event->result);
        if (event->operation == 'R' && event->offset == 9 && event->value == 0x10) {
            assert(event->elapsed_us == 81000);
            postdisable_events++;
        }
    }
    assert(postdisable_events == 1 && !model.audit.dropped);
    fixture(&model);
    fuxi_torch_audit_record(&model.audit, 'R', 7, 0x20, -2, model.now - 1);
    assert(model.audit.events[0].elapsed_us == UINT64_MAX);
    fuxi_torch_audit_begin(&model.audit, UINT64_MAX - 999);
    fuxi_torch_audit_record(&model.audit, 'W', 0x46, 0x80, 0, UINT64_MAX);
    assert(!model.audit.events[0].elapsed_us);
    for (unsigned index = 1; index < FUXI_TORCH_AUDIT_CAPACITY + 10; index++)
        fuxi_torch_audit_record(&model.audit, 'R', index, 0, 0, UINT64_MAX);
    assert(model.audit.count == FUXI_TORCH_AUDIT_CAPACITY && model.audit.dropped == 10);
    model.audit.dropped = UINT32_MAX;
    fuxi_torch_audit_record(&model.audit, 'R', 0, 0, 0, UINT64_MAX);
    assert(model.audit.dropped == UINT32_MAX);
    fuxi_torch_audit_begin(&model.audit, 0);
    assert(!model.audit.count && !model.audit.dropped && !model.audit.started);
    fuxi_torch_audit_begin(NULL, 0);
    fuxi_torch_audit_record(NULL, 'R', 0, 0, 0, 0);
    puts("PASS production torch audit: 0x89 dual-primary source bounds and verified timer-before-enable, postdisable 0x09 bit4 recorded/refused, bounded disable confirmation, every read failure, sleep timing, 64-event bound, reset, clock rollback and overflow; no device cutoff proof");
    return 0;
}
'''

specification = importlib.util.spec_from_file_location('audio_compiler', ROOT / 'tools/test-fuxi-audio-prep.py')
module = importlib.util.module_from_spec(specification)
specification.loader.exec_module(module)
compiler, environment = module.compiler_environment()
microsoft = Path(compiler[0]).name.lower() in ('cl', 'cl.exe')
with tempfile.TemporaryDirectory(prefix='fuxi-torch-audit-') as temporary:
    directory = Path(temporary)
    source = directory / 'audit.c'
    binary = directory / ('audit.exe' if os.name == 'nt' else 'audit')
    source.write_text(SOURCE, encoding='utf-8', newline='\n')
    if microsoft:
        command = compiler + ['/nologo', '/std:c11', '/W4', '/WX', '/Zi', '/Od', '/fsanitize=address',
                   '/I' + str(ROOT / 'xnu/fuxi-adsp'), str(source), '/Fe' + str(binary)]
    else:
        command = compiler + ['-std=c11', '-g', '-Wall', '-Wextra', '-Werror',
                   '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                   '-I' + str(ROOT / 'xnu/fuxi-adsp'), str(source), '-o', str(binary)]
    subprocess.run(command, cwd=directory, env=environment, check=True)
    subprocess.run([str(binary)], cwd=directory, env=environment, check=True, timeout=60)
