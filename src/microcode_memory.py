from src.isa import Src, Dst, AluOp, MemOp, Move


def mc(
    src: Src = Src.NONE,
    dst: Dst = Dst.NONE,
    alu: AluOp = AluOp.NONE,
    mem: MemOp = MemOp.NONE,
    move: Move = Move.NEXT,
    inc_ip: bool = False,
):
    return (
        (src.value << 0)
        | (dst.value << 4)
        | (alu.value << 8)
        | (mem.value << 12)
        | (move.value << 15)
        | (int(inc_ip) << 20)
    )


microcode_memory = [0] * 256

# ==========================================
# Выборка команды
microcode_memory[0] = mc(
    dst=Dst.CR, mem=MemOp.READ_CMD, inc_ip=True, move=Move.DISPATCH_ADDR
)  # Чтение кода команды в CR, инкремент IP и переход к выборке операнда/выполнению

# ==========================================
# Выборка адреса

# Прямая адресация
microcode_memory[2] = mc(
    mem=MemOp.READ_CMD, dst=Dst.AR_H, inc_ip=True
)  # Записываем старшие 8 бит адреса из памяти команд в AR и инкрементируем IP
microcode_memory[3] = mc(
    mem=MemOp.READ_CMD, dst=Dst.AR_L, inc_ip=True, move=Move.DISPATCH_OP
)  # Записываем младшие 8 бит адреса, инкрементируем IP и переходим к выполнению

# Прямая загрузка операнда
microcode_memory[6] = mc(
    src=Src.CR_IMM, dst=Dst.DR, mem=MemOp.READ_CMD, inc_ip=True, move=Move.DISPATCH_OP
)  # Запись immediate из памяти команд в DR, инкремент IP и переход к выполнению

# Косвенная адресация
microcode_memory[8] = mc(
    mem=MemOp.READ_CMD, dst=Dst.AR_H, inc_ip=True
)  # Записываем старшие 8 бит адреса из памяти команд в AR и инкрементируем IP
microcode_memory[9] = mc(
    mem=MemOp.READ_CMD, dst=Dst.AR_L, inc_ip=True
)  # Записываем младшие 8 бит адреса из памяти команд в AR и инкрементируем IP
microcode_memory[10] = mc(
    mem=MemOp.READ_DATA, dst=Dst.AR, move=Move.DISPATCH_OP
)  # Чтение эффективного адреса из памяти данных и переход к выполнению

# ==========================================
# Выполнение команды

# HLT
microcode_memory[13] = mc(move=Move.HLT)

# CLA
microcode_memory[14] = mc(alu=AluOp.PASS, src=Src.NONE, dst=Dst.AC, move=Move.FETCH)

# NOP
microcode_memory[15] = mc(move=Move.FETCH)

# Ld (Mem[AR] -> AC)
microcode_memory[16] = mc(
    mem=MemOp.READ_DATA, dst=Dst.AC, alu=AluOp.PASS, move=Move.FETCH
)

# Ld Imm (DR -> AC)
microcode_memory[17] = mc(src=Src.DR, dst=Dst.AC, alu=AluOp.PASS, move=Move.FETCH)

# ST (AC -> Mem[AR])
microcode_memory[18] = mc(src=Src.AC, dst=Dst.DR, move=Move.NEXT)
microcode_memory[19] = mc(mem=MemOp.WRITE_DATA, move=Move.FETCH)

# ADD_IM
microcode_memory[20] = mc(src=Src.DR, dst=Dst.BR)
microcode_memory[21] = mc(dst=Dst.AC, alu=AluOp.ADD, move=Move.FETCH)  # AC + BR -> AC

# ADD
microcode_memory[22] = mc(
    mem=MemOp.READ_DATA, dst=Dst.BR
)  # Перемещаем значение операнда в буферный регистр для сложения
microcode_memory[23] = mc(dst=Dst.AC, alu=AluOp.ADD, move=Move.FETCH)  # AC + BR -> AC

# SUB
microcode_memory[24] = mc(mem=MemOp.READ_DATA, dst=Dst.BR)
microcode_memory[25] = mc(dst=Dst.AC, alu=AluOp.SUB, move=Move.FETCH)

# SUB_IMM
microcode_memory[26] = mc(src=Src.DR, dst=Dst.BR)
microcode_memory[27] = mc(dst=Dst.AC, alu=AluOp.SUB, move=Move.FETCH)

# CMP
microcode_memory[28] = mc(mem=MemOp.READ_DATA, dst=Dst.BR)
microcode_memory[29] = mc(dst=Dst.NONE, alu=AluOp.SUB, move=Move.FETCH)

# CMP_IMM
microcode_memory[30] = mc(src=Src.DR, dst=Dst.BR)
microcode_memory[31] = mc(dst=Dst.NONE, alu=AluOp.SUB, move=Move.FETCH)

# INC
microcode_memory[32] = mc(src=Src.AC, dst=Dst.AC, alu=AluOp.INC, move=Move.FETCH)

# Dec
microcode_memory[33] = mc(src=Src.AC, dst=Dst.AC, alu=AluOp.DEC, move=Move.FETCH)

# JMP
microcode_memory[34] = mc(src=Src.AR, dst=Dst.IP, alu=AluOp.PASS, move=Move.FETCH)

# BEQ/BNE/BLT/BGT/IN/OUT обрабатываются в ControlUnit как специальные операции.
microcode_memory[35] = mc(move=Move.FETCH)
microcode_memory[36] = mc(move=Move.FETCH)
microcode_memory[37] = mc(move=Move.FETCH)
microcode_memory[38] = mc(move=Move.FETCH)
microcode_memory[39] = mc(move=Move.FETCH)
microcode_memory[40] = mc(move=Move.FETCH)

# OUT_CSTR: читаем символ из DataMem[AR], затем ControlUnit либо завершает команду
# на нулевом терминаторе, либо выводит символ и возвращается к чтению следующего.
microcode_memory[41] = mc(mem=MemOp.READ_DATA, dst=Dst.DR)
microcode_memory[42] = mc(move=Move.CSTR_LOOP_OR_FETCH)

# MUL
microcode_memory[43] = mc(mem=MemOp.READ_DATA, dst=Dst.BR)
microcode_memory[44] = mc(dst=Dst.AC, alu=AluOp.MUL, move=Move.FETCH)

# DIV
microcode_memory[45] = mc(mem=MemOp.READ_DATA, dst=Dst.BR)
microcode_memory[46] = mc(dst=Dst.AC, alu=AluOp.DIV, move=Move.FETCH)

# MOD
microcode_memory[47] = mc(mem=MemOp.READ_DATA, dst=Dst.BR)
microcode_memory[48] = mc(dst=Dst.AC, alu=AluOp.MOD, move=Move.FETCH)
