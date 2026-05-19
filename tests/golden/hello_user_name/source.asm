.const NEWLINE 10

.section text
.org 0
_start:
    OUT_CSTR question
    OUT_CSTR hello

read_loop:
    IN 0
    CMP_IMM NEWLINE
    BEQ done_read
    OUT 0
    JMP read_loop

done_read:
    OUT_CSTR suffix
    HLT

.section data
.org 0
question:
    .cstr "What is your name?"
hello:
    .cstr "Hello, "
suffix:
    .cstr "!"
