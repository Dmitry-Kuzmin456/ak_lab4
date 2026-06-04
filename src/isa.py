from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum, IntEnum


class OpCode(Enum):
    HLT = 0x01
    NOP = 0x02
    MOV = 0x03
    ADD = 0x04
    SUB = 0x05
    INC = 0x06
    DEC = 0x07
    CMP = 0x08
    BEQ = 0x09
    BNE = 0x0A
    BLT = 0x0B
    BGT = 0x0C
    JMP = 0x0D
    IN = 0x0E
    OUT = 0x0F
    OUT_CSTR = 0x10
    MUL = 0x11
    DIV = 0x12
    MOD = 0x13
    POLY = 0x14


class OperandKind(Enum):
    NONE = 0x0
    DATA_REG = 0x1
    ADDR_REG = 0x2
    DIRECT = 0x3
    INDIRECT = 0x4
    IMMEDIATE = 0x5
    PORT = 0x6
    CODE_ADDR = 0x7
    DATA_ADDR = 0x8
    SPECIAL_REG = 0x9


@dataclass(frozen=True)
class Operand:
    kind: OperandKind
    value: int = 0
    text: str = ""


@dataclass(frozen=True)
class DecodedInstruction:
    ip: int
    op: OpCode
    operands: list[Operand]
    size: int


DATA_REGISTERS = {"R1": 0, "R2": 1, "R3": 2}
ADDR_REGISTERS = {"A1": 0, "A2": 1, "A3": 2}
SPECIAL_REGISTERS = {"ZERO": 0}

OPERAND_COUNT = {
    OpCode.HLT: 0,
    OpCode.NOP: 0,
    OpCode.MOV: 2,
    OpCode.ADD: 2,
    OpCode.SUB: 2,
    OpCode.INC: 1,
    OpCode.DEC: 1,
    OpCode.CMP: 2,
    OpCode.BEQ: 1,
    OpCode.BNE: 1,
    OpCode.BLT: 1,
    OpCode.BGT: 1,
    OpCode.JMP: 1,
    OpCode.IN: 2,
    OpCode.OUT: 2,
    OpCode.OUT_CSTR: 1,
    OpCode.MUL: 2,
    OpCode.DIV: 2,
    OpCode.MOD: 2,
    OpCode.POLY: None,
}


def encode_operand(operand: Operand) -> list[int]:
    if operand.kind == OperandKind.IMMEDIATE:
        return [operand.kind.value, *struct.pack(">h", operand.value)]
    if operand.kind in {
        OperandKind.DATA_REG,
        OperandKind.ADDR_REG,
        OperandKind.DIRECT,
        OperandKind.INDIRECT,
        OperandKind.PORT,
        OperandKind.CODE_ADDR,
        OperandKind.DATA_ADDR,
        OperandKind.SPECIAL_REG,
    }:
        return [operand.kind.value, (operand.value >> 8) & 0xFF, operand.value & 0xFF]
    raise ValueError(f"Unsupported operand kind: {operand.kind}")


def encode_instruction(op: OpCode, operands: list[Operand] | None = None) -> list[int]:
    operands = operands or []
    expected = OPERAND_COUNT[op]
    if expected is None:
        if op == OpCode.POLY and len(operands) < 3:
            raise ValueError("POLY expects at least 3 operands")
    elif len(operands) != expected:
        raise ValueError(f"{op.name} expects {expected} operands, got {len(operands)}")
    if len(operands) > 255:
        raise ValueError("Instruction cannot have more than 255 operands")
    encoded = [op.value]
    if expected is None:
        encoded.append(len(operands))
    for operand in operands:
        encoded.extend(encode_operand(operand))
    return encoded


def instruction_size(op: OpCode, operands: list[Operand] | None = None) -> int:
    return len(encode_instruction(op, operands or []))


def instruction_hex(op: OpCode, operands: list[Operand] | None = None) -> str:
    return "".join(f"{byte:02X}" for byte in encode_instruction(op, operands))


def _decode_operand(command_memory: list[int], ip: int) -> tuple[Operand, int]:
    kind = OperandKind(command_memory[ip])
    pos = ip + 1
    if kind == OperandKind.IMMEDIATE:
        value = struct.unpack(">h", bytes(command_memory[pos : pos + 2]))[0]
        pos += 2
    elif kind in {
        OperandKind.DATA_REG,
        OperandKind.ADDR_REG,
        OperandKind.DIRECT,
        OperandKind.INDIRECT,
        OperandKind.PORT,
        OperandKind.CODE_ADDR,
        OperandKind.DATA_ADDR,
        OperandKind.SPECIAL_REG,
    }:
        value = (command_memory[pos] << 8) | command_memory[pos + 1]
        pos += 2
    else:
        raise ValueError(f"Bad operand kind: {kind}")
    return Operand(kind, value), pos


def decode_instruction(command_memory: list[int], ip: int) -> DecodedInstruction:
    op = OpCode(command_memory[ip])
    expected = OPERAND_COUNT[op]
    if expected is None:
        argc = command_memory[ip + 1]
        if op == OpCode.POLY and argc < 3:
            raise ValueError("POLY expects at least 3 operands")
        pos = ip + 2
    else:
        argc = expected
        pos = ip + 1
    operands = []
    for _ in range(argc):
        operand, pos = _decode_operand(command_memory, pos)
        operands.append(operand)
    return DecodedInstruction(ip, op, operands, pos - ip)


class Src(Enum):
    NONE = 0x0
    IP = 0x1
    CR = 0x2
    PS = 0x3
    DST_VALUE = 0x4
    SRC_VALUE = 0x5
    ALU_RESULT = 0x6


class Dst(Enum):
    NONE = 0x0
    IP = 0x1
    CR = 0x2
    PS = 0x3
    DST_OPERAND = 0x4
    SRC_LATCH = 0x5
    DST_LATCH = 0x6


class AluOp(Enum):
    NONE = 0x0
    ADD = 0x1
    SUB = 0x2
    MUL = 0x3
    DIV = 0x4
    MOD = 0x5
    INC = 0x6
    DEC = 0x7
    PASS = 0x8


class MemOp(Enum):
    NONE = 0x0


class Move(Enum):
    NEXT = 0x1
    FETCH = 0x2
    DISPATCH_OP = 0x3
    HLT = 0x4
    BRANCH = 0x5
    IN = 0x6
    OUT = 0x7
    CSTR_LOOP_OR_FETCH = 0x8
    POLY_START = 0x9
    POLY_STEP = 0xA
    PREPARE_OR_DISPATCH = 0xB


class MicroOp(Enum):
    NOP = "NOP"
    FETCH = "FETCH"
    PREPARE_OPERAND = "PREPARE_OPERAND"
    LOAD_SRC = "LOAD_SRC"
    LOAD_DST = "LOAD_DST"
    STORE_DST = "STORE_DST"
    ALU = "ALU"


class McSrc(Enum):
    NONE = "NONE"
    SRC_LATCH = "SRC_LATCH"
    DST_LATCH = "DST_LATCH"
    ZERO = "ZERO"


class McDst(Enum):
    NONE = "NONE"
    ALU_LATCH = "ALU_LATCH"


@dataclass(frozen=True)
class MicroCommand:
    op: MicroOp = MicroOp.NOP
    alu: AluOp = AluOp.NONE
    move: Move = Move.NEXT
    left: McSrc = McSrc.NONE
    right: McSrc = McSrc.NONE
    dst: McDst = McDst.NONE
    write_flags: bool = False


class MicroProgramStart(IntEnum):
    FETCH = 0
    PREPARE_OPERAND = 1
    HLT = 2
    NOP = 3
    MOV = 4
    ADD = 7
    SUB = 11
    MUL = 15
    DIV = 19
    MOD = 23
    INC = 27
    DEC = 30
    CMP = 33
    BEQ = 36
    BNE = 37
    BLT = 38
    BGT = 39
    JMP = 40
    IN = 41
    OUT = 42
    OUT_CSTR = 43
    POLY = 44


EXEC_MAP = {
    OpCode.HLT: MicroProgramStart.HLT,
    OpCode.NOP: MicroProgramStart.NOP,
    OpCode.MOV: MicroProgramStart.MOV,
    OpCode.ADD: MicroProgramStart.ADD,
    OpCode.SUB: MicroProgramStart.SUB,
    OpCode.MUL: MicroProgramStart.MUL,
    OpCode.DIV: MicroProgramStart.DIV,
    OpCode.MOD: MicroProgramStart.MOD,
    OpCode.INC: MicroProgramStart.INC,
    OpCode.DEC: MicroProgramStart.DEC,
    OpCode.CMP: MicroProgramStart.CMP,
    OpCode.BEQ: MicroProgramStart.BEQ,
    OpCode.BNE: MicroProgramStart.BNE,
    OpCode.BLT: MicroProgramStart.BLT,
    OpCode.BGT: MicroProgramStart.BGT,
    OpCode.JMP: MicroProgramStart.JMP,
    OpCode.IN: MicroProgramStart.IN,
    OpCode.OUT: MicroProgramStart.OUT,
    OpCode.OUT_CSTR: MicroProgramStart.OUT_CSTR,
    OpCode.POLY: MicroProgramStart.POLY,
}
