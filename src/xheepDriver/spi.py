# Copyright 2026 Politecnico di Torino.
#
# File: spi.py
# Author: Christian Conti {christian.conti@polito.it}
# Date: 31/03/2026

import os
import sys
import time
import subprocess
from typing import Optional
from pathlib import Path

from .logger import log

class xheepSPI:
    DTS_PATCHED_PATH = Path("dts/spi-patched.dts")
    DTBO_PATH = Path("dts/spi-overlay.dtbo")

    OVERLAY_NAME = "axiquadspi"
    OVL_DIR = Path("/sys/kernel/config/device-tree/overlays") / OVERLAY_NAME
    
    TIMEOUT_S = 5.0
    POLL_S = 0.05

    def __init__(self, memAddr: int, irqId: int = 62):
        self.memAddr = int(memAddr)
        self.irqId = int(irqId)
        self.PLATFORM_DEV = f"{self.memAddr:08x}.spi"

        board = os.getenv("BOARD", "pynq-z2").lower()
        if board == "aup-zu3":
            self.DTS_TEMPLATE_PATH = Path("dts/spi-ultrascale.tpl")
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

        # Wait for SPI device
        time.sleep(0.5)
        spi_dev = self._get_spi_device()

        if spi_dev:
            log("info", f"SPI device ready: {spi_dev}")
        else:
            log("warning", "No SPI device found")