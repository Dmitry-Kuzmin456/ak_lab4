.section data
zero: .word 0
ten: .word 10
eleven: .word 11
min_factor: .word 100
max_i: .word 999
max_j: .word 990
div10: .word 10
div100: .word 100
div1000: .word 1000
div10000: .word 10000
div100000: .word 100000
ascii_zero: .word 48
i: .word 0
j: .word 0
product: .word 0
best: .word 0
candidate: .word 0
reversed: .word 0
digit: .word 0
print_value: .word 0

.section text
_start:
    LD max_i
    ST i
    LD zero
    ST best

outer_loop:
    LD i
    CMP min_factor
    BLT print_result

    LD max_j
    ST j

inner_loop:
    LD j
    CMP min_factor
    BLT dec_i

    LD i
    MUL j
    ST product

    LD product
    CMP best
    BGT check_palindrome
    JMP dec_i

check_palindrome:
    LD product
    ST candidate
    LD zero
    ST reversed

pal_loop:
    LD candidate
    CMP zero
    BEQ pal_done

    LD candidate
    MOD ten
    ST digit

    LD reversed
    MUL ten
    ADD digit
    ST reversed

    LD candidate
    DIV ten
    ST candidate

    JMP pal_loop

pal_done:
    LD reversed
    CMP product
    BEQ update_best
    JMP dec_j

update_best:
    LD product
    ST best

dec_j:
    LD j
    SUB eleven
    ST j
    JMP inner_loop

dec_i:
    LD i
    DEC
    ST i
    JMP outer_loop

print_result:
    LD best
    ST print_value

    LD print_value
    DIV div100000
    ADD ascii_zero
    OUT 0
    LD print_value
    MOD div100000
    ST print_value

    LD print_value
    DIV div10000
    ADD ascii_zero
    OUT 0
    LD print_value
    MOD div10000
    ST print_value

    LD print_value
    DIV div1000
    ADD ascii_zero
    OUT 0
    LD print_value
    MOD div1000
    ST print_value

    LD print_value
    DIV div100
    ADD ascii_zero
    OUT 0
    LD print_value
    MOD div100
    ST print_value

    LD print_value
    DIV div10
    ADD ascii_zero
    OUT 0
    LD print_value
    MOD div10
    ADD ascii_zero
    OUT 0

    HLT
