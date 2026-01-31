import argparse
import hashlib
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
    """Flush UART RX/TX buffers to avoid stale data."""
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

def flash_write_mtd(bin_file: Path, mtd_dev: Path) -> bool:
    """Write binary to SPI flash using MTD"""
    print(f"[INFO] Programming SPI flash: {bin_file} -> {mtd_dev}")
    
    file_size = bin_file.stat().st_size
    print(f"[INFO] Binary size: {file_size} bytes ({file_size/1024:.1f} KB)")
    
    try:
        # Erase the flash
        print("[INFO] Erasing flash...")
        result = subprocess.run(
            ["flash_erase", str(mtd_dev), "0", "0"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"[ERROR] Flash erase failed: {result.stderr}")
            return False
        
        # Write the binary
        print("[INFO] Writing flash...")
        with open(mtd_dev, 'wb') as mtd:
            data = bin_file.read_bytes()
            mtd.write(data)
            mtd.flush()
        
        print(f"[INFO] Successfully wrote {file_size} bytes")
        print("[INFO] ✓ Flash programming complete!")
        return True
            
    except FileNotFoundError:
        print(f"[ERROR] MTD tools not found. Install with: apt-get install mtd-utils")
        return False
    except Exception as e:
        print(f"[ERROR] MTD flash write failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def flash_write_flashrom(bin_file: Path, spi_dev: Path) -> bool:
    """Write binary to SPI flash using flashrom (no verify)"""
    print(f"[INFO] Programming SPI flash: {bin_file} -> {spi_dev}")
    
    file_size = bin_file.stat().st_size
    print(f"[INFO] Binary size: {file_size} bytes ({file_size/1024:.1f} KB)")
    
    print("[INFO] Writing flash with flashrom...")
    try:
        result = subprocess.run(
            ["flashrom", "-p", f"linux_spi:dev={spi_dev}", "-w", str(bin_file), "-n"],
            capture_output=True, text=True, timeout=120
        )
        
        if result.returncode != 0:
            print(f"[ERROR] flashrom failed: {result.stderr}")
            return False
        else:
            print("[INFO] ✓ Flash programming complete!")
            return True
            
    except FileNotFoundError:
        print("[ERROR] flashrom not installed. Install with: apt-get install flashrom")
        return False
    except subprocess.TimeoutExpired:
        print("[ERROR] Flash programming timed out")
        return False
    except Exception as e:
        print(f"[ERROR] Flash programming failed: {e}")
        return False

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
    from xheepDriver import xheepDriver, xheepGPIO, xheepJTAG, xheepSPI
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
                    self.spi = xheepSPI(int(spi_ip["phys_addr"]), 62)
                    self.spi.bind()  # Bind overlay when reusing
                else:
                    self.spi = None
        
        xheep = _Stub()

    xvc_addr = xheep.jtag.getAddr()

    # Handle flash operations
    if args.memory in ["flash_load", "flash_exec"]:
        if not xheep.spi:
            print(f"[ERROR] SPI IP not available. Cannot use flash modes.", file=sys.stderr)
            return 1
        
        # Need .bin file for flash
        if fw.suffix == ".elf":
            bin_file = fw.with_suffix(".bin")
            if not bin_file.exists():
                print(f"[ERROR] Flash mode requires .bin file. Convert {fw} to {bin_file}", file=sys.stderr)
                print("[INFO] Use: riscv32-unknown-elf-objcopy -O binary firmware.elf firmware.bin", file=sys.stderr)
                return 2
        else:
            bin_file = fw
        
        # Switch to PS control
        print("[INFO] Switching SPI flash to PS control...")
        xheep.gpio.setSpiFlashControl(True)
        
        # Get MTD device (preferred) or SPI device (fallback)
        mtd_dev = xheep.spi.getMtdDev()
        spi_dev = xheep.spi.getSpiDev()
        
        if mtd_dev and mtd_dev.exists():
            print(f"[INFO] Using MTD device: {mtd_dev}")
            if not flash_write_mtd(bin_file, mtd_dev):
                xheep.gpio.setSpiFlashControl(False)
                return 1
        elif spi_dev and spi_dev.exists():
            print(f"[INFO] Using SPI device: {spi_dev} (MTD not available)")
            if not flash_write_flashrom(bin_file, spi_dev):
                xheep.gpio.setSpiFlashControl(False)
                return 1
        else:
            print(f"[ERROR] No MTD or SPI device found", file=sys.stderr)
            xheep.gpio.setSpiFlashControl(False)
            return 1
        
        # Switch back to X-HEEP control
        print("[INFO] Switching SPI flash to X-HEEP control...")
        xheep.gpio.setSpiFlashControl(False)

    print("\nPress Enter to program and run X-HEEP...")
    print("(This is a good time to open a UART terminal: screen /dev/ttyUL0 9600)")
    input()

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