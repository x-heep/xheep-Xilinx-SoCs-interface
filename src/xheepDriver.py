from pathlib import Path
import os
import sys
import time
import subprocess
import stat
from typing import Optional

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
        """Set SPI flash control: True=PS, False=X-HEEP"""
        self.setBit(0, self.BIT_SPI_SEL, use_ps)
        time.sleep(10e-3)  # Wait for mux to settle

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
                log("debug", f"SPI driver unbind: {e}")

        if self.OVL_DIR.exists():
            try:
                os.rmdir(self.OVL_DIR)
                self._wait(lambda: not self.OVL_DIR.exists(), self.TIMEOUT_S, "SPI overlay removal")
            except Exception as e:
                log("debug", f"SPI overlay removal: {e}")

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
                        log("debug", f"Attempting to bind driver: {driver_name}")
                        bind_path.write_text(self.PLATFORM_DEV, encoding="utf-8")
                        bind_success = True
                        break
                    except OSError as e:
                        if e.errno == 16:  # Device already bound
                            bind_success = True
                            break
                        log("debug", f"Driver {driver_name} bind failed: {e}")
                    except Exception as e:
                        log("debug", f"Driver {driver_name} bind failed: {e}")

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
        self.download()

        self.gpio = xheepGPIO(self, self.AXI_GPIO_ADDR, self.AXI_GPIO_RNG)
        self.jtag = xheepJTAG(self, self.AXI_JTAG_ADDR, self.AXI_JTAG_RNG)

        self.uart.bind()
        if self.spi:
            self.spi.bind()