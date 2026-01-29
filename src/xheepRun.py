import argparse
import socket
import struct
import subprocess
import sys
import time
import telnetlib
from pathlib import Path
from typing import Iterable, Optional, Tuple

from xheepDriver import xheepDriver


RESET = "\033[0m"
COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m\033[97m",
}

def log(level: str, msg: str, stderr: Optional[bool] = None) -> None:
    lvl = level.upper()
    color = COLORS.get(lvl, "")
    if stderr is None:
        use_stderr = (lvl in ("WARNING", "ERROR", "CRITICAL"))
    else:
        use_stderr = stderr

    stream = sys.stderr if use_stderr else sys.stdout
    stream.write(f"{color}[{lvl}] {msg}{RESET}\n")
    stream.flush()


def wait_for_tcp(host: str, port: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Optional[Exception] = None

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as e:
            last_err = e
            time.sleep(0.1)

    log("critical", f"Timeout waiting for {host}:{port} ({last_err})")
    raise TimeoutError(f"{host}:{port}")


def openocd_telnet_batch(cmds: Iterable[str], host: str = "127.0.0.1", port: int = 4444, timeout_s: float = 30.0) -> str:
    token = f"__XHEEP_DONE_{time.monotonic_ns()}_ns__"
    token_b = token.encode("utf-8")
    token_pat = b"\n" + token_b

    tn = telnetlib.Telnet(host, port, timeout=timeout_s)
    tn.read_until(b">", timeout=timeout_s)

    for c in cmds:
        tn.write(c.encode("utf-8") + b"\n")

    tn.write(b"echo " + token_b + b"\n")

    buf = tn.read_until(token_pat, timeout=timeout_s)
    tail = tn.read_until(b">", timeout=timeout_s)

    text = (buf + tail).decode("utf-8", errors="replace")
    cut = text.find("\n" + token)
    if cut != -1:
        text = text[:cut]

    return text


def start_openocd(cfg_path: Path, log_file: Optional[Path], xvc_dev_addr: int ) -> Tuple[subprocess.Popen, Optional[object]]:
    argv = [
        "openocd",
        "-c",
        f"set XVC_DEV_ADDR 0x{xvc_dev_addr:08x}",
        "-f",
        str(cfg_path),
    ]
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_file, "wb", buffering=0)
    proc = subprocess.Popen(argv, stdout=fh, stderr=fh)

    return proc, fh


def shutdown_openocd(proc: subprocess.Popen, fh: Optional[object]) -> None:
    try:
        openocd_telnet_batch(["shutdown"], timeout_s=5.0)
    except Exception:
        pass

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    if fh is not None:
        try:
            fh.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--overlay", required=True, help="Path to .bit overlay")
    ap.add_argument("-f", "--firmware", required=True, help="Path to firmware .elf")
    ap.add_argument("--verify", action="store_true", help="Run verify_image after load_image")
    args = ap.parse_args()

    bitfile = Path(args.overlay).resolve()
    fwfile = Path(args.firmware).resolve()
    cfgfile = Path("cfg/xheep_xilinx_xvc.cfg").resolve()

    for p, label in ((bitfile, "overlay"), (fwfile, "firmware"), (cfgfile, "cfg")):
        if not p.is_file():
            log("critical", f"Missing {label} file: {p}")
            return 2

    run_dir = Path("xheep_logs")
    run_dir.mkdir(parents=True, exist_ok=True)

    openocd_log = run_dir / "openocd.log"

    xheep = xheepDriver(str(bitfile))

    xvc_addr = xheep.jtag.getAddr()

    input("Press Enter to program and run the application...")

    xheep.gpio.bootFromJTAG()

    xheep.gpio.resetJTAG()
    xheep.gpio.resetXheep()
    time.sleep(0.05)

    v, e = xheep.gpio.getExitCode()
    if v == 1 or e == 1:
        log("warning", f"Exit bits already set before run: exit_valid={v} exit_value={e}")

    hdr = fwfile.read_bytes()[:0x34]
    entry = struct.unpack_from("<I", hdr, 0x18)[0]

    proc, proc_fh = start_openocd(cfgfile, openocd_log, xvc_addr)

    try:
        time.sleep(0.2)
        if proc.poll() is not None:
            log("critical", f"OpenOCD exited early with code {proc.returncode}. Check {openocd_log}")
            return 1

        wait_for_tcp("127.0.0.1", 4444, timeout_s=10.0)

        fwq = "{" + str(fwfile).replace("}", r"\}") + "}"
        cmds = ["targets riscv0", "halt", f"load_image {fwq}"]
        if args.verify:
            cmds.append(f"verify_image {fwq}")

        output = openocd_telnet_batch(cmds, timeout_s=60.0)

        if args.verify:
            if "verified" in output.lower() and "error" not in output.lower():
                log("info", "Firmware verification: PASSED")
            else:
                log("error", "Firmware verification: FAILED")
                log("error", f"Verify output: {output}")

        openocd_telnet_batch(["targets riscv0", f"resume 0x{entry:08x}"], timeout_s=15.0)

        v, e = xheep.gpio.getExitCode()
        while not v:
            time.sleep(10 / 1000.0)
            v, e = xheep.gpio.getExitCode()

        log("info", f"Exit status: exit_valid={v} exit_value={e}")
        return 0 if e == 0 else 1

    except KeyboardInterrupt:
        log("warning", "Interrupted by user (Ctrl+C)...")
        v, e = xheep.gpio.getExitCode()
        log("info", f"Exit status: exit_valid={v} exit_value={e}")
        return 130

    finally:
        if proc.poll() is None:
            shutdown_openocd(proc, proc_fh)
        else:
            if proc_fh is not None:
                try:
                    proc_fh.close()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
