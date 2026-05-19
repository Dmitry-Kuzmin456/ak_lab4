.section text
.org 0
_start:
    OUT_CSTR msg
    HLT

.section data
.org 0
msg:
    .cstr "Hello, world!"
