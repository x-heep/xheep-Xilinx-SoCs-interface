import argparse
import hashlib
import socket
import struct
import subprocess
import sys
import time
import telnetlib
from pathlib import Path
from typing import Optional, Tuple

STATE_FILE = Path("/tmp/.xheep_state")

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

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--overlay", required=True, help="Path to .bit")
    ap.add_argument("-f", "--firmware", required=True, help="Path to .elf")
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

    # Lazy import - only when needed
    from xheepDriver import xheepDriver, xheepUART, xheepGPIO, xheepJTAG
    from pynq import Overlay, PL, MMIO

    if need_reload:
        xheep = xheepDriver(str(bit))
        save_state(cur_hash)
    else:
        # Skip PL reset, just reconnect to existing hardware
        ol = Overlay(str(bit), download=False)
        gpio_ip = ol.ip_dict["axi_gpio"]
        uart_ip = ol.ip_dict["axi_uartlite"]
        jtag_ip = ol.ip_dict["axi_jtag"]
        
        class _Stub:
            def __init__(self):
                self.gpio = xheepGPIO(ol, int(gpio_ip["phys_addr"]), int(gpio_ip["addr_range"]))
                self.jtag = xheepJTAG(ol, int(jtag_ip["phys_addr"]), int(jtag_ip["addr_range"]))
        
        xheep = _Stub()

    xvc_addr = xheep.jtag.getAddr()

    input("Press Enter to program and run...")

    xheep.gpio.bootFromJTAG()
    xheep.gpio.resetJTAG()
    xheep.gpio.resetXheep()
    time.sleep(0.05)

    v, e = xheep.gpio.getExitCode()
    if v == 1 or e == 1:
        print(f"[WARN] Exit bits set: {v},{e}", file=sys.stderr)

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
                pass
            else:
                print("[WARN] Verification failed", file=sys.stderr)

        ocd_cmd(["targets riscv0", f"resume 0x{entry:08x}"], timeout=15.0)

        v, e = xheep.gpio.getExitCode()
        while not v:
            time.sleep(0.01)
            v, e = xheep.gpio.getExitCode()

        print(f"exit_valid={v} | exit_value={e}")
        return 0 if e == 0 else 1

    except KeyboardInterrupt:
        v, e = xheep.gpio.getExitCode()
        print(f"Interrupted: {v},{e}")
        return 130

    finally:
        shutdown_ocd(proc, fh)


if __name__ == "__main__":
    raise SystemExit(main())
