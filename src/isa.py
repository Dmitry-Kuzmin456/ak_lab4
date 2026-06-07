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
    CSTR = 0x14
    NEG = 0x15
    OR = 0x16
    AND = 0x17


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
    POST_INC = 0xA
    PRE_DEC = 0xB


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


DATA_REGISTERS = {"R1": 1, "R2": 2, "R3": 3}
ADDR_REGISTERS = {"A1": 1, "A2": 2, "A3": 3}
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
    OpCode.CSTR: None,
    OpCode.NEG: 1,
    OpCode.OR: 2,
    OpCode.AND: 2,
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
        OperandKind.POST_INC,
        OperandKind.PRE_DEC,
    }:
        return [operand.kind.value, (operand.value >> 8) & 0xFF, operand.value & 0xFF]
    raise ValueError(f"Unsupported operand kind: {operand.kind}")


def _encode_operand_payload(operand: Operand) -> list[int]:
    if operand.kind == OperandKind.IMMEDIATE:
        return list(struct.pack(">h", operand.value))
    if operand.kind in {
        OperandKind.DATA_REG,
        OperandKind.ADDR_REG,
        OperandKind.DIRECT,
        OperandKind.INDIRECT,
        OperandKind.PORT,
        OperandKind.CODE_ADDR,
        OperandKind.DATA_ADDR,
        OperandKind.SPECIAL_REG,
        OperandKind.POST_INC,
        OperandKind.PRE_DEC,
    }:
        return [(operand.value >> 8) & 0xFF, operand.value & 0xFF]
    raise ValueError(f"Unsupported operand kind: {operand.kind}")


def encode_instruction(op: OpCode, operands: list[Operand] | None = None) -> list[int]:
    operands = operands or []
    expected = OPERAND_COUNT[op]
    if expected is None:
        if op == OpCode.CSTR:
            if not operands or operands[0].kind != OperandKind.ADDR_REG:
                raise ValueError("CSTR expects address register and string")
        else:
            raise ValueError(f"Bad operand count for opcode: {op}")
    elif len(operands) != expected:
        raise ValueError(f"{op.name} expects {expected} operands, got {len(operands)}")
    if len(operands) > 255:
        raise ValueError("Instruction cannot have more than 255 operands")
    encoded = [op.value]
    if expected is None:
        encoded.append(operands[0].value & 0xFF)
        for operand in operands[1:]:
            encoded.append(operand.value & 0xFF)
        encoded.append(0)
        return encoded
    if expected == 0:
        return encoded

    kinds = operands[0].kind.value << 4
    if expected == 2:
        kinds |= operands[1].kind.value
    encoded.append(kinds)
    encoded.extend(_encode_operand_payload(operands[0]))
    if expected == 2:
        encoded.extend(_encode_operand_payload(operands[1]))
    return encoded


def instruction_hex(op: OpCode, operands: list[Operand] | None = None) -> str:
    return "".join(f"{byte:02X}" for byte in encode_instruction(op, operands))


def decode_operand_payload(kind: OperandKind, payload: int) -> Operand:
    if kind == OperandKind.IMMEDIATE and payload >= 0x8000:
        payload -= 0x10000
    return Operand(kind, payload)


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
    NEG = 0x9
    OR = 0xA
    AND = 0xB


class McSrc(IntEnum):
    NONE = 0x0
    SHADOW_R0 = 0x1
    SHADOW_R1 = 0x2
    SHADOW_A0 = 0x3
    SHADOW_R2 = 0x4


class McDst(IntEnum):
    NONE = 0x0
    SHADOW_R2 = 0x1
    DST_OR_SHADOW_R2 = 0x2
    SHADOW_R0 = 0x3
    SHADOW_R1 = 0x4
    SHADOW_A0 = 0x5
    ADDRESS_REG = 0x6


class OperandSlot(Enum):
    SRC = "SRC"
    DST = "DST"
    OP1 = "OP1"
    CURRENT = "CURRENT"
    PREVIOUS = "PREVIOUS"


class EaSource(Enum):
    OPERAND_PAYLOAD = "OPERAND_PAYLOAD"
    ADDRESS_REG = "ADDRESS_REG"


class WriteSource(Enum):
    SHADOW_R2 = "SHADOW_R2"


class MpcSel(Enum):
    ZERO = "ZERO"
    NEXT = "NEXT"
    OPCODE = "OPCODE"
    FETCH_SRC_OR_DISPATCH = "FETCH_SRC_OR_DISPATCH"
    FETCH_DST_OR_PREPARE = "FETCH_DST_OR_PREPARE"
    PREPARE_OR_DISPATCH = "PREPARE_OR_DISPATCH"
    STORE_DST_IF_MEMORY = "STORE_DST_IF_MEMORY"
    CSTR_LOOP_OR_FETCH = "CSTR_LOOP_OR_FETCH"
    CSTR_DONE_OR_NEXT_CHAR = "CSTR_DONE_OR_NEXT_CHAR"


@dataclass(frozen=True)
class Signal:
    pass


@dataclass(frozen=True)
class LatchFetch(Signal):
    pass


@dataclass(frozen=True)
class LatchSrcPayload(Signal):
    pass


@dataclass(frozen=True)
class LatchDstPayload(Signal):
    pass


@dataclass(frozen=True)
class LatchCstrAddressRegister(Signal):
    pass


@dataclass(frozen=True)
class LatchCstrChar(Signal):
    pass


@dataclass(frozen=True)
class LatchEa(Signal):
    source: EaSource


@dataclass(frozen=True)
class LatchShadowA0(Signal):
    pass


@dataclass(frozen=True)
class LatchShadowR0(Signal):
    slot: OperandSlot = OperandSlot.SRC


@dataclass(frozen=True)
class LatchShadowR1(Signal):
    slot: OperandSlot = OperandSlot.DST


@dataclass(frozen=True)
class WriteDst(Signal):
    source: WriteSource


@dataclass(frozen=True)
class AluSignal(Signal):
    alu: AluOp
    left: McSrc = McSrc.NONE
    right: McSrc = McSrc.NONE
    dst: McDst = McDst.NONE
    dst_slot: OperandSlot = OperandSlot.CURRENT
    write_flags: bool = False


@dataclass(frozen=True)
class BranchSignal(Signal):
    pass


@dataclass(frozen=True)
class InputSignal(Signal):
    pass


@dataclass(frozen=True)
class OutputSignal(Signal):
    pass


@dataclass(frozen=True)
class LatchShadowR0FromDataMemory(Signal):
    ea_index: int = 0


@dataclass(frozen=True)
class OutputShadowR0(Signal):
    pass


@dataclass(frozen=True)
class LatchShadowA0FromEa(Signal):
    ea_index: int = 0


@dataclass(frozen=True)
class LatchEaFromShadowR2(Signal):
    ea_index: int = 0


@dataclass(frozen=True)
class WriteCstrChar(Signal):
    pass


@dataclass(frozen=True)
class HaltSignal(Signal):
    pass


@dataclass(frozen=True)
class LatchMpc(Signal):
    select: MpcSel


class MicroProgramStart(IntEnum):
    FETCH = 0x00
    FETCH_SRC_PAYLOAD = 0x01
    FETCH_DST_PAYLOAD = 0x02
    PREPARE_DIRECT = 0x03
    PREPARE_INDIRECT = 0x04
    PREPARE_POST_INC = 0x05
    PREPARE_PRE_DEC = 0x07
    FETCH_CSTR_ADDRESS_REGISTER = 0x0A
    CSTR_READ_CHAR = 0x0B
    CSTR_LATCH_CHAR = 0x0C
    CSTR_PASS_CHAR = 0x0D
    CSTR_WRITE_CHAR = 0x0E
    CSTR_LATCH_ADDRESS = 0x0F
    CSTR_INCREMENT_ADDRESS = 0x10
    HLT = 0x11
    NOP = 0x12
    MOV = 0x13
    ADD = 0x15
    SUB = 0x18
    MUL = 0x1B
    DIV = 0x1E
    MOD = 0x21
    NEG = 0x24
    OR = 0x26
    AND = 0x29
    INC = 0x2C
    DEC = 0x2E
    CMP = 0x30
    STORE_DST = 0x33
    BEQ = 0x34
    BNE = 0x35
    BLT = 0x36
    BGT = 0x37
    JMP = 0x38
    IN = 0x39
    OUT = 0x3A
    OUT_CSTR = 0x3B
    OUT_CSTR_END = 0x3F


EXEC_MAP = {
    OpCode.HLT: MicroProgramStart.HLT,
    OpCode.NOP: MicroProgramStart.NOP,
    OpCode.MOV: MicroProgramStart.MOV,
    OpCode.ADD: MicroProgramStart.ADD,
    OpCode.SUB: MicroProgramStart.SUB,
    OpCode.MUL: MicroProgramStart.MUL,
    OpCode.DIV: MicroProgramStart.DIV,
    OpCode.MOD: MicroProgramStart.MOD,
    OpCode.NEG: MicroProgramStart.NEG,
    OpCode.OR: MicroProgramStart.OR,
    OpCode.AND: MicroProgramStart.AND,
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
    OpCode.CSTR: MicroProgramStart.FETCH_CSTR_ADDRESS_REGISTER,
}
