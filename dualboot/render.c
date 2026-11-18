/* SPDX-License-Identifier: MIT */
#include "menu.h"
#include "font-generated.h"
#define BLACK UINT32_C(0xff000000)
#define WHITE UINT32_C(0xffffffff)
enum { BUTTON_X = 112, BUTTON_WIDTH = 856, BUTTON_HEIGHT = 156 };
struct canvas { volatile uint32_t *p; unsigned w, h, stride; };

static void rect(struct canvas *c, unsigned x, unsigned y, unsigned w, unsigned h, uint32_t color)
{
    unsigned x0 = x * c->w / 1080, y0 = y * c->h / 2400;
    unsigned x1 = (x + w) * c->w / 1080, y1 = (y + h) * c->h / 2400;
    if (x1 > c->w) x1 = c->w;
    if (y1 > c->h) y1 = c->h;
    for (unsigned row = y0; row < y1; ++row)
        for (unsigned col = x0; col < x1; ++col) c->p[row * c->stride + col] = color;
}

static const struct menu_glyph *glyph(uint32_t code)
{
    unsigned lo = 0, hi = MENU_GLYPH_COUNT;
    while (lo < hi) {
        unsigned mid = lo + (hi - lo) / 2;
        if (menu_glyphs[mid].code < code) lo = mid + 1;
        else hi = mid;
    }
    if (lo < MENU_GLYPH_COUNT && menu_glyphs[lo].code == code) return &menu_glyphs[lo];
    /* Missing glyphs are visible, never silently dropped. */
    if (code != '?') return glyph('?');
    return &menu_glyphs[0];
}

static uint32_t next(const unsigned char **s)
{
    uint32_t a = *(*s)++;
    if (a < 128) return a;
    if (a >= 0xc2 && a <= 0xdf && **s && (**s & 0xc0) == 0x80) {
        uint32_t b = *(*s)++; return ((a & 31u) << 6) | (b & 63u);
    }
    if (a >= 0xe0 && a <= 0xef && **s && (*s)[1] &&
        ((*s)[0] & 0xc0) == 0x80 && ((*s)[1] & 0xc0) == 0x80) {
        uint32_t b = *(*s)++, d = *(*s)++;
        return ((a & 15u) << 12) | ((b & 63u) << 6) | (d & 63u);
    }
    return '?';
}

static void centered_in(struct canvas *c, unsigned left, unsigned width,
                        unsigned y, const char *text, unsigned scale)
{
    const unsigned char *s = (const unsigned char *)text;
    unsigned length = 0;
    while (*s) length += glyph(next(&s))->advance * scale;
    unsigned x = length < width ? left + (width - length) / 2 : left;
    s = (const unsigned char *)text;
    while (*s) {
        const struct menu_glyph *g = glyph(next(&s));
        if (x + g->advance * scale > left + width) break;
        for (unsigned gy = 0; gy < 64; ++gy)
            for (unsigned gx = 0; gx < 64; ++gx)
                if (g->bits[gy * 8 + gx / 8] & (0x80u >> (gx % 8)))
                    rect(c, x + gx * scale, y + gy * scale, scale, scale, WHITE);
        x += g->advance * scale;
    }
}

static void centered(struct canvas *c, unsigned y, const char *text, unsigned scale)
{ centered_in(c, 60, 960, y, text, scale); }

static void draw_countdown(struct canvas *c, unsigned seconds)
{
    static const char suffix[] = " 秒後啟動 Android";
    enum { MAX_DIGITS = 7 }; /* ceil(UINT32_MAX / 1000) fits in seven digits. */
    char text[MAX_DIGITS + sizeof(suffix)];
    for (size_t i = 0; i < sizeof(suffix); ++i) text[MAX_DIGITS + i] = suffix[i];
    char *start = text + MAX_DIGITS;
    do {
        *--start = (char)('0' + seconds % 10);
        seconds /= 10;
    } while (seconds);
    centered(c, 2080, start, 1);
}

static unsigned button_y(enum menu_page page, unsigned focus)
{
    return page == MENU_HOME ? 900 + 250 * focus : 780 + 180 * focus;
}

static void button_focus(struct canvas *c, unsigned y, int focused)
{
    unsigned x = BUTTON_X, right = x + BUTTON_WIDTH, bottom = y + BUTTON_HEIGHT;
    uint32_t color = focused ? WHITE : BLACK;
    /* Paint the inner four pixels of the outline. Leave the label and
     * the permanent outer pixel in place while the panel is scanning. */
    rect(c, x + 1, y + 1, BUTTON_WIDTH - 2, 4, color);
    rect(c, x + 1, bottom - 5, BUTTON_WIDTH - 2, 4, color);
    rect(c, x + 1, y + 5, 4, BUTTON_HEIGHT - 10, color);
    rect(c, right - 5, y + 5, 4, BUTTON_HEIGHT - 10, color);
    if (focused) {
        for (unsigned i = 0; i < 18; ++i) {
            rect(c, x + 26 + i, y + 60 + i, 3, 3, WHITE);
            rect(c, x + 26 + i, y + 94 - i, 3, 3, WHITE);
        }
    } else rect(c, x + 26, y + 60, 20, 37, BLACK);
}

static void button(struct canvas *c, const struct menu *m, unsigned focus, const char *label)
{
    unsigned x = BUTTON_X, y = button_y(m->page, focus);
    rect(c, x, y, BUTTON_WIDTH, 1, WHITE);
    rect(c, x, y + BUTTON_HEIGHT - 1, BUTTON_WIDTH, 1, WHITE);
    rect(c, x, y, 1, BUTTON_HEIGHT, WHITE);
    rect(c, x + BUTTON_WIDTH - 1, y, 1, BUTTON_HEIGHT, WHITE);
    centered_in(c, x + 50, BUTTON_WIDTH - 100, y + 46, label, 1);
    if (m->focus == focus) button_focus(c, y, 1);
}

static int geometry_ok(volatile uint32_t *p, unsigned w, unsigned h, unsigned stride, size_t capacity)
{
    return p && w >= 320 && w <= 2160 && h >= 700 && h <= 4800 &&
           stride >= w && stride <= 8192 && capacity / stride >= h;
}

int menu_paint(struct menu_paint_state *state, const struct menu *m,
               volatile uint32_t *p, unsigned w, unsigned h, unsigned stride,
               size_t capacity, const char *notice)
{
    if (!state || !m || !geometry_ok(p, w, h, stride, capacity) ||
        (m->page != MENU_HOME && m->page != MENU_ADVANCED) ||
        m->focus >= (m->page == MENU_HOME ? MENU_HOME_COUNT : MENU_ADVANCED_COUNT)) return 0;
    struct canvas c = {p, w, h, stride};
    int first = !state->drawn;
    int page_changed = first || state->page != m->page;
    int focus_changed = state->focus != m->focus;
    if (notice && !*notice) notice = 0;
    unsigned seconds = !notice && !m->interacted && m->page == MENU_HOME
        ? m->remaining_ms / 1000 + (m->remaining_ms % 1000 != 0) : 0;
    int notice_changed = state->notice != notice || state->countdown_seconds != seconds;
    if (!page_changed && !focus_changed && !notice_changed) return 0;
    if (first) {
        rect(&c, 0, 0, 1080, 2400, BLACK);
        centered(&c, 430, "dualboot", 2);
        centered(&c, 600, "for fuxi", 1);
        centered(&c, 1820, "音量上 / 下：移動", 1);
    }
    if (page_changed) {
        if (!first) {
            rect(&c, BUTTON_X, 780, BUTTON_WIDTH, 876, BLACK);
            rect(&c, 60, 1910, 960, 64, BLACK);
        }
        if (m->page == MENU_HOME) {
            button(&c, m, MENU_ANDROID_BUTTON, "Android");
            button(&c, m, MENU_IOS_BUTTON, "iOS");
            button(&c, m, MENU_OPTIONS, "其他選項");
        } else {
            button(&c, m, MENU_RETURN_BUTTON, "返回");
            button(&c, m, MENU_FASTBOOT_BUTTON, "Fastboot");
            button(&c, m, MENU_RECOVERY_BUTTON, "Recovery");
            button(&c, m, MENU_REBOOT_BUTTON, "重新啟動");
            button(&c, m, MENU_POWEROFF_BUTTON, "關機");
        }
        centered(&c, 1910, m->page == MENU_HOME ? "短按電源：啟動 / 進入" : "短按電源：確認", 1);
    } else if (focus_changed) {
        button_focus(&c, button_y(m->page, state->focus), 0);
        button_focus(&c, button_y(m->page, m->focus), 1);
    }
    if (notice_changed) {
        if (!first) rect(&c, 60, 2080, 960, 64, BLACK);
        if (notice) centered(&c, 2080, notice, 1);
        else if (seconds) draw_countdown(&c, seconds);
    }
    state->drawn = 1;
    state->page = m->page;
    state->focus = m->focus;
    state->notice = notice;
    state->countdown_seconds = seconds;
    return 1;
}

int menu_paint_status(struct menu_paint_state *state, volatile uint32_t *p, unsigned w,
                      unsigned h, unsigned stride, size_t capacity, const char *status)
{
    if (!state || !state->drawn || !status || !*status || !geometry_ok(p, w, h, stride, capacity))
        return 0;
    struct canvas c = {p, w, h, stride};
    /* 2026-11-18 使用者回報選擇後畫面停住約 10 秒像沒反應：把下方按鍵提示與
     * notice（1820–2144）換成狀態文字。標題與按鈕保留，直到所選系統接手面板。 */
    rect(&c, 60, 1820, 960, 324, BLACK);
    centered(&c, 1865, status, 1);
    state->drawn = 0; /* 之後若再畫選單，整頁重畫 */
    return 1;
}

int menu_draw(const struct menu *m, volatile uint32_t *p, unsigned w, unsigned h,
              unsigned stride, size_t capacity, const char *notice)
{
    struct menu_paint_state state = {0};
    return menu_paint(&state, m, p, w, h, stride, capacity, notice);
}
