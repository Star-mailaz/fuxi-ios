/* SPDX-License-Identifier: MIT */
#include "menu.h"
#include "bootinfo.h"
#include "spmi.h"
#include "fuxi-ram-profile.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr, "FAIL line %u: %s\n", __LINE__, #x); exit(1); } } while (0)

static void test_menu(void)
{
    struct menu m;
    menu_init(&m, MENU_ANDROID, 0);
    CHECK(menu_update(&m, MENU_NONE, 60000) == MENU_WAIT);
    CHECK(m.os == MENU_ANDROID && m.focus == MENU_ANDROID_BUTTON);
    CHECK(menu_update(&m, MENU_CONFIRM, 0) == MENU_BOOT_ANDROID);
    CHECK(menu_update(&m, MENU_DOWN, 0) == MENU_BOOT_ANDROID); /* action latched */
    menu_init(&m, MENU_ANDROID, 0);
    menu_update(&m, MENU_DOWN, 0);
    CHECK(m.focus == MENU_IOS_BUTTON);
    CHECK(menu_update(&m, MENU_CONFIRM, 0) == MENU_BOOT_IOS);
    CHECK(menu_update(&m, MENU_CONFIRM, 0) == MENU_BOOT_IOS);
    menu_init(&m, MENU_IOS, 0);
    CHECK(m.focus == MENU_IOS_BUTTON);
    menu_update(&m, MENU_DOWN, 0);
    menu_update(&m, MENU_CONFIRM, 0);
    CHECK(m.page == MENU_ADVANCED && m.focus == 0 && m.os == MENU_IOS);
    menu_update(&m, MENU_CONFIRM, 0);
    CHECK(m.page == MENU_HOME && m.focus == MENU_OPTIONS && m.os == MENU_IOS);
    menu_update(&m, MENU_DOWN, 0);
    CHECK(m.focus == MENU_ANDROID_BUTTON);
    CHECK(menu_update(&m, MENU_CONFIRM, 0) == MENU_BOOT_ANDROID);
    menu_init(&m, MENU_ANDROID, 0);
    menu_update(&m, MENU_UP, 0);
    CHECK(m.focus == MENU_OPTIONS);
    menu_init(&m, MENU_IOS, 0);
    menu_update(&m, MENU_UP, 0);
    CHECK(menu_update(&m, MENU_CONFIRM, 0) == MENU_BOOT_ANDROID);
    const enum menu_action advanced_actions[] = {
        MENU_WAIT, MENU_FASTBOOT, MENU_RECOVERY, MENU_REBOOT, MENU_POWEROFF
    };
    for (unsigned n = 1; n < MENU_ADVANCED_COUNT; ++n) {
        menu_init(&m, MENU_ANDROID, 0);
        menu_update(&m, MENU_DOWN, 0);
        menu_update(&m, MENU_DOWN, 0);
        menu_update(&m, MENU_CONFIRM, 0);
        for (unsigned i = 0; i < n; ++i) menu_update(&m, MENU_DOWN, 0);
        CHECK(menu_update(&m, MENU_CONFIRM, 0) == advanced_actions[n]);
    }
    menu_init(&m, MENU_IOS, 10000);
    CHECK(menu_update(&m, MENU_NONE, 9999) == MENU_WAIT);
    CHECK(menu_update(&m, MENU_NONE, 1) == MENU_BOOT_ANDROID);
    CHECK(m.os == MENU_ANDROID);
    menu_init(&m, MENU_IOS, 10000);
    CHECK(menu_update(&m, MENU_DOWN, 10000) == MENU_WAIT && m.interacted);
    menu_update(&m, MENU_CONFIRM, 0);
    CHECK(m.page == MENU_ADVANCED);
    menu_update(&m, MENU_BACK, 0);
    CHECK(menu_update(&m, MENU_NONE, 60000) == MENU_WAIT);
    CHECK(m.page == MENU_HOME && m.os == MENU_IOS);
}

static enum menu_event held(struct menu_keys *k, unsigned mask)
{
    enum menu_event e = MENU_NONE;
    for (unsigned i = 0; i < 6; ++i) {
        enum menu_event next = menu_keys_sample(k, mask, 10);
        if (next) { CHECK(!e); e = next; }
    }
    return e;
}
static void test_keys(void)
{
    struct menu_keys k;
    menu_keys_init(&k);
    CHECK(held(&k, MENU_KEY_POWER) == MENU_NONE); /* ABL boot key still held */
    CHECK(held(&k, 0) == MENU_NONE);
    CHECK(held(&k, MENU_KEY_DOWN) == MENU_DOWN);
    CHECK(held(&k, MENU_KEY_DOWN) == MENU_NONE); /* no autorepeat */
    CHECK(held(&k, 0) == MENU_NONE);
    CHECK(held(&k, MENU_KEY_POWER) == MENU_NONE); /* confirm on release */
    CHECK(held(&k, 0) == MENU_CONFIRM);
    CHECK(held(&k, MENU_KEY_POWER) == MENU_NONE);
    CHECK(held(&k, MENU_KEY_POWER | MENU_KEY_DOWN) == MENU_NONE);
    CHECK(held(&k, 0) == MENU_NONE); /* warm-reset chord must not boot */
    CHECK(held(&k, MENU_KEY_UP) == MENU_UP);
    CHECK(held(&k, 0) == MENU_NONE);
    CHECK(held(&k, MENU_KEY_POWER) == MENU_NONE);
    CHECK(menu_keys_sample(&k, MENU_KEY_POWER | MENU_KEY_DOWN, 10) == MENU_NONE);
    CHECK(held(&k, 0) == MENU_NONE); /* even a brief chord cancels pending power */
    for (unsigned i = 0; i < 10; ++i)
        CHECK(menu_keys_sample(&k, i & 1 ? MENU_KEY_POWER : 0, 5) == MENU_NONE);
    CHECK(held(&k, 0) == MENU_NONE); /* bounced contact */
}

static void be32(unsigned char *p, uint32_t v)
{ p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v; }
static void le32(unsigned char *p, uint32_t v)
{ p[3] = v >> 24; p[2] = v >> 16; p[1] = v >> 8; p[0] = v; }
static size_t fixture(unsigned char *b, unsigned cells)
{
    memset(b, 0, 256);
    be32(b, 0xd00dfeedu); be32(b + 8, 56); be32(b + 12, 160);
    be32(b + 16, 40); be32(b + 20, 17); be32(b + 24, 16);
    unsigned p = 56;
    be32(b + p, 1); p += 8; /* root */
    be32(b + p, 1); memcpy(b + p + 4, "chosen", 7); p += 12;
    be32(b + p, 3); be32(b + p + 4, cells); be32(b + p + 8, 0);
    if (cells == 8) be32(b + p + 12, 0);
    be32(b + p + 8 + cells, 0xb6000000); p += 12 + cells;
    be32(b + p, 3); be32(b + p + 4, cells); be32(b + p + 8, sizeof("linux,initrd-start"));
    if (cells == 8) be32(b + p + 12, 0);
    be32(b + p + 8 + cells, 0xb7fff000); p += 12 + cells;
    be32(b + p, 2); be32(b + p + 4, 2); be32(b + p + 8, 9); p += 12;
    const char names[] = "linux,initrd-start\0linux,initrd-end";
    memcpy(b + 160, names, sizeof(names));
    be32(b + 32, sizeof(names)); be32(b + 36, p - 56); be32(b + 4, 160 + sizeof(names));
    return 160 + sizeof(names);
}
static size_t trailer(unsigned char *b, const char *text)
{
    size_t size = strlen(text), bytes = size + 20;
    memcpy(b, text, size);
    uint32_t checksum = 0;
    for (size_t i = 0; i < size; ++i) checksum += b[i];
    le32(b + size, (uint32_t)size); le32(b + size + 4, checksum);
    memcpy(b + size + 8, "#BOOTCONFIG\n", 12);
    return bytes;
}
static void test_bootinfo(void)
{
    unsigned char b[256], copy[256];
    struct menu_bootinfo info;
    size_t bytes = fixture(b, 4);
    CHECK(menu_fdt_initrd(b, bytes, &info));
    CHECK(info.initrd_start == 0xb6000000 && info.initrd_end == 0xb7fff000);
    bytes = fixture(b, 8);
    CHECK(menu_fdt_initrd(b, bytes, &info));
    CHECK(info.initrd_start == 0xb6000000 && info.initrd_end == 0xb7fff000);
    for (size_t n = 0; n < bytes; ++n) CHECK(!menu_fdt_initrd(b, n, &info));
    memcpy(copy, b, 256); be32(copy + 12, 0xffffffffu);
    CHECK(!menu_fdt_initrd(copy, bytes, &info));
    memcpy(copy, b, 256); be32(copy + 80, 0xffffffffu); /* property length */
    CHECK(!menu_fdt_initrd(copy, bytes, &info));
    memcpy(copy, b, 256); be32(copy + 104, 0); /* duplicate initrd-start */
    CHECK(!menu_fdt_initrd(copy, bytes, &info));
    memcpy(copy, b, 256); be32(copy + 84, 0xffffffffu); /* property name offset */
    CHECK(!menu_fdt_initrd(copy, bytes, &info));
    for (size_t i = 0; i < bytes; ++i) {
        memcpy(copy, b, 256); copy[i] ^= 0xff;
        (void)menu_fdt_initrd(copy, bytes, &info); /* ASan/UBSan bounded mutation */
    }
    bytes = trailer(b, "androidboot.force_normal_boot = \"0\"\n");
    CHECK(menu_bootconfig_normal(b, bytes) == 1);
    b[0] ^= 1;
    CHECK(menu_bootconfig_normal(b, bytes) == -1);
    bytes = trailer(b, "# androidboot.force_normal_boot=0\n");
    CHECK(menu_bootconfig_normal(b, bytes) == 0);
    bytes = trailer(b, "androidboot.force_normal_boot_extra=0\n");
    CHECK(menu_bootconfig_normal(b, bytes) == 0);
    bytes = trailer(b, "value=\"androidboot.force_normal_boot=0\"\n");
    CHECK(menu_bootconfig_normal(b, bytes) == 0);
    bytes = trailer(b, "androidboot.slot_suffix=\"_b\"\n");
    CHECK(menu_bootconfig_normal(b, bytes) == 0);
    for (size_t n = 0; n < bytes; ++n) CHECK(menu_bootconfig_normal(b, n) == -1);
    le32(b + bytes - 20, 0xffffffffu);
    CHECK(menu_bootconfig_normal(b, bytes) == -1);
}

/* Transaction model, including failure/ownership/readback injection. */
struct model {
    uint8_t peripheral[3][256];
    unsigned reg[3], status, channel_writes, pending, owner;
    int fail, corrupt, timeout;
};
static int model_read(void *ctx, uintptr_t a, uint32_t *v)
{
    struct model *m = ctx;
    if (m->fail) return 0;
    if (a == 0xc400000) *v = 0x70000000u;
    else if (a == 0xc400004) *v = 3;
    else if (a >= 0xc402000 && a < 0xc40200c) {
        unsigned i = (unsigned)(a - 0xc402000) / 4;
        *v = ((i == 0 ? 0x013 : i == 1 ? 0x18d : 0x071) << 8) | (1u << 24);
    } else if (a >= 0xc42d000 && a < 0xc42d00c) *v = a == 0xc42d008 ? m->owner : 0;
    else if (a >= 0xc440000 && a < 0xc440060) {
        unsigned i = (unsigned)(a - 0xc440000) / 0x20, off = a & 31u;
        *v = off == 8 ? (m->timeout ? 0 : m->status) : m->peripheral[i][m->reg[i]];
    } else if (a == 0xc502008) *v = m->timeout ? 0 : m->status;
    else { CHECK(0); }
    return 1;
}
static int model_write(void *ctx, uintptr_t a, uint32_t v)
{
    struct model *m = ctx;
    if (m->fail) return 0;
    if (a >= 0xc440000 && a < 0xc440060 && (a & 31u) == 0) {
        CHECK((v >> 27) == 1);
        m->reg[(a - 0xc440000) / 0x20] = (v >> 4) & 255;
    } else if (a == 0xc502010) m->pending = v;
    else if (a == 0xc502000) {
        CHECK(v == (0x48u << 4));
        ++m->channel_writes;
        m->peripheral[2][0x48] = (uint8_t)(m->pending ^ (m->corrupt ? 2u : 0u));
    } else CHECK(0);
    return 1;
}
static void model_delay(void *ctx, unsigned us) { (void)ctx; (void)us; }
static void test_spmi(void)
{
    struct model model = {0};
    model.status = 1;
    model.peripheral[1][4] = 0x10;
    model.peripheral[1][0x46] = 0x80;
    model.peripheral[1][0x10] = 1;
    struct menu_bus bus = {&model, model_read, model_write, model_delay};
    struct menu_spmi spmi;
    CHECK(menu_spmi_open(&spmi, &bus));
    CHECK(model.channel_writes == 0); /* opening/keys never write PMIC state */
    unsigned mask = 99;
    CHECK(menu_spmi_keys(&spmi, &mask) && !mask);
    model.peripheral[0][0x10] = 0xc0;
    model.peripheral[1][0x10] = 0;
    CHECK(menu_spmi_keys(&spmi, &mask) && mask == 7);
    model.peripheral[2][0x48] = 0xf3;
    CHECK(menu_spmi_set_reboot_mode(&spmi, MENU_FASTBOOT));
    CHECK(model.peripheral[2][0x48] == 5 && model.channel_writes == 1);
    CHECK(menu_spmi_set_reboot_mode(&spmi, MENU_RECOVERY));
    CHECK(model.peripheral[2][0x48] == 3 && model.channel_writes == 2);
    model.peripheral[2][0x48] = 0;
    CHECK(menu_spmi_set_reboot_mode(&spmi, MENU_RECOVERY));
    CHECK(model.peripheral[2][0x48] == 2 && model.channel_writes == 3);
    CHECK(!menu_spmi_set_reboot_mode(&spmi, MENU_BOOT_ANDROID) && model.channel_writes == 3);
    spmi.sdam_owner = 1;
    CHECK(!menu_spmi_set_reboot_mode(&spmi, MENU_RECOVERY) && model.channel_writes == 3);
    spmi.sdam_owner = 0; model.corrupt = 1;
    CHECK(!menu_spmi_set_reboot_mode(&spmi, MENU_RECOVERY));
    model.status = 3;
    CHECK(!menu_spmi_keys(&spmi, &mask));
    model.status = 1; model.timeout = 1;
    CHECK(!menu_spmi_keys(&spmi, &mask));
    model.timeout = 0; model.fail = 1;
    CHECK(!menu_spmi_open(&spmi, &bus));
    model.fail = 0; model.peripheral[1][0x46] = 0;
    CHECK(!menu_spmi_open(&spmi, &bus));
}

static void write_preview(const char *directory, const char *name, struct menu *m,
                          const char *status)
{
    unsigned w = 1080, h = 2400;
    uint32_t *pixels = calloc(w * h, sizeof(*pixels));
    struct menu_paint_state state = {0};
    CHECK(pixels && menu_paint(&state, m, pixels, w, h, w, (size_t)w * h, 0));
    if (status) CHECK(menu_paint_status(&state, pixels, w, h, w, (size_t)w * h, status));
    char path[4096];
    CHECK(snprintf(path, sizeof(path), "%s/%s.ppm", directory, name) < (int)sizeof(path));
    FILE *f = fopen(path, "wb"); CHECK(f);
    fprintf(f, "P6\n%u %u\n255\n", w, h);
    int wrote_all = 1;
    for (unsigned i = 0; i < w * h; ++i) {
        unsigned char rgb[3] = {(unsigned char)(pixels[i] >> 16), (unsigned char)(pixels[i] >> 8), (unsigned char)pixels[i]};
        if (fwrite(rgb, 1, 3, f) != 3) { wrote_all = 0; break; }
    }
    CHECK(wrote_all);
    CHECK(fclose(f) == 0); free(pixels);
}
static void test_render(const char *directory)
{
    unsigned w = 540, h = 1200, stride = 544;
    size_t n = (size_t)stride * h;
    uint32_t *p = malloc((n + 2) * sizeof(*p)); CHECK(p);
    for (size_t i = 0; i < n + 2; ++i) p[i] = 0x12345678;
    struct menu m; menu_init(&m, MENU_ANDROID, 10000);
    CHECK(!menu_draw(&m, p + 1, w, h, stride, n - stride, 0));
    CHECK(!menu_draw(&m, p + 1, w, h, w - 1, n, 0));
    CHECK(menu_draw(&m, p + 1, w, h, stride, n, 0));
    CHECK(p[0] == 0x12345678 && p[n + 1] == 0x12345678);
    unsigned white = 0;
    int valid_colors = 1, valid_padding = 1;
    for (unsigned y = 0; y < h; ++y) {
        for (unsigned x = 0; x < w; ++x) {
            uint32_t color = p[1 + y * stride + x];
            if (color != 0xff000000 && color != 0xffffffff) valid_colors = 0;
            if (color == 0xffffffff) ++white;
        }
        for (unsigned x = w; x < stride; ++x) if (p[1 + y * stride + x] != 0x12345678) valid_padding = 0;
    }
    CHECK(valid_colors && valid_padding && white > 3000);
    free(p);
    if (directory) {
        write_preview(directory, "home-android", &m, 0);
        menu_update(&m, MENU_DOWN, 0);
        write_preview(directory, "home-ios", &m, 0);
        write_preview(directory, "launching-ios", &m, "進入系統中");
        menu_update(&m, MENU_DOWN, 0);
        write_preview(directory, "home-options", &m, 0);
        menu_update(&m, MENU_CONFIRM, 0);
        for (unsigned i = 0; i < MENU_RECOVERY_BUTTON; ++i) menu_update(&m, MENU_DOWN, 0);
        write_preview(directory, "advanced", &m, 0);
    }
}

static void test_partial_render(void)
{
    unsigned w = 540, h = 1200, stride = 544;
    size_t n = (size_t)stride * h;
    uint32_t *frame = calloc(n, sizeof(*frame));
    uint32_t *fresh = calloc(n, sizeof(*fresh));
    CHECK(frame && fresh);
    struct menu m;
    struct menu_paint_state state = {0};
    menu_init(&m, MENU_ANDROID, 8000);
    CHECK(menu_paint(&state, &m, frame, w, h, stride, n, 0));
    CHECK(!menu_paint(&state, &m, frame, w, h, stride, n, 0));
    CHECK(state.countdown_seconds == 8);
    CHECK(menu_update(&m, MENU_NONE, 999) == MENU_WAIT);
    CHECK(!menu_paint(&state, &m, frame, w, h, stride, n, 0));
    CHECK(menu_update(&m, MENU_NONE, 1) == MENU_WAIT);
    CHECK(menu_paint(&state, &m, frame, w, h, stride, n, 0));
    CHECK(state.countdown_seconds == 7);
    CHECK(menu_draw(&m, fresh, w, h, stride, n, 0));
    CHECK(memcmp(frame, fresh, n * sizeof(*frame)) == 0);
    size_t title = 220u * stride + 250, label = 487u * stride + 270;
    uint32_t original_title = frame[title], original_label = frame[label];
    frame[title] = frame[label] = 0x12345678;
    menu_update(&m, MENU_DOWN, 0);  /* Focus and countdown changes. */
    CHECK(menu_paint(&state, &m, frame, w, h, stride, n, 0));
    CHECK(state.countdown_seconds == 0);
    CHECK(frame[title] == 0x12345678 && frame[label] == 0x12345678);
    frame[title] = original_title;
    frame[label] = original_label;
    CHECK(menu_draw(&m, fresh, w, h, stride, n, 0));
    CHECK(memcmp(frame, fresh, n * sizeof(*frame)) == 0);
    const enum menu_event events[] = {MENU_DOWN, MENU_CONFIRM, MENU_UP,
                                      MENU_DOWN, MENU_BACK, MENU_UP};
    for (unsigned i = 0; i < sizeof(events) / sizeof(events[0]); ++i) {
        menu_update(&m, events[i], 0);
        frame[title] = 0x12345678;
        CHECK(menu_paint(&state, &m, frame, w, h, stride, n, 0));
        CHECK(frame[title] == 0x12345678);
        frame[title] = original_title;
        CHECK(menu_draw(&m, fresh, w, h, stride, n, 0));
        CHECK(memcmp(frame, fresh, n * sizeof(*frame)) == 0);
    }
    CHECK(menu_paint(&state, &m, frame, w, h, stride, n, "測試"));
    CHECK(menu_paint(&state, &m, frame, w, h, stride, n, 0));
    CHECK(memcmp(frame, fresh, n * sizeof(*frame)) == 0);
    /* 選定後：提示列換成「進入系統中」，上方標題與按鈕不動。 */
    struct menu_paint_state blank = {0};
    CHECK(!menu_paint_status(&blank, frame, w, h, stride, n, "進入系統中"));
    CHECK(!menu_paint_status(&state, frame, w, h, stride, n, ""));
    CHECK(!menu_paint_status(&state, frame, w, h, stride - 5, n, "進入系統中"));
    CHECK(memcmp(frame, fresh, n * sizeof(*frame)) == 0);
    CHECK(menu_paint_status(&state, frame, w, h, stride, n, "進入系統中"));
    unsigned hint_top = 1820u * h / 2400, hint_bottom = 2144u * h / 2400;
    CHECK(memcmp(frame, fresh, (size_t)hint_top * stride * sizeof(*frame)) == 0);
    CHECK(memcmp(frame + (size_t)hint_bottom * stride, fresh + (size_t)hint_bottom * stride,
                 (size_t)(h - hint_bottom) * stride * sizeof(*frame)) == 0);
    unsigned status_white = 0, valid = 1;
    for (unsigned y = hint_top; y < hint_bottom; ++y)
        for (unsigned x = 0; x < w; ++x) {
            uint32_t color = frame[(size_t)y * stride + x];
            if (color != 0xff000000 && color != 0xffffffff) valid = 0;
            if (color == 0xffffffff) ++status_white;
        }
    CHECK(valid && status_white > 300);
    CHECK(memcmp(frame + (size_t)hint_top * stride, fresh + (size_t)hint_top * stride,
                 (size_t)(hint_bottom - hint_top) * stride * sizeof(*frame)) != 0);
    CHECK(!menu_paint_status(&state, frame, w, h, stride, n, "進入系統中"));
    CHECK(menu_paint(&state, &m, frame, w, h, stride, n, 0));
    CHECK(memcmp(frame, fresh, n * sizeof(*frame)) == 0);
    free(frame);
    free(fresh);
}
static void replay_fdt(const char *path)
{
    FILE *f = fopen(path, "rb"); CHECK(f);
    CHECK(fseek(f, 0, SEEK_END) == 0);
    long length = ftell(f); CHECK(length >= 40 && length <= (2 << 20));
    rewind(f);
    unsigned char *data = malloc((size_t)length); CHECK(data);
    CHECK(fread(data, 1, (size_t)length, f) == (size_t)length);
    CHECK(fclose(f) == 0);
    struct menu_bootinfo info;
    CHECK(menu_fdt_initrd(data, (size_t)length, &info));
    CHECK(info.initrd_start >= 0x80000000 && info.initrd_end <= 0xb8000000);
    CHECK(fuxi_ram_profile_check(data, (size_t)length, FUXI_RAM_PROFILE_BASE, FUXI_RAM_PROFILE_9G) == FuxiRamProfileStaticOk12G);
    CHECK(fuxi_ram_profile_check(data, (size_t)length, FUXI_RAM_PROFILE_BASE, FUXI_RAM_PROFILE_5G) == FuxiRamProfileStaticOk12G);
    printf("SAVED_FDT_REPLAY_OK %ld bytes\n", length);
    free(data);
}
int main(int argc, char **argv)
{
    test_menu(); test_keys(); test_bootinfo(); test_spmi();
    test_render(argc > 1 ? argv[1] : NULL);
    test_partial_render();
    if (argc > 2) replay_fdt(argv[2]);
    printf("PASS %u assertions; state, keys, FDT/bootconfig, SPMI, framebuffer bounds\n", checks);
    return 0;
}
