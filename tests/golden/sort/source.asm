.const NEWLINE 10

.section text
.org 0
_start:
    LD arr_base
    ST p_write
    LD zero
    ST count

read_loop:
    IN 0
    CMP_IMM NEWLINE
    BEQ read_done
    ST_IND p_write
    LD p_write
    INC
    ST p_write
    LD count
    INC
    ST count
    JMP read_loop

read_done:
    LD count
    CMP one
    BLT print_done
    BEQ print_loop_init

    LD count
    DEC
    ST outer_left

outer_loop:
    LD outer_left
    CMP zero
    BEQ print_loop_init

    LD arr_base
    ST p_a
    LD arr_base
    INC
    ST p_b
    LD outer_left
    ST inner_left

inner_loop:
    LD inner_left
    CMP zero
    BEQ outer_step

    LD_IND p_a
    ST a_val
    LD_IND p_b
    ST b_val

    LD a_val
    CMP b_val
    BGT do_swap
    JMP no_swap

do_swap:
    LD b_val
    ST_IND p_a
    LD a_val
    ST_IND p_b

no_swap:
    LD p_a
    INC
    ST p_a
    LD p_b
    INC
    ST p_b
    LD inner_left
    DEC
    ST inner_left
    JMP inner_loop

outer_step:
    LD outer_left
    DEC
    ST outer_left
    JMP outer_loop

print_loop_init:
    LD arr_base
    ST p_print
    LD count
    ST print_left

print_loop:
    LD print_left
    CMP zero
    BEQ print_done
    LD_IND p_print
    OUT 0
    LD p_print
    INC
    ST p_print
    LD print_left
    DEC
    ST print_left
    JMP print_loop

print_done:
    HLT

.section data
.org 0
zero:        .word 0
one:         .word 1
arr_base:    .word 32
count:       .word 0
outer_left:  .word 0
inner_left:  .word 0
print_left:  .word 0
p_write:     .word 0
p_a:         .word 0
p_b:         .word 0
p_print:     .word 0
a_val:       .word 0
b_val:       .word 0

.org 32
arr:
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
    .word 0
