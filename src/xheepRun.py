import argparse
import hashlib
import os
import socket
import struct
import subprocess
import sys
import time
import telnetlib
import serial
from pathlib import Path
from typing import Optional, Tuple

STATE_FILE = Path("/tmp/.xheep_state")
TTY_DEVICE = "/dev/ttyUL0"

def flush_uart():
    """ Flush UART RX/TX buffers to avoid stale data """
    try:
        ser = serial.Serial(TTY_DEVICE, 9600, timeout=0.1)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.close()
    except:
        pass

def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def load_state() -> Optional[str]:
    if STATE_FILE.exists():
        try:
            return STATE_FILE.read_text().strip()
        except:
            pass
    return None

def save_state(bit_hash: str):
    try:
        STATE_FILE.write_text(bit_hash)
    except:
        pass

def wait_tcp(host: str, port: int, timeout: float):
    dl = time.monotonic() + timeout
    while time.monotonic() < dl:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except:
            time.sleep(0.1)
    raise TimeoutError(f"{host}:{port}")

def ocd_cmd(cmds, host="127.0.0.1", port=4444, timeout=30.0) -> str:
    tok = f"__D{time.monotonic_ns()}__"
    tn = telnetlib.Telnet(host, port, timeout=timeout)
    tn.read_until(b">", timeout=timeout)
    for c in cmds:
        tn.write(c.encode() + b"\n")
    tn.write(f"echo {tok}\n".encode())
    buf = tn.read_until(tok.encode(), timeout=timeout)
    return buf.decode(errors="replace")

def start_ocd(cfg: Path, log: Path, addr: int) -> Tuple[subprocess.Popen, object]:
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log, "wb", buffering=0)
    proc = subprocess.Popen(
        ["openocd", "-c", f"set XVC_DEV_ADDR 0x{addr:08x}", "-f", str(cfg)],
        stdout=fh, stderr=fh
    )
    return proc, fh

def shutdown_ocd(proc, fh):
    try:
        ocd_cmd(["shutdown"], timeout=3.0)
    except:
        pass
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except:
            proc.kill()
            proc.wait()
    if fh:
        try:
            fh.close()
        except:
            pass

def _score_text(s: str, keywords: list[tuple[str, int]]) -> int:
    s = (s or "").lower()
    score = 0
    for kw, w in keywords:
        if kw in s:
            score += w
    return score

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--overlay", required=True, help="Path to .bit")
    ap.add_argument("-f", "--firmware", required=True, help="Path to .elf or .bin")
    ap.add_argument("-m", "--memory", choices=["on_chip", "flash_load", "flash_exec"], 
                    default="on_chip", help="Execution mode")
    ap.add_argument("--verify", action="store_true", help="Verify after load")
    ap.add_argument("--force", action="store_true", help="Force PL reload")
    args = ap.parse_args()

    bit = Path(args.overlay).resolve()
    fw = Path(args.firmware).resolve()
    cfg = Path("cfg/xheep_xilinx_xvc.cfg").resolve()

    for p, l in ((bit, "overlay"), (fw, "firmware"), (cfg, "cfg")):
        if not p.is_file():
            print(f"[ERROR] Missing {l}: {p}", file=sys.stderr)
            return 2

    log_dir = Path("xheep_logs")
    ocd_log = log_dir / "openocd.log"

    # Check if bitstream changed
    cur_hash = file_hash(bit)
    prev_hash = load_state()
    need_reload = args.force or (cur_hash != prev_hash)

    # Import drivers
    from xheepDriver import xheepDriver, xheepGPIO, xheepJTAG, xheepSPI, xheepFlashProgrammer
    from pynq import Overlay

    if need_reload:
        print("[INFO] Loading bitstream...")
        xheep = xheepDriver(str(bit))
        save_state(cur_hash)
    else:
        print("[INFO] Reusing existing bitstream...")
        ol = Overlay(str(bit), download=False)
        gpio_ip = ol.ip_dict["axi_gpio"]
        jtag_ip = ol.ip_dict["axi_jtag"]
        spi_ip = ol.ip_dict.get("axi_quad_spi")
        
        class _Stub:
            def __init__(self):
                self.gpio = xheepGPIO(ol, int(gpio_ip["phys_addr"]), int(gpio_ip["addr_range"]))
                self.jtag = xheepJTAG(ol, int(jtag_ip["phys_addr"]), int(jtag_ip["addr_range"]))
                if spi_ip:
                    # SPI IRQ is at concat position 2 (In2), UART is at position 0 (In0)
                    # So SPI_IRQ = UART_IRQ + 2
                    board = os.getenv("BOARD", "pynq-z2").lower()
                    if board == "aup-zu3":
                        spi_irq = 92  # UltraScale+: UART=90 (In0), In1=91, SPI=92 (In2)
                    else:
                        spi_irq = 32  # Zynq-7000: UART=30 (In0), In1=31, SPI=32 (In2)
                    # Use MTD mode for Quad SPI
                    self.spi = xheepSPI(int(spi_ip["phys_addr"]), spi_irq, use_mtd=True)
                    # Note: don't bind here - we'll use direct MMIO for flash programming
                    self.flash_programmer = xheepFlashProgrammer(int(spi_ip["phys_addr"]), self.gpio)
                else:
                    self.spi = None
                    self.flash_programmer = None
        
        xheep = _Stub()

    xvc_addr = xheep.jtag.getAddr()

    # Handle flash operations using direct MMIO (does not require kernel drivers)
    if args.memory in ["flash_load", "flash_exec"]:
        # Need .bin file for flash
        if fw.suffix == ".elf":
            bin_file = fw.with_suffix(".bin")
            if not bin_file.exists():
                print(f"[ERROR] Flash mode requires .bin file", file=sys.stderr)
                return 2
        else:
            bin_file = fw

        # Check if flash programmer is available
        if not getattr(xheep, "flash_programmer", None):
            print("[ERROR] Flash programmer not available (no SPI IP found)", file=sys.stderr)
            return 2

        # Note: SPI kernel driver is no longer bound by xheepDriver
        # (we use direct MMIO instead to avoid state corruption issues)

        # Switch mux to PS control
        print("[INFO] Switching SPI flash to PS control...")
        xheep.gpio.setSpiFlashControl(True)
        time.sleep(0.2)

        # Program flash using direct MMIO
        ok = False
        try:
            print(f"[INFO] Programming flash with: {bin_file}")
            ok = xheep.flash_programmer.program_file(bin_file, verify=args.verify)
        except Exception as e:
            print(f"[ERROR] Flash programming failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            ok = False
        finally:
            # Always switch back to X-HEEP control
            print("[INFO] Switching SPI flash to X-HEEP control...")
            xheep.gpio.setSpiFlashControl(False)
            time.sleep(0.05)

        if not ok:
            return 1
    print("\nPress Enter to program and run X-HEEP...")
    print("(This is a good time to open a UART terminal: screen /dev/ttyUL0 9600)")
    input()

    # Ensure X-HEEP has flash control before starting execution
    # (GPIO starts with PS control to prevent flash corruption during setup)
    xheep.gpio.setSpiFlashControl(False)

    # Configure boot mode
    if args.memory == "on_chip":
        xheep.gpio.bootFromJTAG()
    elif args.memory == "flash_load":
        xheep.gpio.loadFromFlash()
    elif args.memory == "flash_exec":
        xheep.gpio.execFromFlash()

    xheep.gpio.resetJTAG()
    xheep.gpio.resetXheep()
    time.sleep(0.1)

    v, e = xheep.gpio.getExitCode()
    if v == 1 or e == 1:
        print(f"[WARN] Exit bits set before start: valid={v}, value={e}", file=sys.stderr)

    # For flash_exec, we don't load via JTAG
    if args.memory == "flash_exec":
        print("[INFO] X-HEEP is executing from flash...")
        print("[INFO] Waiting for completion...")
        
        v, e = xheep.gpio.getExitCode()
        timeout = time.time() + 30
        while not v and time.time() < timeout:
            time.sleep(0.01)
            v, e = xheep.gpio.getExitCode()
        
        if not v:
            print("[WARN] Timeout waiting for completion", file=sys.stderr)
        
        print(f"exit_valid={v} | exit_value={e}")
        return 0 if e == 0 else 1

    # JTAG loading path
    entry = struct.unpack_from("<I", fw.read_bytes()[:0x34], 0x18)[0]
    proc, fh = start_ocd(cfg, ocd_log, xvc_addr)

    try:
        time.sleep(0.2)
        if proc.poll() is not None:
            print(f"[ERROR] OpenOCD failed, see {ocd_log}", file=sys.stderr)
            return 1

        wait_tcp("127.0.0.1", 4444, 10.0)

        fwq = "{" + str(fw).replace("}", r"\}") + "}"
        cmds = ["targets riscv0", "halt", f"load_image {fwq}"]
        if args.verify:
            cmds.append(f"verify_image {fwq}")

        out = ocd_cmd(cmds, timeout=60.0)
        if args.verify:
            if "verified" in out.lower() and "error" not in out.lower():
                print("[INFO] Verification passed")
            else:
                print("[WARN] Verification failed", file=sys.stderr)

        flush_uart()
        ocd_cmd(["targets riscv0", f"resume 0x{entry:08x}"], timeout=15.0)

        print("[INFO] Waiting for execution to complete...")
        v, e = xheep.gpio.getExitCode()
        timeout = time.time() + 30
        while not v and time.time() < timeout:
            time.sleep(0.01)
            v, e = xheep.gpio.getExitCode()

        if not v:
            print("[WARN] Timeout waiting for completion", file=sys.stderr)
        
        print(f"exit_valid={v} | exit_value={e}")
        return 0 if e == 0 else 1

    except KeyboardInterrupt:
        v, e = xheep.gpio.getExitCode()
        print(f"Interrupted: valid={v}, value={e}")
        return 130

    finally:
        shutdown_ocd(proc, fh)


if __name__ == "__main__":
    raise SystemExit(main())