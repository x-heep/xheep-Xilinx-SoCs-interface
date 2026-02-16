from pathlib import Path
import os
import sys
import time
import subprocess
import stat
from typing import Optional, Tuple

from pynq import Overlay, PL, MMIO

RESET = "\033[0m"
COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m\033[97m",
}

def log(level: str, msg: str, stderr: bool | None = None) -> None:
    lvl = level.upper()
    color = COLORS.get(lvl, "")
    if stderr is None:
        use_stderr = (lvl in ("WARNING", "ERROR", "CRITICAL"))
    else:
        use_stderr = stderr
    stream = sys.stderr if use_stderr else sys.stdout
    stream.write(f"{color}[{lvl}] {msg}{RESET}\n")
    stream.flush()


class xheepGPIO:
    # AXI GPIO register offsets
    CH1_DATA = 0x00
    CH1_TRI  = 0x04
    CH2_DATA = 0x08
    CH2_TRI  = 0x0C

    BIT_RST_NI    = 0     # rst_ni
    BIT_BOOTSEL   = 1     # boot_select_i
    BIT_EXECFLASH = 2     # execute_from_flash_i
    BIT_TRST_NI   = 3     # jtag_trst_ni
    BIT_SPI_SEL   = 4     # SPI flash mux select (0=X-HEEP, 1=PS)

    EXIT_VALID = 0
    EXIT_VALUE = 1

    def __init__(self, overlay: Overlay, memAddr: int, memRng: int):
        self._ol = overlay
        self._mmio = MMIO(memAddr, memRng)

        # Set direction: CH1 = output, CH2 = input
        self._mmio.write(self.CH1_TRI, 0x0)
        self._mmio.write(self.CH2_TRI, 0x3)
        
        # Initialize GPIO values:
        # IMPORTANT: Start with PS controlling flash (SPI_SEL=1) to prevent
        # X-HEEP from sending garbage to flash before we configure things.
        # This matches what debug_spi.py does and avoids JEDEC read issues.
        # bit 0: rst_ni = 1 (not in reset)
        # bit 1: boot_select = 0 (JTAG boot)
        # bit 2: execute_from_flash = 0
        # bit 3: jtag_trst_ni = 1 (not in reset)
        # bit 4: spi_sel = 1 (PS control - prevents X-HEEP from touching flash)
        initial_val = (1 << self.BIT_RST_NI) | (1 << self.BIT_TRST_NI) | (1 << self.BIT_SPI_SEL)
        self._mmio.write(self.CH1_DATA, initial_val)
        time.sleep(10e-3)

    def setBit(self, channel: int, bit: int, value: bool):
        reg = int(self._mmio.read(channel << 3))
        reg = (reg | (1 << bit)) if value else (reg & ~(1 << bit))
        self._mmio.write(channel << 3, reg)

    def getBit(self, channel: int, bit: int) -> int:
        return (int(self._mmio.read(channel << 3)) >> bit) & 0x1

    def setChannel(self, value: int) -> None:
        self._mmio.write(self.CH1_DATA, (value & 0x1F))

    def getChannel(self, channel: int) -> int:
        return int(self._mmio.read(channel << 3))

    def setSpiFlashControl(self, use_ps: bool) -> None:
        """
        Set SPI flash control: True=PS, False=X-HEEP.
        When enabling PS control, set ALL GPIO bits high (0x1F) like debug_spi.py does.
        """
        # Read current value
        current = int(self._mmio.read(self.CH1_DATA))
        
        if use_ps:
            # Set ALL bits to 1 (0x1F) - this is what debug_spi.py does and it works
            # bit 0: rst_ni = 1
            # bit 1: boot_select = 1  
            # bit 2: execute_from_flash = 1
            # bit 3: jtag_trst_ni = 1
            # bit 4: spi_sel = 1 (PS control)
            new_val = 0x1F
        else:
            # Keep rst/jtag high, clear spi_sel
            new_val = (1 << self.BIT_RST_NI) | (1 << self.BIT_TRST_NI)
        
        self._mmio.write(self.CH1_DATA, new_val)
        time.sleep(20e-3)  # Wait for mux to settle

    def resetXheep(self) -> None:
        self.setBit(0, self.BIT_RST_NI, 0)
        time.sleep(1e-3)
        self.setBit(0, self.BIT_RST_NI, 1)
        time.sleep(1e-3)

    def resetJTAG(self) -> None:
        self.setBit(0, self.BIT_TRST_NI, 0)
        time.sleep(1e-3)
        self.setBit(0, self.BIT_TRST_NI, 1)
        time.sleep(1e-3)

    def bootFromJTAG(self) -> None:
        self.setBit(0, self.BIT_BOOTSEL, 0)
        self.setBit(0, self.BIT_EXECFLASH, 0)

    def loadFromFlash(self) -> None:
        self.setBit(0, self.BIT_BOOTSEL, 1)
        self.setBit(0, self.BIT_EXECFLASH, 0)

    def execFromFlash(self) -> None:
        self.setBit(0, self.BIT_BOOTSEL, 1)
        self.setBit(0, self.BIT_EXECFLASH, 1)

    def getExitCode(self) -> tuple[int, int]:
        exitVal = self.getChannel(1)
        exit_valid = (exitVal >> self.EXIT_VALID) & 0x1
        exit_value = (exitVal >> self.EXIT_VALUE) & 0x1
        return (exit_valid, exit_value)
    
    def getAddr(self) -> int:
        return self._mmio.base_addr


class xheepUART:
    DTS_PATCHED_PATH = Path("dts/uartlite-patched.dts")
    DTBO_PATH = Path("dts/uartlite-overlay.dtbo")

    OVERLAY_NAME = "uartlite"
    OVL_DIR = Path("/sys/kernel/config/device-tree/overlays") / OVERLAY_NAME
    DRIVER_NAME = "uartlite"
    TTY_NODE = Path("/dev/ttyUL0")

    TIMEOUT_S = 3.0
    POLL_S = 0.05

    def __init__(self, memAddr: int):
        self.memAddr = int(memAddr)
        self.PLATFORM_DEV = f"{self.memAddr:08x}.serial"
        
        board = os.getenv("BOARD", "pynq-z2").lower()
        if board == "aup-zu3":
            self.DTS_TEMPLATE_PATH = Path("dts/uartlite-ultrascale.tpl")
        else:
            self.DTS_TEMPLATE_PATH = Path("dts/uartlite-zynq.tpl")

    def _patchDts(self) -> None:
        content = self.DTS_TEMPLATE_PATH.read_text()
        patched = content.replace("########", f"{self.memAddr:08x}")
        self.DTS_PATCHED_PATH.write_text(patched)

    def _dtsCompile(self) -> None:
        argv = ["dtc", "-@", "-I", "dts", "-O", "dtb", "-o", str(self.DTBO_PATH), str(self.DTS_PATCHED_PATH)]
        cp = subprocess.run(argv, capture_output=True, text=True)
        if cp.returncode != 0:
            log("critical", f"dtc failed (rc={cp.returncode}). stderr: {cp.stderr or cp.stdout}")
            sys.exit(1)

    def _wait(self, cond_fn, timeout_s: float, what: str) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if cond_fn():
                return
            time.sleep(self.POLL_S)
        log("critical", f"Timeout waiting for: {what} (>{timeout_s:.2f}s)")
        sys.exit(1)

    def _pids_using_path(self, target: Path) -> list[tuple[int, str]]:
        if not target.exists():
            return []
        target_str = str(target)
        found: list[tuple[int, str]] = []
        for pid_s in os.listdir("/proc"):
            if not pid_s.isdigit():
                continue
            fd_dir = Path("/proc") / pid_s / "fd"
            try:
                for fd in os.listdir(fd_dir):
                    try:
                        link = os.readlink(fd_dir / fd)
                        if link == target_str or os.path.realpath(link) == os.path.realpath(target_str):
                            comm = (Path("/proc") / pid_s / "comm").read_text(encoding="utf-8", errors="ignore").strip() or "unknown"
                            found.append((int(pid_s), comm))
                            break
                    except Exception:
                        continue
            except Exception:
                continue
        return found

    def unbind(self) -> None:
        if self.TTY_NODE.exists():
            holders = self._pids_using_path(self.TTY_NODE)
            if holders:
                details = ", ".join([f"{pid}({comm})" for pid, comm in holders])
                log("critical", f"{self.TTY_NODE} is busy (open by: {details})")
                sys.exit(1)

        dev = Path("/sys/bus/platform/devices") / self.PLATFORM_DEV
        driver_link = dev / "driver"

        if driver_link.exists():
            try:
                drv_name = Path(os.readlink(driver_link)).name
                unbind_path = Path("/sys/bus/platform/drivers") / drv_name / "unbind"
                unbind_path.write_text(self.PLATFORM_DEV, encoding="utf-8")
                self._wait(lambda: not driver_link.exists(), self.TIMEOUT_S, "driver unbind")
            except Exception as e:
                log("critical", f"Driver unbind failed: {e}")
                sys.exit(1)

        if self.OVL_DIR.exists():
            try:
                os.rmdir(self.OVL_DIR)
                self._wait(lambda: not self.OVL_DIR.exists(), self.TIMEOUT_S, "overlay removal")
            except Exception as e:
                log("critical", f"Failed to remove device tree overlay: {e}")
                sys.exit(1)

        self._wait(lambda: not dev.exists(), self.TIMEOUT_S, "platform device disappearance")
        self._wait(lambda: not self.TTY_NODE.exists(), self.TIMEOUT_S, "tty node removal")

    def bind(self) -> None:
        self._patchDts()
        self._dtsCompile()

        base = Path("/sys/kernel/config/device-tree/overlays")
        if not base.exists():
            log("critical", f"Configfs DT overlays not mounted: {base}")
            sys.exit(1)

        if self.OVL_DIR.exists():
            log("critical", f"Overlay dir already exists: {self.OVL_DIR}. Try unbinding first.")
            sys.exit(1)

        try:
            self.OVL_DIR.mkdir(parents=True, exist_ok=False)
            (self.OVL_DIR / "dtbo").write_bytes(self.DTBO_PATH.read_bytes())
        except Exception as e:
            if self.OVL_DIR.exists():
                try:
                    os.rmdir(self.OVL_DIR)
                except Exception:
                    pass
            log("critical", f"Failed to load DTBO: {e}")
            sys.exit(1)

        dev = Path("/sys/bus/platform/devices") / self.PLATFORM_DEV
        self._wait(lambda: dev.exists(), self.TIMEOUT_S, "platform device appearance")

        driver_link = dev / "driver"
        if not driver_link.exists():
            bind_path = Path("/sys/bus/platform/drivers") / self.DRIVER_NAME / "bind"
            if not bind_path.exists():
                subprocess.run(["modprobe", self.DRIVER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if not bind_path.exists():
                    log("critical", f"Driver '{self.DRIVER_NAME}' not found in kernel.")
                    sys.exit(1)
            try:
                bind_path.write_text(self.PLATFORM_DEV, encoding="utf-8")
            except OSError as e:
                if e.errno != 16:
                    log("critical", f"Driver bind failed (OSError {e.errno}): {e.strerror}")
                    log("error", "Check 'dmesg' for hardware/interrupt mismatches.")
                    sys.exit(1)
            except Exception as e:
                log("critical", f"Driver bind failed: {e}")
                sys.exit(1)

        self._wait(lambda: (dev / "driver").exists(), self.TIMEOUT_S, "driver bind confirmation")
        self._wait(lambda: self.TTY_NODE.exists(), self.TIMEOUT_S, "tty node creation")

        try:
            file_stats = self.TTY_NODE.stat()
            if not stat.S_ISCHR(file_stats.st_mode):
                log("critical", f"{self.TTY_NODE} exists but is not a character device.")
                sys.exit(1)
        except Exception as e:
            log("critical", f"Cannot access device node: {e}")
            sys.exit(1)

    def getAddr(self) -> int:
        return self.memAddr


class xheepSPI:
    DTS_PATCHED_PATH = Path("dts/spi-patched.dts")
    DTBO_PATH = Path("dts/spi-overlay.dtbo")

    OVERLAY_NAME = "axiquadspi"
    OVL_DIR = Path("/sys/kernel/config/device-tree/overlays") / OVERLAY_NAME
    
    TIMEOUT_S = 5.0
    POLL_S = 0.05

    def __init__(self, memAddr: int, irqId: int = 62, use_mtd: bool = True):
        self.memAddr = int(memAddr)
        self.irqId = int(irqId)
        self.PLATFORM_DEV = f"{self.memAddr:08x}.spi"
        self.use_mtd = use_mtd

        board = os.getenv("BOARD", "pynq-z2").lower()
        if board == "aup-zu3":
            # Use MTD template for QSPI mode (creates /dev/mtdX)
            if use_mtd:
                self.DTS_TEMPLATE_PATH = Path("dts/spi-ultrascale-mtd.tpl")
            else:
                self.DTS_TEMPLATE_PATH = Path("dts/spi-ultrascale.tpl")
        else:
            if use_mtd:
                self.DTS_TEMPLATE_PATH = Path("dts/spi-zynq-mtd.tpl")
            else:
                self.DTS_TEMPLATE_PATH = Path("dts/spi-zynq.tpl")
    
    def _score_text(self, s: str, keywords: list[tuple[str, int]]) -> int:
        s = (s or "").lower()
        score = 0
        for kw, w in keywords:
            if kw in s:
                score += w
        return score

    def _get_spi_device(self) -> Optional[Path]:
        """Find a likely SPI character device node (e.g., /dev/spidev0.0)."""
        spidev_dir = Path("/sys/class/spidev")
        candidates: list[tuple[int, Path]] = []

        if spidev_dir.exists():
            for node in spidev_dir.iterdir():
                dev = Path("/dev") / node.name
                if not dev.exists():
                    continue
                score = 0
                try:
                    of_node = node / "device" / "of_node"
                    if (of_node / "full_name").exists():
                        fn = (of_node / "full_name").read_text(encoding="utf-8", errors="ignore")
                        score += self._score_text(fn, [
                            ("qspi", 80), ("spi-nor", 80), ("spi_flash", 60), ("flash", 40), ("nor", 30)
                        ])
                except Exception:
                    pass
                candidates.append((score, dev))

        # Fallback: any /dev/spidev*
        if not candidates:
            for dev in sorted(Path("/dev").glob("spidev*")):
                if dev.exists():
                    candidates.append((0, dev))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _get_mtd_device(self) -> Optional[Path]:
        """Find a likely MTD node for the SPI flash (e.g., /dev/mtd0)."""
        mtd_dir = Path("/sys/class/mtd")
        if not mtd_dir.exists():
            return None

        candidates: list[tuple[int, Path]] = []
        for mtd in mtd_dir.iterdir():
            if not mtd.name.startswith("mtd"):
                continue

            # Skip mtdblock entries if present in sysfs view
            if mtd.name.startswith("mtdblock"):
                continue

            score = 0
            name = ""
            try:
                if (mtd / "name").exists():
                    name = (mtd / "name").read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                name = ""

            lname = name.lower()
            if "xheep-firmware" in lname:
                score += 200
            score += self._score_text(lname, [
                ("qspi", 80), ("spi-nor", 80), ("spi nor", 80), ("flash", 40), ("nor", 30),
                ("w25", 20), ("n25", 20), ("mt25", 20), ("micron", 10), ("winbond", 10),
            ])

            try:
                of_node = mtd / "device" / "of_node"
                if (of_node / "full_name").exists():
                    fn = (of_node / "full_name").read_text(encoding="utf-8", errors="ignore")
                    score += self._score_text(fn, [("qspi", 80), ("spi-nor", 80), ("spi_flash", 60), ("flash", 40), ("nor", 30)])
            except Exception:
                pass

            mtd_num = mtd.name.replace("mtd", "")
            dev = Path("/dev") / f"mtd{mtd_num}"
            if dev.exists():
                candidates.append((score, dev))

        if not candidates:
            # Last-resort fallback: pick the first /dev/mtdX
            devs = sorted(Path("/dev").glob("mtd[0-9]*"))
            return devs[0] if devs else None

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _patchDts(self) -> None:
        if not self.DTS_TEMPLATE_PATH.exists():
            log("critical", f"SPI DTS template not found: {self.DTS_TEMPLATE_PATH}")
            sys.exit(1)
        
        content = self.DTS_TEMPLATE_PATH.read_text()
        patched = content.replace("########", f"{self.memAddr:08x}")
        patched = patched.replace("INTERRUPT_ID", str(self.irqId))
        
        self.DTS_PATCHED_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.DTS_PATCHED_PATH.write_text(patched)

    def _dtsCompile(self) -> None:
        argv = ["dtc", "-@", "-I", "dts", "-O", "dtb", "-o", str(self.DTBO_PATH), str(self.DTS_PATCHED_PATH)]
        cp = subprocess.run(argv, capture_output=True, text=True)
        if cp.returncode != 0:
            log("critical", f"SPI dtc failed (rc={cp.returncode}). stderr: {cp.stderr or cp.stdout}")
            sys.exit(1)

    def _wait(self, cond_fn, timeout_s: float, what: str) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if cond_fn():
                return True
            time.sleep(self.POLL_S)
        return False

    def unbind(self) -> None:
        dev = Path("/sys/bus/platform/devices") / self.PLATFORM_DEV
        driver_link = dev / "driver"

        if driver_link.exists():
            try:
                drv_name = Path(os.readlink(driver_link)).name
                unbind_path = Path("/sys/bus/platform/drivers") / drv_name / "unbind"
                unbind_path.write_text(self.PLATFORM_DEV, encoding="utf-8")
                self._wait(lambda: not driver_link.exists(), self.TIMEOUT_S, "SPI driver unbind")
            except Exception as e:
                pass

        if self.OVL_DIR.exists():
            try:
                os.rmdir(self.OVL_DIR)
                self._wait(lambda: not self.OVL_DIR.exists(), self.TIMEOUT_S, "SPI overlay removal")
            except Exception as e:
                pass

    def bind(self) -> None:
        log("info", "Binding SPI device tree overlay...")

        self._patchDts()
        self._dtsCompile()

        base = Path("/sys/kernel/config/device-tree/overlays")
        if not base.exists():
            log("critical", f"Configfs DT overlays not mounted: {base}")
            sys.exit(1)

        if self.OVL_DIR.exists():
            try:
                os.rmdir(self.OVL_DIR)
                time.sleep(0.2)
            except Exception as e:
                log("warning", f"Could not remove existing overlay: {e}")

        try:
            self.OVL_DIR.mkdir(parents=True, exist_ok=False)
            (self.OVL_DIR / "dtbo").write_bytes(self.DTBO_PATH.read_bytes())
        except Exception as e:
            if self.OVL_DIR.exists():
                try:
                    os.rmdir(self.OVL_DIR)
                except:
                    pass
            log("error", f"Failed to load SPI DTBO: {e}")
            return

        dev = Path("/sys/bus/platform/devices") / self.PLATFORM_DEV
        if not self._wait(lambda: dev.exists(), self.TIMEOUT_S, "SPI platform device"):
            log("error", f"Platform device {self.PLATFORM_DEV} did not appear")
            return

        # Bind the SPI driver if not already bound
        driver_link = dev / "driver"
        if not driver_link.exists():
            # Try multiple possible driver names
            driver_names = ["xilinx_spi", "spi-xilinx"]
            bind_success = False

            for driver_name in driver_names:
                bind_path = Path("/sys/bus/platform/drivers") / driver_name / "bind"
                if not bind_path.exists():
                    # Try to load the module
                    subprocess.run(["modprobe", driver_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                if bind_path.exists():
                    try:
                        bind_path.write_text(self.PLATFORM_DEV, encoding="utf-8")
                        bind_success = True
                        break
                    except OSError as e:
                        if e.errno == 16:  # Device already bound
                            bind_success = True
                            break
                    except Exception as e:
                        pass

            if not bind_success:
                log("warning", "Could not bind SPI driver - device may still work if driver auto-binds")

        # Wait for driver bind confirmation
        if not self._wait(lambda: (dev / "driver").exists(), self.TIMEOUT_S, "SPI driver bind"):
            log("warning", "SPI driver not bound - communication may fail")

        # Wait for MTD or SPI device
        time.sleep(0.5)
        mtd_dev = self._get_mtd_device()
        spi_dev = self._get_spi_device()

        if mtd_dev:
            log("info", f"MTD device ready: {mtd_dev}")
        elif spi_dev:
            log("info", f"SPI device ready: {spi_dev}")
        else:
            log("warning", "No MTD or SPI device found")

    def getAddr(self) -> int:
        return self.memAddr
    
    def getSpiDev(self) -> Optional[Path]:
        return self._get_spi_device()
    
    def getMtdDev(self) -> Optional[Path]:
        return self._get_mtd_device()


class xheepFlashProgrammer:
    """
    Direct MMIO-based SPI flash programmer for X-HEEP on Xilinx platforms.
    Uses AXI Quad SPI IP to program external SPI NOR flash.
    Does NOT rely on kernel drivers (MTD/spidev) - works via direct register access.
    """
    
    # AXI Quad SPI register offsets (PG153)
    SRR         = 0x40  # Software Reset Register
    SPICR       = 0x60  # SPI Control Register
    SPISR       = 0x64  # SPI Status Register
    SPIDTR      = 0x68  # SPI Data Transmit Register
    SPIDRR      = 0x6C  # SPI Data Receive Register
    SPISSR      = 0x70  # SPI Slave Select Register
    TXFIFO_OCY  = 0x74  # TX FIFO Occupancy
    RXFIFO_OCY  = 0x78  # RX FIFO Occupancy
    
    # SPI Flash commands (compatible with W25Q128JV and similar)
    CMD_WRITE_ENABLE    = 0x06
    CMD_WRITE_DISABLE   = 0x04
    CMD_READ_STATUS1    = 0x05
    CMD_READ_STATUS2    = 0x35
    CMD_WRITE_STATUS    = 0x01
    CMD_PAGE_PROGRAM    = 0x02
    CMD_SECTOR_ERASE    = 0x20  # 4KB sector erase
    CMD_BLOCK_ERASE_32K = 0x52
    CMD_BLOCK_ERASE_64K = 0xD8
    CMD_CHIP_ERASE      = 0xC7
    CMD_READ_DATA       = 0x03
    CMD_FAST_READ       = 0x0B
    CMD_JEDEC_ID        = 0x9F
    CMD_RELEASE_PWRDOWN = 0xAB
    
    # Flash parameters
    PAGE_SIZE = 256
    SECTOR_SIZE = 4096
    
    # Status register bits
    STATUS_WIP  = 0x01  # Write In Progress
    STATUS_WEL  = 0x02  # Write Enable Latch
    STATUS_QE   = 0x02  # Quad Enable (in status register 2)
    
    def __init__(self, spi_addr: int, gpio: 'xheepGPIO'):
        """
        Initialize the flash programmer.
        
        Args:
            spi_addr: Physical address of AXI Quad SPI IP
            gpio: xheepGPIO instance for mux control
        """
        self.spi_addr = spi_addr
        self.spi = MMIO(spi_addr, 0x100)
        self.gpio = gpio
        self._initialized = False
        log("info", f"Flash programmer initialized at SPI address: 0x{spi_addr:08X}")
    
    def _spi_reset(self) -> None:
        """Reset the SPI controller."""
        self.spi.write(self.SRR, 0x0000000A)
        time.sleep(0.05)  # Increased delay for reset to complete
    
    def _spi_init(self) -> None:
        """Initialize SPI controller as master."""
        # Reset controller
        self._spi_reset()
        
        # Note: SPISR bit 5 (Slave_Mode) reads 1 even after reset - this is normal
        # for this AXI Quad SPI IP configuration (confirmed by debug_spi.py)
        
        # Configure: Master + SPE + Manual_SS + Reset FIFOs
        spicr = (1 << 6) | (1 << 5) | (1 << 2) | (1 << 1) | (1 << 7)
        self.spi.write(self.SPICR, spicr)
        time.sleep(0.01)
        
        # Clear FIFO reset bits, keep Master + SPE + Manual_SS + MTI
        spicr = (1 << 2) | (1 << 1) | (1 << 7) | (1 << 8)
        self.spi.write(self.SPICR, spicr)
        time.sleep(0.01)
        
        self._initialized = True
    
    def _cs_assert(self) -> None:
        """Assert chip select (active low)."""
        self.spi.write(self.SPISSR, 0xFFFFFFFE)
    
    def _cs_deassert(self) -> None:
        """Deassert chip select."""
        self.spi.write(self.SPISSR, 0xFFFFFFFF)
    
    def _wait_tx_empty(self, timeout_ms: int = 100) -> bool:
        """Wait for TX FIFO to empty."""
        for _ in range(timeout_ms):
            spisr = self.spi.read(self.SPISR)
            if spisr & (1 << 2):  # TX_Empty
                return True
            time.sleep(0.001)
        return False
    
    def _flush_rx(self) -> None:
        """Flush RX FIFO."""
        for _ in range(256):
            spisr = self.spi.read(self.SPISR)
            if spisr & (1 << 0):  # RX_Empty
                break
            self.spi.read(self.SPIDRR)
    
    def _start_transfer(self) -> None:
        """Start SPI transfer by clearing MTI bit."""
        spicr = self.spi.read(self.SPICR) & ~(1 << 8)
        self.spi.write(self.SPICR, spicr)
    
    def _stop_transfer(self) -> None:
        """Stop transfer by setting MTI bit."""
        spicr = self.spi.read(self.SPICR) | (1 << 8)
        self.spi.write(self.SPICR, spicr)
    
    FIFO_DEPTH = 16

    def _transfer(self, tx_data: bytes, rx_len: int = 0) -> bytes:
        """
        Perform SPI transaction with proper FIFO management.

        The AXI Quad SPI TX/RX FIFOs are 16 bytes deep. For transfers larger
        than 16 bytes (e.g. page_program=260, read_data=260), data is streamed
        through the FIFO in chunks. CS stays asserted (Manual_SS mode) and the
        SPI clock auto-restarts when new TX data is written with MTI=0.
        """
        tx_buf = bytes(tx_data) + bytes(rx_len)
        total = len(tx_buf)

        self._flush_rx()
        self._cs_assert()
        time.sleep(0.0001)

        rx_data = []
        offset = 0
        started = False

        while offset < total:
            # Fill TX FIFO with next chunk
            chunk = min(self.FIFO_DEPTH, total - offset)
            for i in range(chunk):
                self.spi.write(self.SPIDTR, tx_buf[offset + i])

            # Start transfer on first chunk (clear MTI)
            if not started:
                self._start_transfer()
                started = True

            # Wait for TX FIFO to empty (all bytes shifted out)
            if not self._wait_tx_empty(timeout_ms=1000):
                spisr = self.spi.read(self.SPISR)
                log("error", f"SPI timeout at offset {offset}/{total}, SPISR=0x{spisr:08X}")
                self._spi_init()
                return b''

            # Small delay for last byte to finish shifting
            time.sleep(0.001)

            # Drain RX FIFO (same number of bytes received)
            for _ in range(chunk):
                if self.spi.read(self.SPISR) & 1:  # RX_Empty
                    break
                rx_data.append(self.spi.read(self.SPIDRR) & 0xFF)

            offset += chunk

        self._stop_transfer()
        self._cs_deassert()

        return bytes(rx_data)
    
    def wake_up(self) -> None:
        """Wake flash from power-down mode."""
        self._transfer(bytes([self.CMD_RELEASE_PWRDOWN]), rx_len=3)
        time.sleep(0.01)  # tRES1 = 3us typical, use 10ms for safety
    
    def read_jedec_id(self) -> Tuple[int, int, int]:
        """Read JEDEC ID (Manufacturer, Memory Type, Capacity)."""
        rx = self._transfer(bytes([self.CMD_JEDEC_ID]), rx_len=3)
        if len(rx) >= 4:
            return (rx[1], rx[2], rx[3])
        return (0, 0, 0)
    
    def read_status1(self) -> int:
        """Read status register 1."""
        rx = self._transfer(bytes([self.CMD_READ_STATUS1]), rx_len=1)
        return rx[1] if len(rx) >= 2 else 0xFF
    
    def read_status2(self) -> int:
        """Read status register 2."""
        rx = self._transfer(bytes([self.CMD_READ_STATUS2]), rx_len=1)
        return rx[1] if len(rx) >= 2 else 0xFF
    
    def write_enable(self) -> None:
        """Enable write operations."""
        self._transfer(bytes([self.CMD_WRITE_ENABLE]))
        time.sleep(0.001)
    
    def write_disable(self) -> None:
        """Disable write operations."""
        self._transfer(bytes([self.CMD_WRITE_DISABLE]))
    
    def wait_busy(self, timeout_s: float = 30.0) -> bool:
        """Wait for flash to become ready."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = self.read_status1()
            if not (status & self.STATUS_WIP):
                return True
            time.sleep(0.01)
        return False
    
    def sector_erase(self, addr: int) -> bool:
        """Erase 4KB sector containing addr."""
        self.write_enable()
        cmd = bytes([self.CMD_SECTOR_ERASE, 
                     (addr >> 16) & 0xFF, 
                     (addr >> 8) & 0xFF, 
                     addr & 0xFF])
        self._transfer(cmd)
        return self.wait_busy(timeout_s=3.0)
    
    def chip_erase(self) -> bool:
        """Erase entire flash chip."""
        log("info", "Erasing entire flash (this may take a while)...")
        self.write_enable()
        self._transfer(bytes([self.CMD_CHIP_ERASE]))
        return self.wait_busy(timeout_s=120.0)
    
    def page_program(self, addr: int, data: bytes) -> bool:
        """Program a page (max 256 bytes) starting at addr."""
        if len(data) > self.PAGE_SIZE:
            data = data[:self.PAGE_SIZE]
        if not data:
            return True
        
        self.write_enable()
        cmd = bytes([self.CMD_PAGE_PROGRAM,
                     (addr >> 16) & 0xFF,
                     (addr >> 8) & 0xFF,
                     addr & 0xFF]) + data
        self._transfer(cmd)
        return self.wait_busy(timeout_s=5.0)
    
    def read_data(self, addr: int, length: int) -> bytes:
        """Read data from flash."""
        cmd = bytes([self.CMD_READ_DATA,
                     (addr >> 16) & 0xFF,
                     (addr >> 8) & 0xFF,
                     addr & 0xFF])
        rx = self._transfer(cmd, rx_len=length)
        return rx[4:] if len(rx) > 4 else b''
    
    def program_binary(self, data: bytes, start_addr: int = 0, 
                       verify: bool = True, erase: bool = True) -> bool:
        """
        Program binary data to flash.
        
        Args:
            data: Binary data to program
            start_addr: Starting address in flash
            verify: Verify after programming
            erase: Erase sectors before programming
        
        Returns:
            True if successful
        """
        # IMPORTANT: Set GPIO to PS control mode BEFORE touching SPI
        # This is exactly what debug_spi.py does
        self.gpio._mmio.write(0x00, 0x1F)  # Direct write like debug_spi.py
        time.sleep(0.1)  # Longer delay for mux to settle
        
        # Recreate MMIO object to ensure fresh hardware access (no stale cache)
        self.spi = MMIO(self.spi_addr, 0x100)
        time.sleep(0.05)
        
        # Always reinitialize SPI controller (in case kernel driver left it in bad state)
        # Note: SPISR bit 5 (Slave_Mode) reads 1 even in master mode for this IP
        # configuration - this is a hardware quirk, not an error. debug_spi.py
        # confirms the controller works correctly despite this bit being set.
        
        # Note: do NOT send wake_up (0xAB) here. The AXI Quad SPI IP is in
        # enhanced mode with a command lookup table - 0xAB is not recognized and
        # triggers Command_Error (SPISR bit 10), corrupting subsequent transfers.
        # debug_spi.py confirms the flash works without wake_up after power-on.

        # Read and verify JEDEC ID
        jedec = self.read_jedec_id()
        log("info", f"Flash JEDEC ID: {jedec[0]:02X} {jedec[1]:02X} {jedec[2]:02X}")
        
        if jedec[0] == 0xFF or jedec[0] == 0x00:
            log("error", "No flash detected or communication error")
            return False
        
        data_len = len(data)
        log("info", f"Programming {data_len} bytes ({data_len/1024:.1f} KB) starting at 0x{start_addr:06X}")
        
        # Calculate sectors to erase
        if erase:
            start_sector = start_addr // self.SECTOR_SIZE
            end_sector = (start_addr + data_len - 1) // self.SECTOR_SIZE
            num_sectors = end_sector - start_sector + 1
            log("info", f"Erasing {num_sectors} sectors...")
            
            for i in range(num_sectors):
                sector_addr = (start_sector + i) * self.SECTOR_SIZE
                if not self.sector_erase(sector_addr):
                    log("error", f"Failed to erase sector at 0x{sector_addr:06X}")
                    return False
                if (i + 1) % 16 == 0:
                    log("info", f"  Erased {i + 1}/{num_sectors} sectors")
            
            log("info", "Erase complete")
        
        # Program pages
        log("info", "Programming flash...")
        offset = 0
        page_count = 0
        total_pages = (data_len + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        
        while offset < data_len:
            addr = start_addr + offset
            page_data = data[offset:offset + self.PAGE_SIZE]
            
            if not self.page_program(addr, page_data):
                log("error", f"Failed to program page at 0x{addr:06X}")
                return False
            
            offset += len(page_data)
            page_count += 1
            
            if page_count % 64 == 0:
                progress = (page_count / total_pages) * 100
                log("info", f"  Programmed {page_count}/{total_pages} pages ({progress:.1f}%)")
        
        log("info", f"Programming complete: {page_count} pages written")
        
        # Verify
        if verify:
            log("info", "Verifying flash contents...")
            offset = 0
            errors = 0
            
            while offset < data_len:
                chunk_size = min(256, data_len - offset)
                addr = start_addr + offset
                read_data = self.read_data(addr, chunk_size)
                expected = data[offset:offset + chunk_size]
                
                if read_data != expected:
                    errors += 1
                    if errors <= 5:
                        log("error", f"Verification failed at 0x{addr:06X}")
                
                offset += chunk_size
                
                if offset % (64 * 256) == 0:
                    progress = (offset / data_len) * 100
                    log("info", f"  Verified {offset}/{data_len} bytes ({progress:.1f}%)")
            
            if errors > 0:
                log("error", f"Verification failed with {errors} errors")
                return False
        
        return True
    
    def program_file(self, filepath: Path, start_addr: int = 0,
                     verify: bool = True, erase: bool = True) -> bool:
        """
        Program binary file to flash.
        """
        if not filepath.exists():
            log("error", f"File not found: {filepath}")
            return False
        
        data = filepath.read_bytes()
        return self.program_binary(data, start_addr, verify, erase)


class xheepJTAG:
    def __init__(self, overlay: Overlay, memAddr: int, memRng: int):
        self._ol = overlay
        self.memAddr = int(memAddr)
        self.memRng = int(memRng)
        
    def getAddr(self) -> int:
        return self.memAddr


class xheepDriver(Overlay):
    IP_GPIO = "axi_gpio"
    IP_UART = "axi_uartlite"
    IP_JTAG = "axi_jtag"
    IP_SPI  = "axi_quad_spi"

    def __init__(self, overlay_path, **kwargs):
        overlay_path = Path(overlay_path)
        super().__init__(str(overlay_path), download=False, **kwargs)

        gpio_ip = self.ip_dict[self.IP_GPIO]
        uart_ip = self.ip_dict[self.IP_UART]
        jtag_ip = self.ip_dict[self.IP_JTAG]
        spi_ip  = self.ip_dict.get(self.IP_SPI)

        self.AXI_GPIO_ADDR = int(gpio_ip["phys_addr"])
        self.AXI_GPIO_RNG  = int(gpio_ip["addr_range"])
        self.AXI_UART_ADDR = int(uart_ip["phys_addr"])
        self.AXI_UART_RNG  = int(uart_ip["addr_range"])
        self.AXI_JTAG_ADDR = int(jtag_ip["phys_addr"])
        self.AXI_JTAG_RNG  = int(jtag_ip["addr_range"])

        self.uart = xheepUART(self.AXI_UART_ADDR)
        self.uart.unbind()

        # SPI IRQ is at concat position 2 (In2), UART is at position 0 (In0)
        # So SPI_IRQ = UART_IRQ + 2
        board = os.getenv("BOARD", "pynq-z2").lower()
        if board == "aup-zu3":
            spi_irq = 92  # UltraScale+: UART=90 (In0), In1=91, SPI=92 (In2)
        else:
            spi_irq = 32  # Zynq-7000: UART=30 (In0), In1=31, SPI=32 (In2)

        if spi_ip:
            self.AXI_SPI_ADDR = int(spi_ip["phys_addr"])
            self.AXI_SPI_RNG  = int(spi_ip["addr_range"])
            # Use MTD mode for Quad SPI (creates /dev/mtdX instead of /dev/spidevX.Y)
            self.spi = xheepSPI(self.AXI_SPI_ADDR, spi_irq, use_mtd=True)
            self.spi.unbind()
        else:
            log("warning", "SPI IP not found - PL SPI overlay unavailable (flash may still be accessible via PS mux)")
            self.spi = None

        PL.reset()
        time.sleep(0.2)  # Wait for PL reset to complete (like debug_spi.py)
        self.download()
        time.sleep(0.1)  # Wait for fabric to stabilize after bitstream load

        self.gpio = xheepGPIO(self, self.AXI_GPIO_ADDR, self.AXI_GPIO_RNG)
        self.jtag = xheepJTAG(self, self.AXI_JTAG_ADDR, self.AXI_JTAG_RNG)

        self.uart.bind()
        # NOTE: Do NOT bind SPI driver - we use direct MMIO for flash programming
        # Kernel drivers leave the IP in inconsistent state after unbind
        # if self.spi:
        #     self.spi.bind()
        
        # Create flash programmer using direct MMIO (does not need kernel drivers)
        if spi_ip:
            self.flash_programmer = xheepFlashProgrammer(self.AXI_SPI_ADDR, self.gpio)
        else:
            self.flash_programmer = None
    
    def program_flash(self, bin_file: Path, verify: bool = True) -> bool:
        """
        Program binary to external SPI flash using direct MMIO.
        
        This method:
        1. Switches SPI mux to PS control
        2. Programs flash via direct AXI Quad SPI register access
        3. Switches SPI mux back to X-HEEP control
        
        Args:
            bin_file: Path to binary file
            verify: Verify after programming
        
        Returns:
            True if successful
        """
        if not self.flash_programmer:
            log("error", "Flash programmer not available (no SPI IP)")
            return False
        
        bin_file = Path(bin_file)
        if not bin_file.exists():
            log("error", f"Binary file not found: {bin_file}")
            return False
        
        log("info", f"Programming flash: {bin_file}")
        
        # Unbind kernel SPI driver if it was bound (free the hardware)
        if self.spi:
            self.spi.unbind()
        
        # Switch SPI mux to PS control
        log("info", "Switching SPI mux to PS control...")
        self.gpio.setSpiFlashControl(True)
        time.sleep(0.1)
        
        try:
            # Program flash
            result = self.flash_programmer.program_file(bin_file, verify=verify)
        finally:
            # Always switch back to X-HEEP control
            log("info", "Switching SPI mux to X-HEEP control...")
            self.gpio.setSpiFlashControl(False)
            time.sleep(0.05)
        
        return result