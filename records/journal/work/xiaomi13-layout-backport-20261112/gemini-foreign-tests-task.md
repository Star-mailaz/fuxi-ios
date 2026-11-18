# Task: extend the host test for the new cross-process ("foreign") ASTC import

Scope is deliberately small. Edit exactly ONE file:
`%USERPROFILE%\Documents\Codex\xiaomi13-layout-backport-20261112\harness\tests\FuxiLinearLayoutTests.mm`
Do not create, delete, rename or edit any other file. Do not run git, builds or shell commands
(this machine is Windows; the test only compiles on the macOS CI). Allowed tools: Read, Edit, Grep, Glob.

## Context (read these two files first, nothing else is needed)

1. `%USERPROFILE%\Documents\Codex\xiaomi13-layout-backport-20261112\native\FuxiTextureLayout.inc`
   - New in this change: `fuxiForeignLinearEnabled()`, `gFuxiLayoutForeignImports`, `fuxiSnapshotForeign(...)`
     and the `foreign` branch inside `fuxiImportLinearTexture(...)`.
   - Semantics: when `newTextureWithBytesNoCopy:length:descriptor:deallocator:` receives memory that has NO
     producer record in this process (status `Unknown`), it is now admitted as a row-major ASTC 4x4 snapshot
     if ALL of these hold: environment `FUXI_NATIVE_FOREIGN_LINEAR` is not "0"; the layout has exactly
     1 mip level and 1 slice; base address is a multiple of 16384; `length >= layout.totalBytes`
     (so length 0 is refused); every byte is readable through the bounded self-memory read.
     The existing guards still apply first: ASTC 4x4 LDR/sRGB only, `usage == MTLTextureUsageShaderRead` exactly.
   - If not admitted, the call falls through to the old refusal, which calls the failure hook
     (the test observes that as `latched == true`) and returns nil.
   - If admitted, the bytes `[0, totalBytes)` are copied into an owned snapshot and uploaded with ONE
     upload call (one level, one slice). A supplied deallocator is kept by an owner object and runs exactly
     once when the texture is destroyed. On a refused or failed call the deallocator is NOT invoked.
2. `%USERPROFILE%\Documents\Codex\xiaomi13-layout-backport-20261112\harness\tests\FuxiLinearLayoutTests.mm`
   - Existing helpers you must reuse: `descriptor(w,h,mips)`, `allocate(bytes)` (16384-aligned, filled 0xcc),
     `resetFailure()`, globals `latched`, `failureCalls`, `uploadCalls`, `failUpload`, `failAllocation`,
     class `LayoutTestTexture` with `uploads` (one byte vector per upload call),
     `dev` (a `LayoutTestDevice *`) and the `__block unsigned released` counter declared in `main`.

## What to add

Insert ONE new block of code in `main`, immediately BEFORE the existing line that starts with
` setenv("FUXI_NATIVE_LINEAR_LAYOUT","0",1);resetFailure();`.
Wrap the whole insertion in its own `{ ... }` scope with its own local variable names so the existing
variables `d`, `layout`, `memory`, `texture`, `snapshot`, `block`, `linear`, `raw`, `aligned`, `page`,
`mapping` are not modified or shadowed in a way that changes later code. Start the block with
`resetFailure();` and end it with `resetFailure();` and `unsetenv("FUXI_NATIVE_FOREIGN_LINEAR");`.

Also change only the COMMENT above the existing line
`resetFailure();assert(![dev newTextureWithBytesNoCopy:(void *)16384 length:2752512 descriptor:d deallocator:nil] && latched);`
to: `// Unknown unreadable addresses are refused by the bounded read, even with matching length.`
(the assertion itself stays unchanged).

Test cases the new block must contain, each with a one-line comment:

A. Success with the observed shape. `descriptor(1125,2436)`; `allocate(2752512)`; fill the first 2747808 bytes
   with a position-dependent pattern (for example `(uint8_t)((i/16)*131u + (i%16)*7u + 1u)`), leave the tail as is.
   Call with `length:2752512 deallocator:nil`. Assert: texture non-nil, `!latched`, `failureCalls==0`,
   `uploadCalls` grew by exactly 1, `uploads.size()==1`, `uploads[0].size()==2747808`, and the uploaded bytes
   `memcmp`-equal the source. Then overwrite the source with another value and assert the uploaded copy is unchanged.
B. Deallocator lifecycle on success: pass a block that asserts the pointer and length (2752512) and increments a
   new `__block unsigned` counter. Counter is 0 while the texture is alive, exactly 1 after the last strong
   reference is dropped (use an inner `@autoreleasepool { }` and set the variable to nil, like the existing test does).
C. Refusals. For each: result is nil AND `latched` is true; call `resetFailure()` afterwards. Use the same
   valid 1125x2436 source unless stated otherwise:
   1. base not 16384-aligned: `(uint8_t *)source + 16`, `length:2752512-16`.
   2. short length: `length:2747807`.
   3. zero length: `length:0`.
   4. usage not exactly ShaderRead: copy of the descriptor with `usage = MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget`.
   5. mipmapped: `descriptor(1125,2436,YES)` over a separate allocation sized by
      `[[dev newTextureLayoutWithDescriptor:thatDescriptor isHeapOrBufferBacked:NO] size]` (do NOT call
      `initializeTextureMemory:` on it), `length:` that size.
   6. array: `descriptor(1125,2436)` with `textureType = MTLTextureType2DArray; arrayLength = 2`, allocation sized
      the same way, not initialized.
   7. disabled: `setenv("FUXI_NATIVE_FOREIGN_LINEAR","0",1)` then the valid call is refused; then `unsetenv` and the
      same call succeeds again (`!latched`).
   8. unreadable pages: `descriptor(7,7)` (64 bytes). `mmap` four pages `PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANON`,
      pick the 16384-aligned address inside it exactly as the existing "Safe snapshot failure" test does, fill 64 bytes,
      `mprotect(..., PROT_NONE)`, call with `length:64` -> refused, no crash; then `munmap`.
   9. a refused call must not invoke the deallocator: repeat case 2 with a counting deallocator and assert the
      counter did not change.
D. Upload failure: `failUpload=true`, valid foreign source with a counting deallocator -> nil, `latched`, counter
   unchanged. Then `resetFailure()`.
E. Allocation failure: `failAllocation=true`, valid foreign source with a counting deallocator -> nil, counter
   unchanged (do NOT assert `latched` here: the test device returns nil without calling the failure hook).
   Then `resetFailure()`.
F. A small non-multiple-of-4 shape succeeds: `descriptor(7,7)`, `allocate(64)`, 64 distinct bytes, `length:64` ->
   non-nil, `!latched`, one upload of exactly 64 bytes equal to the source.
G. Free every allocation you made (`free`), and make sure nothing was registered:
   keep the existing final `assert(gFuxiLayoutAllocations.empty() && gFuxiLayoutTrackedBytes==0);` passing.

Also update the final `puts("PASS: ...")` string by appending `, foreign row-major snapshots` before the closing quote.

## Hard constraints (the CI compiles with these; a warning is a failed build)

- `xcrun clang++ -std=c++17 -O1 -g -Wall -Wextra -Werror -Wno-deprecated-declarations -fobjc-arc -fblocks -fsanitize=address,undefined`
- No unused variables or parameters, no signed/unsigned comparison, no shadowing surprises, no implicit
  narrowing that warns. Under ARC a texture dies when its last strong reference goes away; objects returned by
  `new...` methods are owned, but be careful to drop every reference (including temporaries inside an
  `@autoreleasepool`) before asserting that a deallocator ran.
- Blocks that mutate a counter need `__block`. Blocks may capture raw pointers by value.
- Keep the file's existing terse style (single-space indent, several statements per line are fine).
- Do not weaken or delete any existing assertion.

## Report (final message, in English, concise)

1. The exact inserted block (as a code block).
2. For each case A-G: one sentence on why the assertion must hold given `FuxiTextureLayout.inc`.
3. Anything you were unsure about.
4. State clearly that the code was not compiled or run.
