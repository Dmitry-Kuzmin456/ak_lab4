.section text
.org 0
_start:
    LD low_a
    ADD low_b
    ST low_result
    LD high_a
    ADD high_b
    ST high_result

    LD low_result
    CMP low_expected
    BNE fail
    LD high_result
    CMP high_expected
    BNE fail
    OUT_CSTR ok
    HLT

fail:
    OUT_CSTR err
    HLT

.section data
.org 0
low_a:
    .word 5
low_b:
    .word 6
high_a:
    .word 1
high_b:
    .word 2
low_result:
    .word 0
high_result:
    .word 0
low_expected:
    .word 11
high_expected:
    .word 3
ok:
    .cstr "OK64"
err:
    .cstr "ERR64"
