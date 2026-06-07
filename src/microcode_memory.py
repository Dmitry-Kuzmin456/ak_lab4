# ruff: noqa: F403, F405
from src.isa import *


def mi(*signals: Signal) -> list[Signal]:
    return list(signals)


# fmt: off
microcode_memory = [
    # Common fetch/decode path.
    mi(LatchFetch(), LatchMpc(MpcSel.FETCH_SRC_OR_DISPATCH)),
    mi(LatchSrcPayload(), LatchMpc(MpcSel.FETCH_DST_OR_PREPARE)),
    mi(LatchDstPayload(), LatchMpc(MpcSel.PREPARE_OR_DISPATCH)),

    # Effective address preparation, driven by operand decoder and EA mux.
    mi(LatchEa(EaSource.OPERAND_PAYLOAD), LatchMpc(MpcSel.PREPARE_OR_DISPATCH)),
    mi(LatchEa(EaSource.ADDRESS_REG), LatchMpc(MpcSel.PREPARE_OR_DISPATCH)),
    mi(LatchShadowA0(), LatchEa(EaSource.ADDRESS_REG), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.INC, left=McSrc.SHADOW_A0, dst=McDst.ADDRESS_REG, dst_slot=OperandSlot.PREVIOUS), LatchMpc(MpcSel.PREPARE_OR_DISPATCH)),
    mi(LatchShadowA0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.DEC, left=McSrc.SHADOW_A0, dst=McDst.ADDRESS_REG), LatchMpc(MpcSel.NEXT)),
    mi(LatchEa(EaSource.ADDRESS_REG), LatchMpc(MpcSel.PREPARE_OR_DISPATCH)),

    # CSTR A?, "text": command byte -> OP1 -> shadow_r2 -> data[A?], A?++, until zero terminator.
    mi(LatchCstrAddressRegister(), LatchMpc(MpcSel.NEXT)),
    mi(LatchCstrChar(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(OperandSlot.OP1), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.PASS, left=McSrc.SHADOW_R0, dst=McDst.SHADOW_R2, write_flags=False), LatchMpc(MpcSel.NEXT)),
    mi(WriteCstrChar(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowA0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.INC, left=McSrc.SHADOW_A0, dst=McDst.ADDRESS_REG), LatchMpc(MpcSel.CSTR_DONE_OR_NEXT_CHAR)),

    # HLT / NOP
    mi(HaltSignal()),
    mi(LatchMpc(MpcSel.ZERO)),

    # MOV src, dst: src -> dst through ALU PASS, no flags.
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.PASS, left=McSrc.SHADOW_R0, dst=McDst.DST_OR_SHADOW_R2, write_flags=False), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # ADD src, dst: dst + src -> dst.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.ADD, left=McSrc.SHADOW_R1, right=McSrc.SHADOW_R0, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # SUB src, dst: dst - src -> dst.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.SUB, left=McSrc.SHADOW_R1, right=McSrc.SHADOW_R0, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # MUL src, dst: dst * src -> dst.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.MUL, left=McSrc.SHADOW_R1, right=McSrc.SHADOW_R0, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # DIV src, dst: dst / src -> dst.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.DIV, left=McSrc.SHADOW_R1, right=McSrc.SHADOW_R0, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # MOD src, dst: dst % src -> dst.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.MOD, left=McSrc.SHADOW_R1, right=McSrc.SHADOW_R0, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # NEG dst: dst <- -dst.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.NEG, left=McSrc.SHADOW_R1, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # OR src, dst: dst <- dst | src.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.OR, left=McSrc.SHADOW_R1, right=McSrc.SHADOW_R0, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # AND src, dst: dst <- dst & src.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.AND, left=McSrc.SHADOW_R1, right=McSrc.SHADOW_R0, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # INC dst
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.INC, left=McSrc.SHADOW_R1, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # DEC dst
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.DEC, left=McSrc.SHADOW_R1, dst=McDst.DST_OR_SHADOW_R2, write_flags=True), LatchMpc(MpcSel.STORE_DST_IF_MEMORY)),

    # CMP src, dst: set flags for dst - src.
    mi(LatchShadowR1(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.SUB, left=McSrc.SHADOW_R1, right=McSrc.SHADOW_R0, write_flags=True), LatchMpc(MpcSel.ZERO)),

    # Shared memory write-back for arithmetic operations whose dst is memory.
    mi(WriteDst(WriteSource.SHADOW_R2), LatchMpc(MpcSel.ZERO)),

    # Branches, IN/OUT and complex CISC instructions.
    mi(BranchSignal(), LatchMpc(MpcSel.ZERO)),
    mi(BranchSignal(), LatchMpc(MpcSel.ZERO)),
    mi(BranchSignal(), LatchMpc(MpcSel.ZERO)),
    mi(BranchSignal(), LatchMpc(MpcSel.ZERO)),
    mi(BranchSignal(), LatchMpc(MpcSel.ZERO)),
    mi(InputSignal(), LatchMpc(MpcSel.ZERO)),
    mi(OutputSignal(), LatchMpc(MpcSel.ZERO)),

    # OUT_CSTR: read data[EA0], output non-zero char, EA0++, repeat.
    mi(LatchShadowR0FromDataMemory(), LatchMpc(MpcSel.CSTR_LOOP_OR_FETCH)),
    mi(OutputShadowR0(), LatchMpc(MpcSel.NEXT)),
    mi(LatchShadowA0FromEa(), LatchMpc(MpcSel.NEXT)),
    mi(AluSignal(AluOp.INC, left=McSrc.SHADOW_A0, dst=McDst.SHADOW_R2), LatchMpc(MpcSel.NEXT)),
    mi(LatchEaFromShadowR2(), LatchMpc(MpcSel.OPCODE)),
]

assert len(microcode_memory) == MicroProgramStart.OUT_CSTR_END + 1
# fmt: on
