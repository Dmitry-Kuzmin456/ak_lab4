from src.isa import AluOp, MicroCommand, MicroOp, MicroProgramStart, Move


def mc(
    op: MicroOp = MicroOp.NOP,
    alu: AluOp = AluOp.NONE,
    move: Move = Move.NEXT,
) -> MicroCommand:
    return MicroCommand(op, alu, move)


microcode_memory = [
    # Fetch/decode instruction and dispatch to execution microprogram.
    mc(MicroOp.FETCH, move=Move.DISPATCH_OP),
    # HLT / NOP
    mc(move=Move.HLT),
    mc(move=Move.FETCH),
    # MOV src, dst: src -> dst, no flags.
    mc(MicroOp.SELECT_SRC),
    mc(MicroOp.READ_SELECTED_TO_SRC),
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.WRITE_SRC_TO_SELECTED, move=Move.FETCH),
    # ADD src, dst: dst + src -> dst.
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.READ_SELECTED_TO_DST),
    mc(MicroOp.SELECT_SRC),
    mc(MicroOp.READ_SELECTED_TO_SRC),
    mc(MicroOp.ALU, AluOp.ADD),
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.WRITE_ALU_TO_SELECTED, move=Move.FETCH),
    # SUB src, dst: dst - src -> dst.
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.READ_SELECTED_TO_DST),
    mc(MicroOp.SELECT_SRC),
    mc(MicroOp.READ_SELECTED_TO_SRC),
    mc(MicroOp.ALU, AluOp.SUB),
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.WRITE_ALU_TO_SELECTED, move=Move.FETCH),
    # MUL src, dst: dst * src -> dst.
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.READ_SELECTED_TO_DST),
    mc(MicroOp.SELECT_SRC),
    mc(MicroOp.READ_SELECTED_TO_SRC),
    mc(MicroOp.ALU, AluOp.MUL),
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.WRITE_ALU_TO_SELECTED, move=Move.FETCH),
    # DIV src, dst: dst / src -> dst.
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.READ_SELECTED_TO_DST),
    mc(MicroOp.SELECT_SRC),
    mc(MicroOp.READ_SELECTED_TO_SRC),
    mc(MicroOp.ALU, AluOp.DIV),
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.WRITE_ALU_TO_SELECTED, move=Move.FETCH),
    # MOD src, dst: dst % src -> dst.
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.READ_SELECTED_TO_DST),
    mc(MicroOp.SELECT_SRC),
    mc(MicroOp.READ_SELECTED_TO_SRC),
    mc(MicroOp.ALU, AluOp.MOD),
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.WRITE_ALU_TO_SELECTED, move=Move.FETCH),
    # INC dst
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.READ_SELECTED_TO_DST),
    mc(MicroOp.ALU, AluOp.INC),
    mc(MicroOp.WRITE_ALU_TO_SELECTED, move=Move.FETCH),
    # DEC dst
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.READ_SELECTED_TO_DST),
    mc(MicroOp.ALU, AluOp.DEC),
    mc(MicroOp.WRITE_ALU_TO_SELECTED, move=Move.FETCH),
    # CMP src, dst: set flags for dst - src.
    mc(MicroOp.SELECT_DST),
    mc(MicroOp.READ_SELECTED_TO_DST),
    mc(MicroOp.SELECT_SRC),
    mc(MicroOp.READ_SELECTED_TO_SRC),
    mc(MicroOp.ALU, AluOp.SUB, move=Move.FETCH),
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

assert len(microcode_memory) == MicroProgramStart.POLY + 2
