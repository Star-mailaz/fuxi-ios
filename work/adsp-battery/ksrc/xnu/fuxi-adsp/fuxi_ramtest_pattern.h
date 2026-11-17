#ifndef FUXI_RAMTEST_PATTERN_H
#define FUXI_RAMTEST_PATTERN_H
#include <stddef.h>
#include <stdint.h>

static inline uint64_t fuxi_ramtest_allocation_bytes(unsigned mode)
{
    if (mode == 1) return 128ull * 1024 * 1024;
    if (mode == 2) return 512ull * 1024 * 1024;
    return 0;
}

static inline int fuxi_ramtest_page_allowed(uint64_t physical, uint64_t page_size)
{
    return page_size && !(page_size & (page_size - 1)) &&
        !(physical & (page_size - 1)) && physical >= 0x8c0000000ull &&
        physical < 0xafe000000ull && page_size <= 0xafe000000ull - physical;
}

static inline uint64_t fuxi_ramtest_word(size_t index, unsigned pass)
{
    static const uint64_t seeds[] = {
        0, UINT64_MAX, 0xaaaaaaaaaaaaaaaaull, 0x5555555555555555ull
    };
    return ((uint64_t)index + 1) * 0x9e3779b97f4a7c15ull ^ seeds[pass & 3u];
}

static inline void fuxi_ramtest_fill(volatile uint64_t *memory, size_t words, unsigned pass)
{
    for (size_t index = 0; index < words; index++) {
        memory[index] = fuxi_ramtest_word(index, pass);
    }
}

static inline size_t fuxi_ramtest_verify(const volatile uint64_t *memory, size_t words, unsigned pass)
{
    for (size_t index = 0; index < words; index++) {
        if (memory[index] != fuxi_ramtest_word(index, pass)) return index;
    }
    return words;
}
#endif
