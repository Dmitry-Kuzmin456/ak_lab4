import argparse
import struct

# ruff: noqa: F403, F405
from src.isa import *
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

        self.r: list[int] = [0, 0, 0, 0]  # R1-R3, index 0 is unused
        self.a: list[int] = [0, 0, 0, 0]  # A1-A3, index 0 is unused
        self.ip: int = 0
        self.cr: int = 0
        self.ps: dict[str, bool] = {
            "N": False,
            "Z": False,
            "V": False,
            "C": False,
        }

        self.shadow_r0: int = 0
        self.shadow_r1: int = 0
        self.shadow_r2: int = 0
        self.shadow_a0: int = 0
        self.operand_kinds: int = 0
        self.op0_payload: int = 0
        self.op1_payload: int = 0
        self.op0_desc: Operand = Operand(OperandKind.NONE, 0)
        self.op1_desc: Operand = Operand(OperandKind.NONE, 0)
        # EA0/EA1 from the scheme; a list keeps the same path for one/two operands.
        self.operand_addresses: list[int | None] = []
        # Decoder/OP-mux bookkeeping for the simulator, not separate datapath registers.
        self.operand_prepare_index: int = 0

        self.input_buffer: list[int] = []
        self.output_buffer: list[int] = []

    def set_command_memory(self, command_memory: list[int]) -> None:
        self.command_memory = command_memory

    def set_data_memory(self, data_memory: list[int]) -> None:
        self.data_memory = data_memory

    def current_op(self) -> OpCode:
        return OpCode(self.cr)

    def operand(self, index: int) -> Operand:
        if index == 0:
            return self.op0_desc
        if index == 1:
            return self.op1_desc
        raise ValueError(f"Bad operand index: {index}")

    def instruction_operand_count(self) -> int:
        count = OPERAND_COUNT[self.current_op()]
        if count is None:
            return 0
        return count

    def dst_index(self) -> int:
        return 1 if self.instruction_operand_count() > 1 else 0

    def reset_decode_latches(self) -> None:
        self.operand_kinds = 0
        self.op0_payload = 0
        self.op1_payload = 0
        self.op0_desc = Operand(OperandKind.NONE, 0)
        self.op1_desc = Operand(OperandKind.NONE, 0)
        self.operand_addresses = []
        self.operand_prepare_index = 0

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
        if operand.kind in {OperandKind.POST_INC, OperandKind.PRE_DEC}:
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
        if operand.kind in {OperandKind.POST_INC, OperandKind.PRE_DEC}:
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
        if operand.kind in {OperandKind.POST_INC, OperandKind.PRE_DEC}:
            self.data_memory[
                address if address is not None else self.a[operand.value]
            ] = value
            return
        if operand.kind == OperandKind.SPECIAL_REG:
            return
        raise ValueError(f"Cannot write operand: {operand}")

    def execute_alu(
        self,
        operation: AluOp,
        left: int | None = None,
        right: int | None = None,
        write_flags: bool = True,
    ) -> int:
        if left is None:
            left = (
                self.shadow_r1
                if operation not in {AluOp.PASS, AluOp.NONE}
                else self.shadow_r0
            )
        if right is None:
            right = self.shadow_r0

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
        elif operation == AluOp.NEG:
            right = left
            left = 0
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
            elif operation == AluOp.OR:
                result_raw = left | right
                op_name = ""
            elif operation == AluOp.AND:
                result_raw = left & right
                op_name = ""
            else:
                result_raw = self.shadow_r0
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
        return result


class ControlUnit:
    def __init__(self, datapath: DataPath, microcode):
        self.datapath = datapath
        self.microcode = microcode
        self.upc = 0
        self.halted = False
        self.last_io_event = ""

    def _read_operand(self, index: int) -> int:
        dp = self.datapath
        address = (
            dp.operand_addresses[index] if index < len(dp.operand_addresses) else None
        )
        return dp.read_operand(dp.operand(index), address)

    def _write_operand(self, index: int, value: int) -> None:
        dp = self.datapath
        dp.write_operand(dp.operand(index), value, dp.operand_addresses[index])

    def _dst_is_register(self) -> bool:
        return self.datapath.operand(self.datapath.dst_index()).kind in {
            OperandKind.DATA_REG,
            OperandKind.ADDR_REG,
            OperandKind.SPECIAL_REG,
        }

    def _store_dst_if_memory(self) -> None:
        if self._dst_is_register():
            self.upc = 0
            return
        self.upc = MicroProgramStart.STORE_DST

    @staticmethod
    def _format_operand(operand: Operand) -> str:
        if operand.kind == OperandKind.DATA_REG:
            return f"R{operand.value}"
        if operand.kind == OperandKind.ADDR_REG:
            return f"A{operand.value}"
        if operand.kind == OperandKind.DIRECT:
            return f"mem[{operand.value:04X}]"
        if operand.kind == OperandKind.INDIRECT:
            return f"(A{operand.value})"
        if operand.kind == OperandKind.POST_INC:
            return f"(A{operand.value})+"
        if operand.kind == OperandKind.PRE_DEC:
            return f"-(A{operand.value})"
        if operand.kind == OperandKind.SPECIAL_REG:
            return "ZERO"
        return "dst"

    @staticmethod
    def _needs_address_prepare(operand: Operand) -> bool:
        return operand.kind in {
            OperandKind.DIRECT,
            OperandKind.INDIRECT,
            OperandKind.POST_INC,
            OperandKind.PRE_DEC,
            OperandKind.DATA_ADDR,
            OperandKind.CODE_ADDR,
        }

    def _prepare_or_dispatch(self) -> None:
        dp = self.datapath
        operand_count = dp.instruction_operand_count()
        if len(dp.operand_addresses) != operand_count:
            dp.operand_addresses = [None] * operand_count
        while dp.operand_prepare_index < operand_count:
            operand = dp.operand(dp.operand_prepare_index)
            if self._needs_address_prepare(operand):
                self._prepare_by_kind()
                return
            dp.operand_prepare_index += 1
        self.upc = EXEC_MAP[dp.current_op()]

    def _prepare_by_kind(self) -> None:
        operand = self.datapath.operand(self.datapath.operand_prepare_index)
        if operand.kind in {
            OperandKind.DIRECT,
            OperandKind.DATA_ADDR,
            OperandKind.CODE_ADDR,
        }:
            self.upc = MicroProgramStart.PREPARE_DIRECT
        elif operand.kind == OperandKind.INDIRECT:
            self.upc = MicroProgramStart.PREPARE_INDIRECT
        elif operand.kind == OperandKind.POST_INC:
            self.upc = MicroProgramStart.PREPARE_POST_INC
        elif operand.kind == OperandKind.PRE_DEC:
            self.upc = MicroProgramStart.PREPARE_PRE_DEC
        else:
            raise ValueError(f"Cannot prepare address for operand: {operand}")

    def _save_prepared_address(self, address: int) -> None:
        dp = self.datapath
        dp.operand_addresses[dp.operand_prepare_index] = address & 0xFFFF
        self.last_io_event = f"EA[{dp.operand_prepare_index}] <- {address & 0xFFFF:04X}"
        dp.operand_prepare_index += 1

    def _write_addr_reg_from_alu(self, slot: OperandSlot, value: int) -> None:
        dp = self.datapath
        index = dp.operand_prepare_index
        if slot == OperandSlot.PREVIOUS:
            index -= 1
        operand_count = (
            1 if dp.current_op() == OpCode.CSTR else dp.instruction_operand_count()
        )
        if index < 0 or index >= operand_count:
            raise ValueError(f"No operand selected for address register update: {slot}")
        operand = dp.operand(index)
        if operand.kind not in {
            OperandKind.ADDR_REG,
            OperandKind.POST_INC,
            OperandKind.PRE_DEC,
        }:
            raise ValueError(f"Operand does not update address register: {operand}")
        dp.a[operand.value] = value & 0xFFFF

    def _fetch_src_or_dispatch(self) -> None:
        dp = self.datapath
        if dp.current_op() == OpCode.CSTR:
            self.upc = MicroProgramStart.FETCH_CSTR_ADDRESS_REGISTER
            return
        operand_count = dp.instruction_operand_count()
        if operand_count >= 1:
            self.upc = MicroProgramStart.FETCH_SRC_PAYLOAD
            return
        dp.operand_prepare_index = 0
        dp.operand_addresses = [None] * operand_count
        self._prepare_or_dispatch()

    def _fetch_dst_or_prepare(self) -> None:
        dp = self.datapath
        operand_count = dp.instruction_operand_count()
        if operand_count >= 2:
            self.upc = MicroProgramStart.FETCH_DST_PAYLOAD
            return
        dp.operand_prepare_index = 0
        dp.operand_addresses = [None] * operand_count
        self._prepare_or_dispatch()

    @staticmethod
    def _read_u16(memory: list[int], ip: int) -> int:
        return (memory[ip] << 8) | memory[ip + 1]

    def _fetch_src_payload(self) -> None:
        dp = self.datapath
        kind = OperandKind((dp.operand_kinds >> 4) & 0x0F)
        payload = self._read_u16(dp.command_memory, dp.ip)
        dp.op0_payload = payload
        dp.op0_desc = decode_operand_payload(kind, payload)
        dp.ip = (dp.ip + 2) & 0xFFFF

    def _fetch_dst_payload(self) -> None:
        dp = self.datapath
        kind = OperandKind(dp.operand_kinds & 0x0F)
        payload = self._read_u16(dp.command_memory, dp.ip)
        dp.op1_payload = payload
        dp.op1_desc = decode_operand_payload(kind, payload)
        dp.ip = (dp.ip + 2) & 0xFFFF

    def _fetch_cstr_address_register(self) -> None:
        dp = self.datapath
        reg = dp.command_memory[dp.ip]
        if reg not in {1, 2, 3}:
            raise ValueError(f"Bad CSTR address register: {reg}")
        dp.op0_payload = reg
        dp.op0_desc = Operand(OperandKind.ADDR_REG, reg)
        dp.ip = (dp.ip + 1) & 0xFFFF

    def _fetch_cstr_char(self) -> None:
        dp = self.datapath
        char = dp.command_memory[dp.ip]
        dp.op1_payload = char
        dp.op1_desc = Operand(OperandKind.IMMEDIATE, char)
        dp.ip = (dp.ip + 1) & 0xFFFF

    def _latch_fetch(self) -> None:
        dp = self.datapath
        ip = dp.ip
        op = OpCode(dp.command_memory[ip])
        dp.reset_decode_latches()
        dp.cr = op.value
        if op == OpCode.CSTR:
            dp.ip = (dp.ip + 1) & 0xFFFF
        else:
            operand_count = dp.instruction_operand_count()
            if OPERAND_COUNT[op] is None:
                raise ValueError(f"Bad operand count for opcode: {op}")
            if operand_count > 0:
                dp.operand_kinds = dp.command_memory[ip + 1]
                dp.ip = (dp.ip + 2) & 0xFFFF
            else:
                dp.ip = (dp.ip + 1) & 0xFFFF

    def _latch_ea(self, source: EaSource) -> None:
        dp = self.datapath
        operand = dp.operand(dp.operand_prepare_index)
        if source == EaSource.OPERAND_PAYLOAD:
            address = operand.value
        elif source == EaSource.ADDRESS_REG:
            address = dp.a[operand.value]
        else:
            raise ValueError(f"Unsupported EA source: {source}")
        self._save_prepared_address(address)

    def _latch_mpc(self, select: MpcSel) -> None:
        if select == MpcSel.ZERO:
            self.upc = 0
        elif select == MpcSel.NEXT:
            self.upc += 1
        elif select == MpcSel.OPCODE:
            self.upc = EXEC_MAP[self.datapath.current_op()]
        elif select == MpcSel.PREPARE_OR_DISPATCH:
            self._prepare_or_dispatch()
        elif select == MpcSel.FETCH_SRC_OR_DISPATCH:
            self._fetch_src_or_dispatch()
        elif select == MpcSel.FETCH_DST_OR_PREPARE:
            self._fetch_dst_or_prepare()
        elif select == MpcSel.STORE_DST_IF_MEMORY:
            self._store_dst_if_memory()
        elif select == MpcSel.CSTR_LOOP_OR_FETCH:
            if self.datapath.shadow_r0 == 0:
                if self.datapath.operand_addresses:
                    self.datapath.operand_addresses[0] = None
                self.upc = 0
            else:
                self.upc += 1
        elif select == MpcSel.CSTR_DONE_OR_NEXT_CHAR:
            if self.datapath.shadow_r0 == 0:
                self.upc = 0
            else:
                self.upc = MicroProgramStart.CSTR_READ_CHAR
        else:
            raise ValueError(f"Unsupported mPC selector: {select}")

    def _dispatch_signal(self, signal: Signal) -> None:
        dp = self.datapath
        if isinstance(signal, LatchFetch):
            self._latch_fetch()
        elif isinstance(signal, LatchSrcPayload):
            self._fetch_src_payload()
        elif isinstance(signal, LatchDstPayload):
            self._fetch_dst_payload()
        elif isinstance(signal, LatchCstrAddressRegister):
            self._fetch_cstr_address_register()
        elif isinstance(signal, LatchCstrChar):
            self._fetch_cstr_char()
        elif isinstance(signal, LatchEa):
            self._latch_ea(signal.source)
        elif isinstance(signal, LatchShadowA0):
            operand = dp.operand(dp.operand_prepare_index)
            dp.shadow_a0 = dp.a[operand.value]
        elif isinstance(signal, LatchShadowR0):
            if signal.slot == OperandSlot.SRC:
                index = 0
            elif signal.slot == OperandSlot.DST:
                index = dp.dst_index()
            elif signal.slot == OperandSlot.OP1:
                index = 1
            else:
                index = dp.operand_prepare_index
            dp.shadow_r0 = self._read_operand(index)
        elif isinstance(signal, LatchShadowR1):
            if signal.slot == OperandSlot.DST:
                index = dp.dst_index()
            elif signal.slot == OperandSlot.SRC:
                index = 0
            else:
                index = dp.operand_prepare_index
            dp.shadow_r1 = self._read_operand(index)
        elif isinstance(signal, WriteDst):
            if signal.source == WriteSource.SHADOW_R2:
                value = dp.shadow_r2
            else:
                raise ValueError(f"Unsupported write source: {signal.source}")
            self._write_operand(dp.dst_index(), value)
        elif isinstance(signal, AluSignal):
            if signal.left == McSrc.SHADOW_R0:
                left = dp.shadow_r0
            elif signal.left == McSrc.SHADOW_R1:
                left = dp.shadow_r1
            elif signal.left == McSrc.SHADOW_A0:
                left = dp.shadow_a0
            elif signal.left == McSrc.SHADOW_R2:
                left = dp.shadow_r2
            else:
                left = 0

            if signal.right == McSrc.SHADOW_R0:
                right = dp.shadow_r0
            elif signal.right == McSrc.SHADOW_R1:
                right = dp.shadow_r1
            elif signal.right == McSrc.SHADOW_A0:
                right = dp.shadow_a0
            elif signal.right == McSrc.SHADOW_R2:
                right = dp.shadow_r2
            else:
                right = 0

            result = dp.execute_alu(signal.alu, left, right, signal.write_flags)
            if signal.dst == McDst.SHADOW_R0:
                dp.shadow_r0 = result
            elif signal.dst == McDst.SHADOW_R1:
                dp.shadow_r1 = result
            elif signal.dst == McDst.SHADOW_R2:
                dp.shadow_r2 = result
            elif signal.dst == McDst.SHADOW_A0:
                dp.shadow_a0 = result
            elif signal.dst == McDst.ADDRESS_REG:
                self._write_addr_reg_from_alu(signal.dst_slot, result)
            elif signal.dst == McDst.DST_OR_SHADOW_R2:
                if self._dst_is_register():
                    self._write_operand(dp.dst_index(), result)
                else:
                    dp.shadow_r2 = result
            elif signal.dst != McDst.NONE:
                raise ValueError(f"Unsupported ALU destination: {signal.dst}")
        elif isinstance(signal, BranchSignal):
            self._branch()
        elif isinstance(signal, InputSignal):
            self._input()
        elif isinstance(signal, OutputSignal):
            self._output()
        elif isinstance(signal, LatchShadowR0FromDataMemory):
            address = dp.operand_addresses[signal.ea_index]
            if address is None:
                raise ValueError("No EA selected for data memory read")
            dp.shadow_r0 = dp.data_memory[address]
        elif isinstance(signal, OutputShadowR0):
            address = dp.operand_addresses[0]
            if address is None:
                raise ValueError("OUT_CSTR has no prepared address")
            value = dp.shadow_r0 & 0xFF
            dp.output_buffer.append(value)
            self.last_io_event = f"OUT_CSTR[0] <- char={value} addr={address:04X}"
        elif isinstance(signal, LatchShadowA0FromEa):
            address = dp.operand_addresses[signal.ea_index]
            if address is None:
                raise ValueError("No EA selected for shadow_a0")
            dp.shadow_a0 = address
        elif isinstance(signal, LatchEaFromShadowR2):
            dp.operand_addresses[signal.ea_index] = dp.shadow_r2 & 0xFFFF
        elif isinstance(signal, WriteCstrChar):
            dp.data_memory[dp.a[dp.op0_payload]] = dp.shadow_r2 & 0xFF
        elif isinstance(signal, HaltSignal):
            self.halted = True
        elif isinstance(signal, LatchMpc):
            self._latch_mpc(signal.select)
        else:
            raise ValueError(f"Unsupported signal: {signal}")

    def tick(self) -> None:
        self.last_io_event = ""
        signals = self.microcode[self.upc]
        for signal in signals:
            self._dispatch_signal(signal)

    def _branch(self) -> None:
        op = self.datapath.current_op()
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
        self.datapath.shadow_r0 = value
        self.datapath.execute_alu(AluOp.PASS, value)
        self.last_io_event = (
            f"IN[{port}] -> {self._format_operand(self.datapath.operand(1))}={value}"
        )

    def _output(self) -> None:
        port = self._read_operand(1)
        if port != 0:
            raise ValueError(f"Unsupported output port: {port}")
        value = self._read_operand(0) & 0xFF
        self.datapath.output_buffer.append(value)
        self.last_io_event = f"OUT[{port}] <- value={value}"


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
                + f"R1={dp.r[1]} R2={dp.r[2]} R3={dp.r[3]} "
                + f"A1={dp.a[1]:04X} A2={dp.a[2]:04X} A3={dp.a[3]:04X} "
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
