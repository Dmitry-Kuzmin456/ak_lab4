.const USE_MSG 1

.macro PRINT label
    OUT_CSTR label
.endmacro

.section text
.org 0
_start:
    LD_IND ptr
    OUT 0
.ifdef USE_MSG
    PRINT msg
.else
    LD_IMM '?'
    OUT 0
.endif
    HLT

.section data
.org 0
ptr:
    .word 1
value:
    .word 'Z'
msg:
    .cstr "OK"
