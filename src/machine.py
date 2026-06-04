import argparse
import struct

from src.isa import (
    EXEC_MAP,
    AluOp,
    DecodedInstruction,
    McDst,
    McSrc,
    MicroOp,
    MicroProgramStart,
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
        self.operand_addresses: list[int | None] = []

        self.input_buffer: list[int] = []
        self.output_buffer: list[int] = []

    def set_command_memory(self, command_memory: list[int]) -> None:
        self.command_memory = command_memory

    def set_data_memory(self, data_memory: list[int]) -> None:
        self.data_memory = data_memory

    def read_operand(self, operand: Operand, address: int | None = None) -> int:
        if operand.kind == OperandKind.DATA_REG:
            return self.r[operand.value]
        if operand.kind == OperandKind.ADDR_REG:
            return self.a[operand.value]
        if operand.kind == OperandKind.DIRECT:
            return self.data_memory[address if address is not None else operand.value]
        if operand.kind == OperandKind.INDIRECT:
            return self.data_memory[
                address if address is not None else self.a[operand.value]
            ]
        if operand.kind == OperandKind.IMMEDIATE:
            return operand.value
        if operand.kind == OperandKind.SPECIAL_REG:
            return 0
        if operand.kind in {
            OperandKind.PORT,
            OperandKind.CODE_ADDR,
            OperandKind.DATA_ADDR,
        }:
            return operand.value
        raise ValueError(f"Cannot read operand: {operand}")

    def read_address(self, operand: Operand, address: int | None = None) -> int:
        if address is not None:
            return address
        if operand.kind in {OperandKind.DIRECT, OperandKind.DATA_ADDR}:
            return operand.value
        if operand.kind == OperandKind.ADDR_REG:
            return self.a[operand.value]
        if operand.kind == OperandKind.INDIRECT:
            return self.a[operand.value]
        if operand.kind == OperandKind.IMMEDIATE:
            return operand.value
        raise ValueError(f"Cannot use operand as address: {operand}")

    def write_operand(
        self, operand: Operand, value: int, address: int | None = None
    ) -> None:
        value = _to_signed32(value)
        if operand.kind == OperandKind.DATA_REG:
            self.r[operand.value] = value
            return
        if operand.kind == OperandKind.ADDR_REG:
            self.a[operand.value] = value & 0xFFFF
            return
        if operand.kind == OperandKind.DIRECT:
            self.data_memory[address if address is not None else operand.value] = value
            return
        if operand.kind == OperandKind.INDIRECT:
            self.data_memory[
                address if address is not None else self.a[operand.value]
            ] = value
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

    def execute_alu(
        self,
        operation: AluOp,
        left: int | None = None,
        right: int | None = None,
        write_flags: bool = True,
    ) -> int:
        if left is None:
            left = (
                self.dst_latch
                if operation not in {AluOp.PASS, AluOp.NONE}
                else self.src_latch
            )
        if right is None:
            right = self.src_latch

        if operation in {AluOp.NONE, AluOp.PASS}:
            result_raw = left
            op_name = ""
        elif operation == AluOp.INC:
            right = 1
            result_raw = left + right
            op_name = "add"
        elif operation == AluOp.DEC:
            right = 1
            result_raw = left - right
            op_name = "sub"
        else:
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
        if write_flags:
            if op_name == "add":
                self.ps["C"] = left_u + right_u > UNSIGNED_MAX
            elif op_name == "sub":
                self.ps["C"] = left_u < right_u
            elif op_name == "mul":
                self.ps["C"] = left_u * right_u > UNSIGNED_MAX
            else:
                self.ps["C"] = False

            self.ps["V"] = op_name in {"add", "sub", "mul"} and (
                result_raw < SIGNED_MIN or result_raw > SIGNED_MAX
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
        self.current_instruction: DecodedInstruction | None = None
        self.operand_prepare_index = 0
        self.cstr_addr: int | None = None
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
        return self.current_instruction.operands[self._dst_index()]

    def _dst_index(self) -> int:
        if self.current_instruction is None:
            raise ValueError("Instruction is not decoded")
        return 1 if len(self.current_instruction.operands) > 1 else 0

    def _prepared_address(self, index: int) -> int | None:
        return self.datapath.operand_addresses[index]

    def _read_operand(self, index: int) -> int:
        return self.datapath.read_operand(
            self._operand(index), self._prepared_address(index)
        )

    def _write_operand(self, index: int, value: int) -> None:
        self.datapath.write_operand(
            self._operand(index), value, self._prepared_address(index)
        )

    def _read_dst(self) -> int:
        return self._read_operand(self._dst_index())

    def _write_dst(self, value: int) -> None:
        self._write_operand(self._dst_index(), value)

    def _read_micro_source(self, source: McSrc) -> int:
        if source == McSrc.SRC_LATCH:
            return self.datapath.src_latch
        if source == McSrc.DST_LATCH:
            return self.datapath.dst_latch
        if source == McSrc.ZERO:
            return 0
        return 0

    def _write_micro_destination(self, destination: McDst, value: int) -> None:
        if destination == McDst.ALU_LATCH:
            self.datapath.alu_latch = value

    @staticmethod
    def _format_operand(operand: Operand) -> str:
        if operand.kind == OperandKind.DATA_REG:
            return f"R{operand.value + 1}"
        if operand.kind == OperandKind.ADDR_REG:
            return f"A{operand.value + 1}"
        if operand.kind == OperandKind.DIRECT:
            return f"mem[{operand.value:04X}]"
        if operand.kind == OperandKind.INDIRECT:
            return f"(A{operand.value + 1})"
        if operand.kind == OperandKind.SPECIAL_REG:
            return "ZERO"
        return "dst"

    @staticmethod
    def _needs_address_prepare(operand: Operand) -> bool:
        return operand.kind in {
            OperandKind.DIRECT,
            OperandKind.INDIRECT,
            OperandKind.DATA_ADDR,
            OperandKind.CODE_ADDR,
        }

    def _prepare_or_dispatch(self) -> None:
        if self.current_instruction is None:
            raise ValueError("Cannot dispatch without instruction")
        operands = self.current_instruction.operands
        while self.operand_prepare_index < len(operands):
            operand = operands[self.operand_prepare_index]
            if self._needs_address_prepare(operand):
                self.upc = MicroProgramStart.PREPARE_OPERAND
                return
            self.operand_prepare_index += 1
        self.upc = EXEC_MAP[self.current_instruction.op]

    def _prepare_operand_address(self) -> None:
        if self.current_instruction is None:
            raise ValueError("Instruction is not decoded")
        operand = self.current_instruction.operands[self.operand_prepare_index]
        if operand.kind == OperandKind.INDIRECT:
            address = self.datapath.a[operand.value]
        else:
            address = operand.value
        self.datapath.operand_addresses[self.operand_prepare_index] = address & 0xFFFF
        self.last_io_event = (
            f"EA[{self.operand_prepare_index}] <- {address & 0xFFFF:04X}"
        )
        self.operand_prepare_index += 1

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
            dp.operand_addresses = [None] * len(inst.operands)
            dp.cr = inst.op.value
            dp.ip = (dp.ip + inst.size) & 0xFFFF
            self.operand_prepare_index = 0
            self.cstr_addr = None
        elif mc.op == MicroOp.PREPARE_OPERAND:
            self._prepare_operand_address()
        elif mc.op == MicroOp.LOAD_SRC:
            dp.src_latch = self._read_operand(0)
        elif mc.op == MicroOp.LOAD_DST:
            dp.dst_latch = self._read_dst()
        elif mc.op == MicroOp.STORE_DST:
            self._write_dst(dp.alu_latch)
        elif mc.op == MicroOp.ALU:
            left = self._read_micro_source(mc.left)
            right = self._read_micro_source(mc.right)
            result = dp.execute_alu(mc.alu, left, right, mc.write_flags)
            self._write_micro_destination(mc.dst, result)

        if mc.move == Move.NEXT:
            self.upc += 1
        elif mc.move == Move.FETCH:
            self.upc = 0
        elif mc.move == Move.DISPATCH_OP:
            if self.current_instruction is None:
                raise ValueError("Cannot dispatch without instruction")
            self.upc = EXEC_MAP[self.current_instruction.op]
        elif mc.move == Move.PREPARE_OR_DISPATCH:
            self._prepare_or_dispatch()
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
        elif mc.move == Move.POLY_START:
            self._poly_start()
            self.upc = EXEC_MAP[OpCode.POLY] + 1
        elif mc.move == Move.POLY_STEP:
            self._poly_step()

    def _branch(self) -> None:
        if self.current_instruction is None:
            raise ValueError("No instruction for branch")
        op = self.current_instruction.op
        target = self._read_operand(0) & 0xFFFF
        if op == OpCode.JMP:
            self.datapath.ip = target
        elif op == OpCode.BEQ and self.datapath.ps["Z"]:
            self.datapath.ip = target
        elif op == OpCode.BNE and not self.datapath.ps["Z"]:
            self.datapath.ip = target
        elif op == OpCode.BLT and self.datapath.ps["N"]:
            self.datapath.ip = target
        elif (
            op == OpCode.BGT and not self.datapath.ps["N"] and not self.datapath.ps["Z"]
        ):
            self.datapath.ip = target

    def _input(self) -> None:
        port = self._read_operand(0)
        if port != 0:
            raise ValueError(f"Unsupported input port: {port}")
        if not self.datapath.input_buffer:
            self.halted = True
            return
        value = self.datapath.input_buffer.pop(0)
        self._write_operand(1, value)
        self.datapath.src_latch = value
        self.datapath.execute_alu(AluOp.PASS, value)
        self.last_io_event = (
            f"IN[{port}] -> {self._format_operand(self._operand(1))}={value}"
        )

    def _output(self) -> None:
        port = self._read_operand(1)
        if port != 0:
            raise ValueError(f"Unsupported output port: {port}")
        value = self._read_operand(0) & 0xFF
        self.datapath.output_buffer.append(value)
        self.last_io_event = f"OUT[{port}] <- value={value}"

    def _out_cstr(self) -> None:
        if self.cstr_addr is None:
            self.cstr_addr = (
                self.datapath.read_address(self._operand(0), self._prepared_address(0))
                & 0xFFFF
            )
        value = self.datapath.data_memory[self.cstr_addr]
        if value == 0:
            self.cstr_addr = None
            self.upc = 0
            return
        self.datapath.output_buffer.append(value & 0xFF)
        self.last_io_event = (
            f"OUT_CSTR[0] <- char={value & 0xFF} addr={self.cstr_addr:04X}"
        )
        self.cstr_addr = (self.cstr_addr + 1) & 0xFFFF
        self.upc = EXEC_MAP[OpCode.OUT_CSTR]

    def _poly_start(self) -> None:
        if self.current_instruction is None:
            raise ValueError("No instruction for POLY")
        operands = self.current_instruction.operands
        self.poly_x = self._read_operand(0)
        self.poly_index = len(operands) - 2
        self.poly_result_raw = 0

    def _poly_step(self) -> None:
        if self.current_instruction is None:
            raise ValueError("No instruction for POLY")
        operands = self.current_instruction.operands
        dst = operands[-1]
        if self.poly_index >= 1:
            coeff = self._read_operand(self.poly_index)
            self.poly_result_raw = self.poly_result_raw * self.poly_x + coeff
            self.poly_index -= 1
            self.upc = EXEC_MAP[OpCode.POLY] + 1
            return

        result = _to_signed32(self.poly_result_raw)
        self.datapath.write_operand(
            dst, result, self._prepared_address(len(operands) - 1)
        )
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
