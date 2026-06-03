import argparse
import struct

from src.isa import Src, Dst, AluOp, MemOp, OpCode, Move
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

        self.ac: int = 0  # Аккумулятор (32 бита)
        self.ip: int = 0  # Счетчик команд (16 бит)
        self.ar: int = 0  # Адресный регистр (16 бит)
        self.dr: int = 0  # Регистр данных (32 бита)
        self.cr: int = 0  # Регистр команд (8 бит)
        self.br: int = 0  # Буферный регистр (32 бита)
        self.ps: dict[str, bool] = {
            "N": False,
            "Z": False,
            "V": False,
            "C": False,
        }  # Регистр состояния (4 бита)

        self.input_buffer: list = []  # Очередь символов из файла
        self.output_buffer: list = []  # Очередь вывода

    def set_command_memory(self, command_memory: list[int]) -> None:
        self.command_memory = command_memory

    def set_data_memory(self, data_memory: list[int]) -> None:
        self.data_memory = data_memory

    def get_src_value(self, src: Src) -> int:
        if src == Src.AC:
            return self.ac
        if src == Src.IP:
            return self.ip
        if src == Src.AR:
            return self.ar
        if src == Src.DR:
            return self.dr
        if src == Src.CR:
            return self.cr
        if src == Src.BR:
            return self.br
        if src == Src.PS:
            return (
                self.ps["N"] * 2**3
                + self.ps["Z"] * 2**2
                + self.ps["V"] * 2
                + self.ps["C"]
            )
        if src == Src.CR_IMM:
            return self.command_memory[self.ip]
        return 0

    def set_dst_value(self, dst: Dst, value: int):
        if dst == Dst.AC:
            self.ac = value
        elif dst == Dst.IP:
            self.ip = value
        elif dst == Dst.AR:
            self.ar = value
        elif dst == Dst.DR:
            self.dr = value
        elif dst == Dst.CR:
            self.cr = value
        elif dst == Dst.BR:
            self.br = value
        elif dst == Dst.PS:
            self.ps["C"] = value % 2 == 1
            value //= 2
            self.ps["V"] = value % 2 == 1
            value //= 2
            self.ps["Z"] = value % 2 == 1
            value //= 2
            self.ps["N"] = value % 2 == 1
        if dst == Dst.AR_L:
            self.ar = (self.ar & 0xFF00) | (value & 0x00FF)
        if dst == Dst.AR_H:
            self.ar = (self.ar & 0x00FF) | (value << 8)

    def execute_alu(self, operation: AluOp, bus_value: int) -> int:
        if operation == AluOp.NONE:
            return bus_value

        if operation in [AluOp.INC, AluOp.DEC]:
            left = bus_value
            right = 1
        else:
            left = self.ac
            right = self.br

        result_raw = 0
        if operation in [AluOp.ADD, AluOp.INC]:
            result_raw = left + right
        elif operation == AluOp.MUL:
            result_raw = left * right
        elif operation == AluOp.DIV:
            if right == 0:
                raise ZeroDivisionError("DIV by zero")
            result_raw = int(left / right)
        elif operation == AluOp.MOD:
            if right == 0:
                raise ZeroDivisionError("MOD by zero")
            result_raw = left % right
        elif operation in [AluOp.SUB, AluOp.CMP, AluOp.DEC]:
            result_raw = left - right

        result = _to_signed32(result_raw)
        left_u = left & WORD_MASK
        right_u = right & WORD_MASK

        if operation in [AluOp.ADD, AluOp.INC]:
            self.ps["C"] = left_u + right_u > UNSIGNED_MAX
        elif operation == AluOp.MUL:
            self.ps["C"] = left_u * right_u > UNSIGNED_MAX
        elif operation in [AluOp.SUB, AluOp.CMP, AluOp.DEC]:
            self.ps["C"] = left_u < right_u
        else:
            self.ps["C"] = False

        if operation in [
            AluOp.ADD,
            AluOp.INC,
            AluOp.MUL,
            AluOp.SUB,
            AluOp.CMP,
            AluOp.DEC,
        ]:
            self.ps["V"] = result_raw < SIGNED_MIN or result_raw > SIGNED_MAX
        else:
            self.ps["V"] = False

        self.ps["N"] = result < 0
        self.ps["Z"] = result == 0

        return result

    def execute_memory(self, operation: MemOp):
        if operation == MemOp.READ_CMD:
            return self.command_memory[self.ip]
        if operation == MemOp.READ_DATA:
            self.dr = self.data_memory[self.ar]
            return self.dr
        if operation == MemOp.WRITE_DATA:
            self.data_memory[self.ar] = self.dr
        return 0


class ControlUnit:
    def __init__(
        self,
        datapath: DataPath,
        microcode: list[int],
    ):
        self.datapath = datapath
        self.microcode = microcode
        self.upc = 0
        self.halted = False
        self.last_io_event = ""

        self.addr_map = {
            OpCode.HLT: 13,
            OpCode.CLA: 14,
            OpCode.NOP: 15,
            OpCode.LD: 2,
            OpCode.ST: 2,
            OpCode.ADD: 2,
            OpCode.MUL: 2,
            OpCode.DIV: 2,
            OpCode.MOD: 2,
            OpCode.SUB: 2,
            OpCode.CMP: 2,
            OpCode.JMP: 2,
            OpCode.BEQ: 2,
            OpCode.BNE: 2,
            OpCode.BLT: 2,
            OpCode.BGT: 2,
            OpCode.IN: 2,
            OpCode.OUT: 2,
            OpCode.OUT_CSTR: 2,
            OpCode.LD_IMM: 6,
            OpCode.ADD_IMM: 6,
            OpCode.SUB_IMM: 6,
            OpCode.CMP_IMM: 6,
            OpCode.LD_IND: 8,
            OpCode.ST_IND: 8,
            OpCode.ADD_IND: 8,
            OpCode.SUB_IND: 8,
            OpCode.CMP_IND: 8,
            OpCode.INC: 32,
            OpCode.DEC: 33,
        }

        self.exec_map = {
            OpCode.LD: 16,
            OpCode.LD_IMM: 17,
            OpCode.ST: 18,
            OpCode.ADD_IMM: 20,
            OpCode.ADD: 22,
            OpCode.MUL: 43,
            OpCode.DIV: 45,
            OpCode.MOD: 47,
            OpCode.SUB: 24,
            OpCode.SUB_IMM: 26,
            OpCode.CMP: 28,
            OpCode.CMP_IMM: 30,
            OpCode.INC: 32,
            OpCode.DEC: 33,
            OpCode.LD_IND: 16,
            OpCode.ST_IND: 18,
            OpCode.ADD_IND: 22,
            OpCode.SUB_IND: 24,
            OpCode.CMP_IND: 28,
            OpCode.JMP: 34,
            OpCode.BEQ: 35,
            OpCode.BNE: 36,
            OpCode.BLT: 37,
            OpCode.BGT: 38,
            OpCode.IN: 39,
            OpCode.OUT: 40,
            OpCode.OUT_CSTR: 41,
        }

    def tick(self):
        self.last_io_event = ""
        mc = self.microcode[self.upc]

        src = Src((mc >> 0) & 0xF)
        dst = Dst((mc >> 4) & 0xF)
        alu_op = AluOp((mc >> 8) & 0xF)
        mem = MemOp((mc >> 12) & 0x7)
        move = Move((mc >> 15) & 0x1F)

        bus_val = self.datapath.get_src_value(src)

        if mem == MemOp.READ_CMD:
            bus_val = self.datapath.execute_memory(mem)
        elif mem == MemOp.READ_DATA:
            bus_val = self.datapath.execute_memory(mem)

        saved_ps = self.datapath.ps.copy()
        if alu_op == AluOp.PASS:
            alu_res = bus_val
        else:
            alu_res = self.datapath.execute_alu(alu_op, bus_val)

        if mem == MemOp.WRITE_DATA:
            self.datapath.execute_memory(mem)

        self.datapath.set_dst_value(dst, alu_res)
        if dst == Dst.IP:
            self.datapath.ps = saved_ps

        if move == Move.FETCH:
            if self.upc == self.exec_map[OpCode.BEQ]:
                if self.datapath.ps["Z"]:
                    self.datapath.ip = self.datapath.ar
            elif self.upc == self.exec_map[OpCode.BNE]:
                if not self.datapath.ps["Z"]:
                    self.datapath.ip = self.datapath.ar
            elif self.upc == self.exec_map[OpCode.BLT]:
                if self.datapath.ps["N"]:
                    self.datapath.ip = self.datapath.ar
            elif self.upc == self.exec_map[OpCode.BGT]:
                if (not self.datapath.ps["N"]) and (not self.datapath.ps["Z"]):
                    self.datapath.ip = self.datapath.ar
            elif self.upc == self.exec_map[OpCode.IN]:
                if self.datapath.ar != 0:
                    raise ValueError(f"Unsupported input port: {self.datapath.ar}")
                if not self.datapath.input_buffer:
                    self.halted = True
                    return
                self.datapath.ac = self.datapath.input_buffer.pop(0)
                self.last_io_event = f"IN[{self.datapath.ar}] -> AC={self.datapath.ac}"
            elif self.upc == self.exec_map[OpCode.OUT]:
                if self.datapath.ar != 0:
                    raise ValueError(f"Unsupported output port: {self.datapath.ar}")
                self.datapath.output_buffer.append(self.datapath.ac & 0xFF)
                self.last_io_event = (
                    f"OUT[{self.datapath.ar}] <- AC={self.datapath.ac & 0xFF}"
                )

        if move == Move.NEXT:
            self.upc += 1
        elif move == Move.FETCH:
            self.upc = 0
        elif move == Move.DISPATCH_ADDR:
            self.upc = self.addr_map[OpCode(self.datapath.cr)]
        elif move == Move.DISPATCH_OP:
            self.upc = self.exec_map[OpCode(self.datapath.cr)]
        elif move == Move.HLT:
            self.halted = True
        elif move == Move.CSTR_LOOP_OR_FETCH:
            if self.datapath.dr == 0:
                self.upc = 0
            else:
                self.datapath.output_buffer.append(self.datapath.dr & 0xFF)
                self.last_io_event = (
                    f"OUT_CSTR[0] <- char={self.datapath.dr & 0xFF} "
                    + f"addr={self.datapath.ar:04X}"
                )
                self.datapath.ar = (self.datapath.ar + 1) & 0xFFFF
                self.upc = self.exec_map[OpCode.OUT_CSTR]


def _load_program(path: str) -> tuple[list[int], list[int], int]:
    with open(path, "rb") as f:
        blob = f.read()
    if len(blob) < 10 or blob[:4] != b"AK4B":
        raise ValueError("Bad binary format")

    entry = struct.unpack_from(">H", blob, 4)[0]
    cmd_len = struct.unpack_from(">H", blob, 6)[0]
    pos = 8
    cmd = [0] * 65536
    cmd_slice = blob[pos : pos + cmd_len]
    pos += cmd_len
    for i, b in enumerate(cmd_slice):
        cmd[i] = b

    data = [0] * 65536
    items = struct.unpack_from(">H", blob, pos)[0]
    pos += 2
    for _ in range(items):
        addr, value = struct.unpack_from(">Hi", blob, pos)
        pos += 6
        data[addr] = value

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
                + f"AR={dp.ar:04X} AC={dp.ac} DR={dp.dr} BR={dp.br} "
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
