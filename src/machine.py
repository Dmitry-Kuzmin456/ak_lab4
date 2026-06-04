import argparse
import struct

from src.isa import (
    EXEC_MAP,
    AluOp,
    MicroOp,
    Move,
    Operand,
    OperandKind,
    OpCode,
    decode_instruction,
)
from src.microcode_memory import microcode_memory


WORD_MASK = 0xFFFFFFFF
UNSIGNED_MAX = WORD_MASK
SIGNED_MIN = -0x80000000
SIGNED_MAX = 0x7FFFFFFF


def _to_signed32(value: int) -> int:
    value &= WORD_MASK
    if value > SIGNED_MAX:
        return value - 0x100000000
    return value


class DataPath:
    def __init__(self):
        self.command_memory: list[int] = [0] * 65536
        self.data_memory: list[int] = [0] * 65536

        self.r: list[int] = [0, 0, 0]  # R1-R3
        self.a: list[int] = [0, 0, 0]  # A1-A3
        self.ip: int = 0
        self.cr: int = 0
        self.ps: dict[str, bool] = {
            "N": False,
            "Z": False,
            "V": False,
            "C": False,
        }

        self.dst_latch: int = 0
        self.src_latch: int = 0
        self.alu_latch: int = 0
        self.src_desc: Operand | None = None
        self.dst_desc: Operand | None = None
        self.selected_operand: Operand | None = None

        self.input_buffer: list[int] = []
        self.output_buffer: list[int] = []

    def set_command_memory(self, command_memory: list[int]) -> None:
        self.command_memory = command_memory

    def set_data_memory(self, data_memory: list[int]) -> None:
        self.data_memory = data_memory

    def read_operand(self, operand: Operand) -> int:
        if operand.kind == OperandKind.DATA_REG:
            return self.r[operand.value]
        if operand.kind == OperandKind.ADDR_REG:
            return self.a[operand.value]
        if operand.kind == OperandKind.DIRECT:
            return self.data_memory[operand.value]
        if operand.kind == OperandKind.INDIRECT:
            return self.data_memory[self.a[operand.value]]
        if operand.kind == OperandKind.IMMEDIATE:
            return operand.value
        if operand.kind == OperandKind.SPECIAL_REG:
            return 0
        if operand.kind in {OperandKind.PORT, OperandKind.CODE_ADDR, OperandKind.DATA_ADDR}:
            return operand.value
        raise ValueError(f"Cannot read operand: {operand}")

    def read_address(self, operand: Operand) -> int:
        if operand.kind in {OperandKind.DIRECT, OperandKind.DATA_ADDR}:
            return operand.value
        if operand.kind == OperandKind.ADDR_REG:
            return self.a[operand.value]
        if operand.kind == OperandKind.INDIRECT:
            return self.a[operand.value]
        if operand.kind == OperandKind.IMMEDIATE:
            return operand.value
        raise ValueError(f"Cannot use operand as address: {operand}")

    def write_operand(self, operand: Operand, value: int) -> None:
        value = _to_signed32(value)
        if operand.kind == OperandKind.DATA_REG:
            self.r[operand.value] = value
            return
        if operand.kind == OperandKind.ADDR_REG:
            self.a[operand.value] = value & 0xFFFF
            return
        if operand.kind == OperandKind.DIRECT:
            self.data_memory[operand.value] = value
            return
        if operand.kind == OperandKind.INDIRECT:
            self.data_memory[self.a[operand.value]] = value
            return
        if operand.kind == OperandKind.SPECIAL_REG:
            return
        raise ValueError(f"Cannot write operand: {operand}")

    def read_selected_operand(self) -> int:
        if self.selected_operand is None:
            raise ValueError("No selected operand")
        return self.read_operand(self.selected_operand)

    def write_selected_operand(self, value: int) -> None:
        if self.selected_operand is None:
            raise ValueError("No selected operand")
        self.write_operand(self.selected_operand, value)

    def execute_alu(self, operation: AluOp) -> int:
        if operation == AluOp.PASS:
            result_raw = self.src_latch
            op_name = ""
            left = self.src_latch
            right = 0
        elif operation == AluOp.INC:
            left = self.dst_latch
            right = 1
            result_raw = left + right
            op_name = "add"
        elif operation == AluOp.DEC:
            left = self.dst_latch
            right = 1
            result_raw = left - right
            op_name = "sub"
        else:
            left = self.dst_latch
            right = self.src_latch
            if operation == AluOp.ADD:
                result_raw = left + right
                op_name = "add"
            elif operation == AluOp.SUB:
                result_raw = left - right
                op_name = "sub"
            elif operation == AluOp.MUL:
                result_raw = left * right
                op_name = "mul"
            elif operation == AluOp.DIV:
                if right == 0:
                    raise ZeroDivisionError("DIV by zero")
                result_raw = int(left / right)
                op_name = ""
            elif operation == AluOp.MOD:
                if right == 0:
                    raise ZeroDivisionError("MOD by zero")
                result_raw = left % right
                op_name = ""
            else:
                result_raw = self.src_latch
                op_name = ""

        result = _to_signed32(result_raw)
        left_u = left & WORD_MASK
        right_u = right & WORD_MASK
        if op_name == "add":
            self.ps["C"] = left_u + right_u > UNSIGNED_MAX
        elif op_name == "sub":
            self.ps["C"] = left_u < right_u
        elif op_name == "mul":
            self.ps["C"] = left_u * right_u > UNSIGNED_MAX
        else:
            self.ps["C"] = False

        self.ps["V"] = (
            op_name in {"add", "sub", "mul"}
            and (result_raw < SIGNED_MIN or result_raw > SIGNED_MAX)
        )
        self.ps["N"] = result < 0
        self.ps["Z"] = result == 0
        self.alu_latch = result
        return result


class ControlUnit:
    def __init__(self, datapath: DataPath, microcode):
        self.datapath = datapath
        self.microcode = microcode
        self.upc = 0
        self.halted = False
        self.last_io_event = ""
        self.current_instruction = None
        self.poly_x = 0
        self.poly_index = 0
        self.poly_result_raw = 0

    def _operand(self, index: int) -> Operand:
        if self.current_instruction is None:
            raise ValueError("Instruction is not decoded")
        return self.current_instruction.operands[index]

    def _dst_operand(self) -> Operand:
        if self.current_instruction is None:
            raise ValueError("Instruction is not decoded")
        index = 1 if len(self.current_instruction.operands) > 1 else 0
        return self.current_instruction.operands[index]

    def tick(self) -> None:
        self.last_io_event = ""
        mc = self.microcode[self.upc]
        dp = self.datapath

        if mc.op == MicroOp.FETCH:
            inst = decode_instruction(dp.command_memory, dp.ip)
            self.current_instruction = inst
            dp.src_desc = inst.operands[0] if inst.operands else None
            dp.dst_desc = inst.operands[1] if len(inst.operands) > 1 else dp.src_desc
            dp.selected_operand = None
            dp.cr = inst.op.value
            dp.ip = (dp.ip + inst.size) & 0xFFFF
        elif mc.op == MicroOp.SELECT_SRC:
            dp.selected_operand = self._operand(0)
        elif mc.op == MicroOp.SELECT_DST:
            dp.selected_operand = self._dst_operand()
        elif mc.op == MicroOp.READ_SELECTED_TO_SRC:
            dp.src_latch = dp.read_selected_operand()
        elif mc.op == MicroOp.READ_SELECTED_TO_DST:
            dp.dst_latch = dp.read_selected_operand()
        elif mc.op == MicroOp.ALU:
            dp.execute_alu(mc.alu)
        elif mc.op == MicroOp.WRITE_ALU_TO_SELECTED:
            dp.write_selected_operand(dp.alu_latch)
        elif mc.op == MicroOp.WRITE_SRC_TO_SELECTED:
            dp.write_selected_operand(dp.src_latch)

        if mc.move == Move.NEXT:
            self.upc += 1
        elif mc.move == Move.FETCH:
            self.upc = 0
        elif mc.move == Move.DISPATCH_OP:
            if self.current_instruction is None:
                raise ValueError("Cannot dispatch without instruction")
            self.upc = EXEC_MAP[self.current_instruction.op]
        elif mc.move == Move.HLT:
            self.halted = True
        elif mc.move == Move.BRANCH:
            self._branch()
            self.upc = 0
        elif mc.move == Move.IN:
            self._input()
            self.upc = 0
        elif mc.move == Move.OUT:
            self._output()
            self.upc = 0
        elif mc.move == Move.CSTR_LOOP_OR_FETCH:
            self._out_cstr()
            self.upc = 0
        elif mc.move == Move.POLY_START:
            self._poly_start()
            self.upc = EXEC_MAP[OpCode.POLY] + 1
        elif mc.move == Move.POLY_STEP:
            self._poly_step()

    def _branch(self) -> None:
        if self.current_instruction is None:
            raise ValueError("No instruction for branch")
        op = self.current_instruction.op
        target = self.datapath.read_operand(self._operand(0)) & 0xFFFF
        if op == OpCode.JMP:
            self.datapath.ip = target
        elif op == OpCode.BEQ and self.datapath.ps["Z"]:
            self.datapath.ip = target
        elif op == OpCode.BNE and not self.datapath.ps["Z"]:
            self.datapath.ip = target
        elif op == OpCode.BLT and self.datapath.ps["N"]:
            self.datapath.ip = target
        elif op == OpCode.BGT and not self.datapath.ps["N"] and not self.datapath.ps["Z"]:
            self.datapath.ip = target

    def _input(self) -> None:
        port = self.datapath.read_operand(self._operand(0))
        if port != 0:
            raise ValueError(f"Unsupported input port: {port}")
        if not self.datapath.input_buffer:
            self.halted = True
            return
        value = self.datapath.input_buffer.pop(0)
        self.datapath.write_operand(self._operand(1), value)
        self.datapath.src_latch = value
        self.datapath.execute_alu(AluOp.PASS)
        self.last_io_event = f"IN[{port}] -> R{self._operand(1).value + 1}={value}"

    def _output(self) -> None:
        port = self.datapath.read_operand(self._operand(1))
        if port != 0:
            raise ValueError(f"Unsupported output port: {port}")
        value = self.datapath.read_operand(self._operand(0)) & 0xFF
        self.datapath.output_buffer.append(value)
        self.last_io_event = f"OUT[{port}] <- value={value}"

    def _out_cstr(self) -> None:
        addr = self.datapath.read_address(self._operand(0)) & 0xFFFF
        while self.datapath.data_memory[addr] != 0:
            value = self.datapath.data_memory[addr] & 0xFF
            self.datapath.output_buffer.append(value)
            self.last_io_event = f"OUT_CSTR[0] <- char={value} addr={addr:04X}"
            addr = (addr + 1) & 0xFFFF

    def _poly_start(self) -> None:
        if self.current_instruction is None:
            raise ValueError("No instruction for POLY")
        operands = self.current_instruction.operands
        self.poly_x = self.datapath.read_operand(operands[0])
        self.poly_index = len(operands) - 2
        self.poly_result_raw = 0

    def _poly_step(self) -> None:
        if self.current_instruction is None:
            raise ValueError("No instruction for POLY")
        operands = self.current_instruction.operands
        dst = operands[-1]
        if self.poly_index >= 1:
            coeff = self.datapath.read_operand(operands[self.poly_index])
            self.poly_result_raw = self.poly_result_raw * self.poly_x + coeff
            self.poly_index -= 1
            self.upc = EXEC_MAP[OpCode.POLY] + 1
            return

        result = _to_signed32(self.poly_result_raw)
        self.datapath.write_operand(dst, result)
        self.datapath.ps["C"] = (
            self.poly_result_raw < 0 or self.poly_result_raw > UNSIGNED_MAX
        )
        self.datapath.ps["V"] = (
            self.poly_result_raw < SIGNED_MIN or self.poly_result_raw > SIGNED_MAX
        )
        self.datapath.ps["N"] = result < 0
        self.datapath.ps["Z"] = result == 0
        self.upc = 0


def _load_program(path: str) -> tuple[list[int], list[int], int]:
    with open(path, "rb") as f:
        blob = f.read()
    if len(blob) < 10 or blob[:4] != b"AK4B":
        raise ValueError("Bad binary format")

    entry = struct.unpack_from(">H", blob, 4)[0]
    cmd_len = struct.unpack_from(">H", blob, 6)[0]
    data_len = struct.unpack_from(">H", blob, 8)[0]
    pos = 10
    cmd = [0] * 65536
    cmd_slice = blob[pos : pos + cmd_len]
    pos += cmd_len
    for i, b in enumerate(cmd_slice):
        cmd[i] = b

    data = [0] * 65536
    for addr in range(data_len):
        data[addr] = struct.unpack_from(">i", blob, pos)[0]
        pos += 4

    return cmd, data, entry


def _load_input(path: str | None) -> list[int]:
    if path is None:
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return [ord(ch) for ch in text]


def run(
    binary_path: str,
    input_path: str | None,
    limit: int,
    trace_path: str = "trace.log",
) -> str:
    cmd, data, entry = _load_program(binary_path)
    dp = DataPath()
    dp.set_command_memory(cmd)
    dp.set_data_memory(data)
    dp.ip = entry
    dp.input_buffer = _load_input(input_path)

    cu = ControlUnit(dp, microcode_memory)
    ticks = 0
    with open(trace_path, "w", encoding="utf-8") as trace:
        while (not cu.halted) and ticks < limit:
            cu.tick()
            trace.write(
                "tick="
                + str(ticks)
                + " mode=scalar"
                + f" uPC={cu.upc:03d} IP={dp.ip:04X} CR={dp.cr:02X} "
                + f"R1={dp.r[0]} R2={dp.r[1]} R3={dp.r[2]} "
                + f"A1={dp.a[0]:04X} A2={dp.a[1]:04X} A3={dp.a[2]:04X} "
                + "PS="
                + f"N{int(dp.ps['N'])}Z{int(dp.ps['Z'])}"
                + f"V{int(dp.ps['V'])}C{int(dp.ps['C'])}"
                + (f" {cu.last_io_event}" if cu.last_io_event else "")
                + "\n"
            )
            ticks += 1

    return "".join(chr(x) for x in dp.output_buffer)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--limit", type=int, default=1000000)
    parser.add_argument("--trace", default="trace.log")
    args = parser.parse_args()

    out = run(args.binary, args.input, args.limit, args.trace)
    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        print(out, end="")


if __name__ == "__main__":
    main()
