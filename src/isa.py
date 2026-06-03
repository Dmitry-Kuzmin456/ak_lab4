from dataclasses import dataclass
from enum import Enum


class OpCode(Enum):
    """
    Список инструкций
    """

    HLT = 0x1  # останов
    CLA = 0x2  # очистить аккумулятор
    NOP = 0x3  # нет операции
    LD = 0x4  # загрузка операнда в аккумулятор из памяти(прямая адресация)
    LD_IND = 0x5  # загрузка операнда в аккумулятор из памяти(косвенная адресация)
    LD_IMM = 0x6  # загрузка операнда в аккумулятор из памяти(прямая загрузка)
    ST = 0x7  # загрузка операнда в память из аккумулятора(прямая адресация)
    ST_IND = 0x8  # загрузка операнда в память из аккумулятора(косвенная адресация)
    ADD = 0xA  # сложение с прямой адресацией
    ADD_IND = 0xB  # сложение с косвенной адресацией
    ADD_IMM = 0xC  # сложение с прямой загрузкой операнда
    SUB = 0xD  # вычитание с прямой адресацией
    SUB_IND = 0xE  # вычитание с косвенной адресацией
    SUB_IMM = 0xF  # вычитание с прямой загрузкой операнда
    INC = 0x10  # Инкремент аккумулятора
    DEC = 0x11  # Декремент аккумулятора
    BEQ = 0x12  # Переход если Z = 1
    BNE = 0x13  # Переход если Z = 0
    BLT = 0x14  # Переход если N = 1
    BGT = 0x15  # Переход если N = 0 && Z = 0
    JMP = 0x16  # Безусловный переход
    CMP = 0x17  # Выставление флагов операции вычитания (прямая адресация)
    CMP_IND = 0x18  # Выставление флагов операции вычитания (косвенная адресация)
    CMP_IMM = 0x19  # Выставление флагов операции вычитания (прямая загрузка)
    IN = 0x1A  # Ввод с ВУ
    OUT = 0x1B  # Вывод на ВУ
    OUT_CSTR = 0x1C  # Вывод C-строки из памяти данных
    MUL = 0x1D  # Умножение с прямой адресацией
    DIV = 0x1E  # Целочисленное деление с прямой адресацией
    MOD = 0x1F  # Остаток от деления с прямой адресацией


class Src(Enum):
    """
    Список источников
    """

    NONE = 0x0
    AC = 0x1
    IP = 0x2
    AR = 0x3
    DR = 0x4
    CR = 0x5
    BR = 0x6
    PS = 0x7
    CR_IMM = 0x8  # для загрузки значения из памяти команд по IP


class Dst(Enum):
    """
    Список мест для записи результата
    """

    NONE = 0x0
    AC = 0x1
    IP = 0x2
    AR = 0x3
    DR = 0x4
    CR = 0x5
    BR = 0x6
    PS = 0x7
    AR_H = 0x8  # Для записи старших бит из памяти команд
    AR_L = 0x9  # Для записи младших бит из памяти команд


class AluOp(Enum):
    """
    Список операций с АЛУ
    """

    NONE = 0x0
    ADD = 0x1
    SUB = 0x2
    MUL = 0x3
    DIV = 0x4
    INC = 0x5
    REV = 0x6
    DEC = 0x7
    CMP = 0x8
    PASS = 0x9
    MOD = 0xA


class IOOp(Enum):
    """
    Список операций ввода/вывода
    """

    NONE = 0x0
    IN = 0x1
    OUT = 0x2


class MemOp(Enum):
    """
    Список поддерживаемых операций с памятью
    """

    NONE = 0x0
    READ_CMD = 0x1  # Читать из памяти команд (по IP)
    READ_DATA = 0x2  # Читать из памяти данных (по AR)
    WRITE_DATA = 0x3  # Писать в память данных (по AR)


class Move(Enum):
    """
    Список способов изменения uIP
    """

    NEXT = 0x1
    FETCH = 0x2
    DISPATCH_ADDR = 0x3  # Переход к блоку выбора адреса
    DISPATCH_OP = 0x4  # Переход к блоку выполнения команды
    HLT = 0x7
    CSTR_LOOP_OR_FETCH = 0x8


INSTR_WITH_OPERAND = {
    OpCode.LD,
    OpCode.LD_IND,
    OpCode.LD_IMM,
    OpCode.ST,
    OpCode.ST_IND,
    OpCode.ADD,
    OpCode.ADD_IND,
    OpCode.ADD_IMM,
    OpCode.MUL,
    OpCode.DIV,
    OpCode.MOD,
    OpCode.SUB,
    OpCode.SUB_IND,
    OpCode.SUB_IMM,
    OpCode.BEQ,
    OpCode.BNE,
    OpCode.BLT,
    OpCode.BGT,
    OpCode.JMP,
    OpCode.CMP,
    OpCode.CMP_IND,
    OpCode.CMP_IMM,
    OpCode.IN,
    OpCode.OUT,
    OpCode.OUT_CSTR,
}

IMM_ONEBYTE = {
    OpCode.LD_IMM,
    OpCode.ADD_IMM,
    OpCode.SUB_IMM,
    OpCode.CMP_IMM,
}


@dataclass
class DecodedInstruction:
    ip: int
    op: OpCode
    operand: int | None
    size: int


def instruction_size(op: OpCode) -> int:
    if op in IMM_ONEBYTE:
        return 2
    if op in INSTR_WITH_OPERAND:
        return 3
    return 1


def encode_instruction(op: OpCode, operand: int | None = None) -> list[int]:
    if op not in INSTR_WITH_OPERAND:
        return [op.value]
    if operand is None:
        raise ValueError(f"Missing operand for {op.name}")
    if op in IMM_ONEBYTE:
        return [op.value, operand & 0xFF]
    return [op.value, (operand >> 8) & 0xFF, operand & 0xFF]


def instruction_hex(op: OpCode, operand: int | None = None) -> str:
    return "".join(f"{byte:02X}" for byte in encode_instruction(op, operand))


def decode_instruction(command_memory: list[int], ip: int) -> DecodedInstruction:
    op = OpCode(command_memory[ip])
    if op not in INSTR_WITH_OPERAND:
        return DecodedInstruction(ip, op, None, 1)
    if op in IMM_ONEBYTE:
        return DecodedInstruction(ip, op, command_memory[ip + 1], 2)
    operand = (command_memory[ip + 1] << 8) | command_memory[ip + 2]
    return DecodedInstruction(ip, op, operand, 3)
