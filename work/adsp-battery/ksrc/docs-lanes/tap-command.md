# Device UI scripts in ADT

Synthetic UI tests still require the explicit `fuxitaps=S` boot argument.
The `fuxitapcmd` boot argument keeps priority. When it is absent, the key
thread can read `/chosen/fuxi,tapcmd` instead. The ADT value must contain
between one and 399 command bytes followed by one NUL, with no embedded
NUL. Missing or malformed properties stop the test script.

This leaves the original GPU and daily boot arguments available within
the 608-byte payload field. The command grammar, coordinates, delays and
three existing presets are unchanged. No synthetic input starts in a
daily boot that omits `fuxitaps`.

`tools/test-fuxi-tap-command.py` compiles the production property reader
with independent boot-argument and device-tree stubs. It checks argument
priority, missing properties, lookup failures, length limits and string
termination under ASan/UBSan.
