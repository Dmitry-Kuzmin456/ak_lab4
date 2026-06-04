from src.isa import (
    AluOp,
    McDst,
    McSrc,
    MicroCommand,
    MicroOp,
    MicroProgramStart,
    Move,
)


def mc(
    op: MicroOp = MicroOp.NOP,
    alu: AluOp = AluOp.NONE,
    move: Move = Move.NEXT,
    left: McSrc = McSrc.NONE,
    right: McSrc = McSrc.NONE,
    dst: McDst = McDst.NONE,
    write_flags: bool = False,
) -> MicroCommand:
    return MicroCommand(op, alu, move, left, right, dst, write_flags)


# fmt: off
microcode_memory = [
    # Fetch/decode instruction, then prepare effective operand addresses.
    mc(MicroOp.FETCH, move=Move.PREPARE_OR_DISPATCH),
    mc(MicroOp.PREPARE_OPERAND, move=Move.PREPARE_OR_DISPATCH),
    # HLT / NOP
    mc(move=Move.HLT),
    mc(move=Move.FETCH),
    # MOV src, dst: src -> dst, no flags.
    mc(MicroOp.LOAD_SRC),
    mc(MicroOp.ALU, AluOp.PASS, left=McSrc.SRC_LATCH, dst=McDst.ALU_LATCH),
    mc(MicroOp.STORE_DST, move=Move.FETCH),
    # ADD src, dst: dst + src -> dst.
    mc(MicroOp.LOAD_DST),
    mc(MicroOp.LOAD_SRC),
    mc(
        MicroOp.ALU,
        AluOp.ADD,
        left=McSrc.DST_LATCH,
        right=McSrc.SRC_LATCH,
        dst=McDst.ALU_LATCH,
        write_flags=True,
    ),
    mc(MicroOp.STORE_DST, move=Move.FETCH),
    # SUB src, dst: dst - src -> dst.
    mc(MicroOp.LOAD_DST),
    mc(MicroOp.LOAD_SRC),
    mc(
        MicroOp.ALU,
        AluOp.SUB,
        left=McSrc.DST_LATCH,
        right=McSrc.SRC_LATCH,
        dst=McDst.ALU_LATCH,
        write_flags=True,
    ),
    mc(MicroOp.STORE_DST, move=Move.FETCH),
    # MUL src, dst: dst * src -> dst.
    mc(MicroOp.LOAD_DST),
    mc(MicroOp.LOAD_SRC),
    mc(
        MicroOp.ALU,
        AluOp.MUL,
        left=McSrc.DST_LATCH,
        right=McSrc.SRC_LATCH,
        dst=McDst.ALU_LATCH,
        write_flags=True,
    ),
    mc(MicroOp.STORE_DST, move=Move.FETCH),
    # DIV src, dst: dst / src -> dst.
    mc(MicroOp.LOAD_DST),
    mc(MicroOp.LOAD_SRC),
    mc(
        MicroOp.ALU,
        AluOp.DIV,
        left=McSrc.DST_LATCH,
        right=McSrc.SRC_LATCH,
        dst=McDst.ALU_LATCH,
        write_flags=True,
    ),
    mc(MicroOp.STORE_DST, move=Move.FETCH),
    # MOD src, dst: dst % src -> dst.
    mc(MicroOp.LOAD_DST),
    mc(MicroOp.LOAD_SRC),
    mc(
        MicroOp.ALU,
        AluOp.MOD,
        left=McSrc.DST_LATCH,
        right=McSrc.SRC_LATCH,
        dst=McDst.ALU_LATCH,
        write_flags=True,
    ),
    mc(MicroOp.STORE_DST, move=Move.FETCH),
    # INC dst
    mc(MicroOp.LOAD_DST),
    mc(MicroOp.ALU, AluOp.INC, left=McSrc.DST_LATCH, dst=McDst.ALU_LATCH, write_flags=True),
    mc(MicroOp.STORE_DST, move=Move.FETCH),
    # DEC dst
    mc(MicroOp.LOAD_DST),
    mc(MicroOp.ALU, AluOp.DEC, left=McSrc.DST_LATCH, dst=McDst.ALU_LATCH, write_flags=True),
    mc(MicroOp.STORE_DST, move=Move.FETCH),
    # CMP src, dst: set flags for dst - src.
    mc(MicroOp.LOAD_DST),
    mc(MicroOp.LOAD_SRC),
    mc(
        MicroOp.ALU,
        AluOp.SUB,
        left=McSrc.DST_LATCH,
        right=McSrc.SRC_LATCH,
        write_flags=True,
        move=Move.FETCH,
    ),
    # Branches, IN/OUT and complex CISC instructions.
    mc(move=Move.BRANCH),
    mc(move=Move.BRANCH),
    mc(move=Move.BRANCH),
    mc(move=Move.BRANCH),
    mc(move=Move.BRANCH),
    mc(move=Move.IN),
    mc(move=Move.OUT),
    mc(move=Move.CSTR_LOOP_OR_FETCH),
    mc(move=Move.POLY_START),
    mc(move=Move.POLY_STEP),
]
# fmt: on

assert len(microcode_memory) == MicroProgramStart.POLY + 2
