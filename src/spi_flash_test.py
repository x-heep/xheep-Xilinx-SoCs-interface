#!/usr/bin/env python3
"""
SPI Flash Test Script per x-heep su Xilinx FPGA (PYNQ-Z2 / UltraScale+)

Questo script:
1. Carica il bitstream sulla PL
2. Compila e installa l'overlay DTS per il controller SPI
3. Verifica che il device tree overlay sia installato correttamente
4. Testa la connessione SPI con la flash esterna W25Q (Winbond)

Per selezionare il PS come master SPI si usa il bit 5 (indice 4 base-0)
del canale 1 della GPIO AXI tramite driver MMIO.

I file DTS sono template (.tpl) perché l'indirizzo viene sostituito
dinamicamente una volta identificato l'IP nella bitstream.

Uso:
    python spi_flash_test.py -o <bitstream.bit> [--board pynq-z2|aup-zu3] [--spi-mode spidev|mtd]

Modalità SPI:
    - spidev: Crea /dev/spidevX.Y per accesso raw SPI (debug, consigliato inizialmente)
    - mtd: Crea /dev/mtdX per accesso flash tramite driver spi-nor
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

# ANSI colors per output leggibile
RESET = "\033[0m"
COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m\033[97m",
    "SUCCESS": "\033[42m\033[97m",
    "TEST": "\033[35m",
}


def log(level: str, msg: str, stderr: bool | None = None) -> None:
    """Log colorato su stdout/stderr."""
    lvl = level.upper()
    color = COLORS.get(lvl, "")
    if stderr is None:
        use_stderr = lvl in ("WARNING", "ERROR", "CRITICAL")
    else:
        use_stderr = stderr
    stream = sys.stderr if use_stderr else sys.stdout
    stream.write(f"{color}[{lvl}] {msg}{RESET}\n")
    stream.flush()


def check_root() -> bool:
    """Verifica se lo script è eseguito come root (necessario per ConfigFS)."""
    return os.geteuid() == 0


class SPIFlashTester:
    """Classe per testare il setup SPI flash su x-heep."""

    # Registri AXI GPIO
    CH1_DATA = 0x00
    CH1_TRI = 0x04
    CH2_DATA = 0x08
    CH2_TRI = 0x0C

    # Bit di controllo sul canale 1
    BIT_RST_NI = 0        # rst_ni - reset attivo basso
    BIT_BOOTSEL = 1       # boot_select_i
    BIT_EXECFLASH = 2     # execute_from_flash_i
    BIT_TRST_NI = 3       # jtag_trst_ni
    BIT_SPI_SEL = 4       # SPI flash mux select (0=X-HEEP, 1=PS)

    # Path per overlay ConfigFS
    CONFIGFS_BASE = Path("/sys/kernel/config/device-tree/overlays")
    SPI_OVERLAY_NAME = "axiquadspi"

    # Path per file temporanei DTS
    DTS_PATCHED_PATH = Path("dts/spi-patched.dts")
    DTBO_PATH = Path("dts/spi-overlay.dtbo")

    # Timeout e polling
    TIMEOUT_S = 5.0
    POLL_S = 0.05

    # Comandi SPI Flash W25Q (Winbond)
    CMD_READ_JEDEC_ID = 0x9F
    CMD_READ_STATUS_REG1 = 0x05
    CMD_READ_STATUS_REG2 = 0x35
    CMD_WRITE_ENABLE = 0x06
    CMD_READ_DATA = 0x03
    CMD_PAGE_PROGRAM = 0x02
    CMD_SECTOR_ERASE = 0x20
    CMD_CHIP_ERASE = 0xC7

    # JEDEC ID per flash W25Q comuni
    KNOWN_FLASH_IDS = {
        (0xEF, 0x40, 0x16): "W25Q32 (32Mbit/4MB)",
        (0xEF, 0x40, 0x17): "W25Q64 (64Mbit/8MB)",
        (0xEF, 0x40, 0x18): "W25Q128 (128Mbit/16MB)",
        (0xEF, 0x40, 0x19): "W25Q256 (256Mbit/32MB)",
        (0xEF, 0x70, 0x18): "W25Q128JV (128Mbit/16MB)",
    }

    def __init__(self, bitstream_path: str, board: str = "pynq-z2", spi_mode: str = "spidev"):
        self.bitstream_path = Path(bitstream_path).resolve()
        self.board = board.lower()
        self.spi_mode = spi_mode.lower()  # "spidev" or "mtd"
        self.overlay = None
        self.mmio_gpio = None
        self.gpio_addr = None
        self.gpio_range = None
        self.spi_addr = None
        self.spi_range = None

        # Template DTS in base alla board e modalità (mtd o spidev)
        if self.board == "aup-zu3":
            self.dts_template = Path(f"dts/spi-ultrascale-{self.spi_mode}.tpl")
        else:
            self.dts_template = Path(f"dts/spi-zynq-{self.spi_mode}.tpl")

        self.ovl_dir = self.CONFIGFS_BASE / self.SPI_OVERLAY_NAME
        self.test_results = []

    def _test_result(self, name: str, passed: bool, details: str = "") -> None:
        """Registra il risultato di un test."""
        self.test_results.append((name, passed, details))
        status = "PASS" if passed else "FAIL"
        color = COLORS["SUCCESS"] if passed else COLORS["ERROR"]
        log("TEST", f"{name}: {color}{status}{RESET} {details}")

    def load_bitstream(self) -> bool:
        """Carica il bitstream sulla PL usando PYNQ."""
        log("INFO", f"Caricamento bitstream: {self.bitstream_path}")

        if not self.bitstream_path.exists():
            log("ERROR", f"Bitstream non trovato: {self.bitstream_path}")
            return False

        try:
            from pynq import Overlay, PL, MMIO

            # Reset PL prima di caricare
            log("INFO", "Reset della Programmable Logic...")
            PL.reset()
            time.sleep(0.1)

            # Carica overlay senza download automatico per ispezionare prima
            self.overlay = Overlay(str(self.bitstream_path), download=False)
            for name, info in self.overlay.ip_dict.items():
                base = info.get("phys_addr")
                span = info.get("addr_range")
                if base is None or span is None:
                    print(f"  - {name:25s}")
                else:
                    print(f"  - {name:25s} base=0x{base:08X}  range=0x{span:X}")

            # Estrai indirizzi IP dal bitstream
            if "axi_gpio" not in self.overlay.ip_dict:
                log("ERROR", "IP axi_gpio non trovato nel bitstream")
                return False

            gpio_ip = self.overlay.ip_dict["axi_gpio"]
            self.gpio_addr = int(gpio_ip["phys_addr"])
            self.gpio_range = int(gpio_ip["addr_range"])
            log("INFO", f"AXI GPIO @ 0x{self.gpio_addr:08X} (range: 0x{self.gpio_range:X})")

            if "axi_quad_spi" in self.overlay.ip_dict:
                spi_ip = self.overlay.ip_dict["axi_quad_spi"]
                self.spi_addr = int(spi_ip["phys_addr"])
                self.spi_range = int(spi_ip["addr_range"])
                log("INFO", f"AXI Quad SPI @ 0x{self.spi_addr:08X} (range: 0x{self.spi_range:X})")
            else:
                log("WARNING", "IP axi_quad_spi non trovato - SPI overlay potrebbe non funzionare")

            # Scarica effettivamente il bitstream
            log("INFO", "Download bitstream sulla PL...")
            self.overlay.download()
            time.sleep(0.2)

            # Inizializza MMIO per GPIO
            self.mmio_gpio = MMIO(self.gpio_addr, self.gpio_range)

            # Configura direzione: CH1 = output, CH2 = input
            self.mmio_gpio.write(self.CH1_TRI, 0x0)
            self.mmio_gpio.write(self.CH2_TRI, 0x3)

            log("SUCCESS", "Bitstream caricato con successo!")
            return True

        except ImportError:
            log("ERROR", "PYNQ non installato. Eseguire su board PYNQ.")
            return False
        except Exception as e:
            log("ERROR", f"Errore caricamento bitstream: {e}")
            import traceback
            traceback.print_exc()
            return False

    def set_gpio_bit(self, bit: int, value: bool) -> None:
        """Imposta un bit sul canale 1 GPIO."""
        if self.mmio_gpio is None:
            log("ERROR", "MMIO GPIO non inizializzato")
            return
        reg = int(self.mmio_gpio.read(self.CH1_DATA))
        reg = (reg | (1 << bit)) if value else (reg & ~(1 << bit))
        self.mmio_gpio.write(self.CH1_DATA, reg)

    def get_gpio_bit(self, channel: int, bit: int) -> int:
        """Legge un bit da un canale GPIO."""
        if self.mmio_gpio is None:
            return 0
        reg_offset = channel * 8  # CH1_DATA=0x00, CH2_DATA=0x08
        return (int(self.mmio_gpio.read(reg_offset)) >> bit) & 0x1

    def set_spi_master_ps(self, use_ps: bool) -> None:
        """
        Seleziona il master SPI: PS (Linux) o PL (X-HEEP).

        Usa il bit 5 (indice 4) del canale 1 della periferica GPIO AXI.
        - True: PS controlla la flash SPI (per programmazione da Linux)
        - False: X-HEEP controlla la flash SPI (per esecuzione)
        """
        log("INFO", f"Selezione master SPI: {'PS (Linux)' if use_ps else 'X-HEEP (PL)'}")
        self.set_gpio_bit(self.BIT_SPI_SEL, use_ps)
        time.sleep(0.01)  # Attendi stabilizzazione mux

    def reset_xheep(self) -> None:
        """Esegue reset del core X-HEEP."""
        log("INFO", "Reset X-HEEP core...")
        self.set_gpio_bit(self.BIT_RST_NI, 0)  # Assert reset
        time.sleep(0.001)
        self.set_gpio_bit(self.BIT_RST_NI, 1)  # Release reset
        time.sleep(0.001)

    def _wait_condition(self, cond_fn, timeout_s: float, what: str) -> bool:
        """Attende che una condizione sia vera."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if cond_fn():
                return True
            time.sleep(self.POLL_S)
        log("WARNING", f"Timeout aspettando: {what}")
        return False

    def _patch_dts(self) -> bool:
        """Applica patch al template DTS con indirizzo SPI effettivo."""
        if not self.dts_template.exists():
            log("ERROR", f"Template DTS non trovato: {self.dts_template}")
            return False

        if self.spi_addr is None:
            log("ERROR", "Indirizzo SPI non disponibile")
            return False

        content = self.dts_template.read_text()
        patched = content.replace("########", f"{self.spi_addr:08x}")

        self.DTS_PATCHED_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.DTS_PATCHED_PATH.write_text(patched)
        log("INFO", f"DTS patchato: {self.DTS_PATCHED_PATH}")
        return True

    def _compile_dts(self) -> bool:
        """Compila DTS in DTBO usando dtc."""
        argv = [
            "dtc", "-@", "-I", "dts", "-O", "dtb",
            "-o", str(self.DTBO_PATH),
            str(self.DTS_PATCHED_PATH)
        ]

        log("INFO", f"Compilazione DTS: {' '.join(argv)}")
        cp = subprocess.run(argv, capture_output=True, text=True)

        if cp.returncode != 0:
            log("ERROR", f"dtc fallito (rc={cp.returncode})")
            log("ERROR", f"stderr: {cp.stderr or cp.stdout}")
            return False

        log("INFO", f"DTBO generato: {self.DTBO_PATH}")
        return True

    def unbind_spi_overlay(self) -> None:
        """Rimuove overlay SPI esistente in modo completo e sicuro."""
        # 1. Trova tutti i possibili platform device SPI da unbindare
        platform_devs = []
        if self.spi_addr:
            platform_devs.append(f"{self.spi_addr:08x}.spi")

        # Cerca anche altri device SPI che potrebbero essere stati creati
        platform_dir = Path("/sys/bus/platform/devices")
        if platform_dir.exists():
            for dev in platform_dir.iterdir():
                if dev.name.endswith(".spi") and dev.name not in platform_devs:
                    # Verifica se è un device AXI Quad SPI
                    compat_path = dev / "of_node" / "compatible"
                    if compat_path.exists():
                        try:
                            compat = compat_path.read_text()
                            if "xlnx,axi-quad-spi" in compat:
                                platform_devs.append(dev.name)
                        except Exception:
                            pass

        # 2. Unbind tutti i driver dai device trovati
        for platform_dev in platform_devs:
            dev = Path("/sys/bus/platform/devices") / platform_dev
            driver_link = dev / "driver"

            if driver_link.exists():
                try:
                    drv_name = Path(os.readlink(driver_link)).name
                    unbind_path = Path("/sys/bus/platform/drivers") / drv_name / "unbind"
                    log("INFO", f"Unbinding driver {drv_name} da {platform_dev}...")
                    unbind_path.write_text(platform_dev, encoding="utf-8")
                    self._wait_condition(lambda: not driver_link.exists(),
                                        self.TIMEOUT_S, f"unbind driver da {platform_dev}")
                    log("INFO", f"Driver SPI scollegato da {platform_dev}")
                except Exception as e:
                    log("DEBUG", f"Unbind SPI driver {platform_dev}: {e}")

        # 3. Attendi che il sistema si stabilizzi
        time.sleep(0.2)

        # 4. Rimuovi l'overlay dal ConfigFS
        if self.ovl_dir.exists():
            try:
                # Scrivi vuoto per forzare rimozione se necessario
                status_path = self.ovl_dir / "status"
                if status_path.exists():
                    try:
                        status = status_path.read_text().strip()
                        log("DEBUG", f"Overlay status: {status}")
                    except Exception:
                        pass

                log("INFO", f"Rimozione overlay da {self.ovl_dir}...")
                os.rmdir(self.ovl_dir)

                # Attendi che la directory sia effettivamente rimossa
                if not self._wait_condition(lambda: not self.ovl_dir.exists(),
                                           self.TIMEOUT_S, "rimozione overlay SPI"):
                    log("WARNING", "Timeout rimozione overlay, forzo...")
                    # Prova con subprocess
                    subprocess.run(["rmdir", str(self.ovl_dir)],
                                  capture_output=True, timeout=5)
                    time.sleep(0.5)

                if not self.ovl_dir.exists():
                    log("INFO", "Overlay SPI rimosso")
                else:
                    log("WARNING", "Overlay SPI potrebbe non essere stato rimosso completamente")
            except OSError as e:
                if e.errno == 39:  # Directory not empty
                    log("WARNING", f"Overlay directory non vuota, provo a forzare: {e}")
                    # Prova a rimuovere contenuti
                    try:
                        for item in self.ovl_dir.iterdir():
                            if item.is_file():
                                item.unlink()
                        os.rmdir(self.ovl_dir)
                        log("INFO", "Overlay SPI rimosso (forzato)")
                    except Exception as e2:
                        log("ERROR", f"Impossibile rimuovere overlay: {e2}")
                else:
                    log("DEBUG", f"Rimozione overlay SPI: {e}")
            except Exception as e:
                log("DEBUG", f"Rimozione overlay SPI: {e}")

        # 5. Attendi stabilizzazione finale
        time.sleep(0.3)

    def install_spi_overlay(self) -> bool:
        """Compila e installa l'overlay DTS per SPI nel device tree."""
        log("INFO", "=== Installazione overlay SPI nel Device Tree ===")

        # Rimuovi overlay esistente (completo unbind + rimozione)
        self.unbind_spi_overlay()

        # Verifica che l'overlay sia stato effettivamente rimosso
        if self.ovl_dir.exists():
            log("WARNING", "Overlay ancora presente dopo unbind, riprovo rimozione...")
            for attempt in range(3):
                try:
                    os.rmdir(self.ovl_dir)
                    time.sleep(0.3)
                    if not self.ovl_dir.exists():
                        break
                except Exception as e:
                    log("DEBUG", f"Tentativo {attempt+1} rimozione: {e}")
                    time.sleep(0.5)

            if self.ovl_dir.exists():
                log("ERROR", f"Impossibile rimuovere overlay esistente: {self.ovl_dir}")
                return False

        # Patch e compila DTS
        if not self._patch_dts():
            return False
        if not self._compile_dts():
            return False

        # Verifica che ConfigFS sia montato
        if not self.CONFIGFS_BASE.exists():
            log("ERROR", f"ConfigFS overlays non montato: {self.CONFIGFS_BASE}")
            log("INFO", "Prova: mount -t configfs configfs /sys/kernel/config")
            return False

        # Crea directory overlay e carica DTBO
        try:
            log("INFO", f"Creazione overlay directory: {self.ovl_dir}")
            self.ovl_dir.mkdir(parents=True, exist_ok=False)
            time.sleep(0.1)

            dtbo_data = self.DTBO_PATH.read_bytes()
            log("INFO", f"Scrittura DTBO ({len(dtbo_data)} bytes)...")
            (self.ovl_dir / "dtbo").write_bytes(dtbo_data)
            log("INFO", f"DTBO caricato in: {self.ovl_dir}")
        except FileExistsError:
            log("ERROR", f"Overlay directory già esiste dopo rimozione: {self.ovl_dir}")
            return False
        except Exception as e:
            log("ERROR", f"Errore caricamento DTBO: {e}")
            return False

        # Attendi che il platform device appaia
        platform_dev = f"{self.spi_addr:08x}.spi"
        dev_path = Path("/sys/bus/platform/devices") / platform_dev

        if not self._wait_condition(lambda: dev_path.exists(),
                                   self.TIMEOUT_S, "platform device SPI"):
            log("ERROR", f"Platform device non apparso: {platform_dev}")
            return False

        log("INFO", f"Platform device creato: {platform_dev}")

        # Prova a bindare il driver
        driver_link = dev_path / "driver"
        if not driver_link.exists():
            for driver_name in ["xilinx_spi", "spi-xilinx"]:
                bind_path = Path("/sys/bus/platform/drivers") / driver_name / "bind"
                if not bind_path.exists():
                    subprocess.run(["modprobe", driver_name],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                if bind_path.exists():
                    try:
                        bind_path.write_text(platform_dev, encoding="utf-8")
                        log("INFO", f"Driver {driver_name} associato")
                        break
                    except OSError as e:
                        if e.errno == 16:  # Device busy = già bound
                            break
                        log("DEBUG", f"Bind {driver_name} fallito: {e}")

        # Attendi conferma bind driver
        self._wait_condition(lambda: (dev_path / "driver").exists(),
                            self.TIMEOUT_S, "bind driver SPI")

        log("SUCCESS", "Overlay SPI installato con successo!")
        return True

    def find_mtd_device(self) -> Optional[Path]:
        """Trova il device MTD per la flash SPI."""
        mtd_dir = Path("/sys/class/mtd")
        if not mtd_dir.exists():
            return None

        # Cerca dispositivi MTD con scoring basato su nome
        candidates = []
        for mtd in mtd_dir.iterdir():
            if not mtd.name.startswith("mtd") or mtd.name.startswith("mtdblock"):
                continue

            score = 0
            name = ""
            try:
                name_path = mtd / "name"
                if name_path.exists():
                    name = name_path.read_text().strip()
            except Exception:
                pass

            lname = name.lower()
            if "xheep-firmware" in lname:
                score += 200
            if "qspi" in lname or "spi-nor" in lname:
                score += 80
            if "flash" in lname:
                score += 40
            if "w25" in lname or "winbond" in lname:
                score += 30

            mtd_num = mtd.name.replace("mtd", "")
            dev = Path("/dev") / f"mtd{mtd_num}"
            if dev.exists():
                candidates.append((score, dev, name))

        if not candidates:
            # Fallback: primo /dev/mtd*
            devs = sorted(Path("/dev").glob("mtd[0-9]*"))
            return devs[0] if devs else None

        candidates.sort(key=lambda x: x[0], reverse=True)
        best = candidates[0]
        log("INFO", f"MTD device trovato: {best[1]} ({best[2]})")
        return best[1]

    def find_spidev_device(self) -> Optional[Path]:
        """Trova il device spidev per accesso raw SPI."""
        spidev_dir = Path("/sys/class/spidev")
        if not spidev_dir.exists():
            devs = sorted(Path("/dev").glob("spidev*"))
            return devs[0] if devs else None

        for node in spidev_dir.iterdir():
            dev = Path("/dev") / node.name
            if dev.exists():
                return dev

        return None

    def test_device_tree_overlay(self) -> bool:
        """Verifica che l'overlay sia installato correttamente."""
        log("INFO", "=== Test Device Tree Overlay ===")

        # Test 1: Verifica overlay caricato
        overlay_loaded = self.ovl_dir.exists()
        self._test_result("Overlay caricato in ConfigFS", overlay_loaded,
                         str(self.ovl_dir) if overlay_loaded else "")

        # Test 2: Verifica platform device
        platform_dev = f"{self.spi_addr:08x}.spi" if self.spi_addr else ""
        dev_path = Path("/sys/bus/platform/devices") / platform_dev
        dev_exists = dev_path.exists()
        self._test_result("Platform device presente", dev_exists, platform_dev)

        # Test 3: Verifica driver bound
        driver_link = dev_path / "driver" if dev_path.exists() else Path("/nonexistent")
        driver_bound = driver_link.exists()
        driver_name = ""
        if driver_bound:
            try:
                driver_name = Path(os.readlink(driver_link)).name
            except Exception:
                pass
        self._test_result("Driver SPI associato", driver_bound, driver_name)

        # Test 4: Verifica MTD o spidev device
        time.sleep(0.5)  # Attendi creazione device node
        mtd_dev = self.find_mtd_device()
        spi_dev = self.find_spidev_device()

        device_found = mtd_dev is not None or spi_dev is not None
        device_info = str(mtd_dev or spi_dev or "nessuno")
        self._test_result("Device node creato (/dev/mtd* o /dev/spidev*)",
                         device_found, device_info)

        return all([overlay_loaded, dev_exists, driver_bound, device_found])

    def test_spi_flash_connection(self) -> bool:
        """Testa la connessione SPI con la flash W25Q."""
        log("INFO", "=== Test Connessione SPI Flash ===")

        # Prima, seleziona PS come master SPI
        self.set_spi_master_ps(True)
        time.sleep(0.1)

        mtd_dev = self.find_mtd_device()
        spi_dev = self.find_spidev_device()

        all_tests_passed = True

        # Test via MTD (preferito)
        if mtd_dev and mtd_dev.exists():
            log("INFO", f"Test via MTD: {mtd_dev}")

            # Test 1: Lettura info MTD
            mtd_name = mtd_dev.name
            mtd_sys = Path("/sys/class/mtd") / mtd_name

            size_bytes = 0
            try:
                size_bytes = int((mtd_sys / "size").read_text().strip())
                size_mb = size_bytes / (1024 * 1024)
                self._test_result("Lettura dimensione flash", True,
                                 f"{size_bytes} bytes ({size_mb:.1f} MB)")
            except Exception as e:
                self._test_result("Lettura dimensione flash", False, str(e))
                all_tests_passed = False

            # Test 2: Tipo di flash
            try:
                flash_type = (mtd_sys / "type").read_text().strip()
                self._test_result("Tipo flash rilevato", True, flash_type)
            except Exception as e:
                self._test_result("Tipo flash rilevato", False, str(e))

            # Test 3: Lettura primi byte
            try:
                with open(mtd_dev, 'rb') as f:
                    header = f.read(16)
                header_hex = header.hex()
                self._test_result("Lettura header flash (16 byte)", True, header_hex)
            except PermissionError:
                self._test_result("Lettura header flash", False,
                                 "Permesso negato - eseguire come root")
                all_tests_passed = False
            except Exception as e:
                self._test_result("Lettura header flash", False, str(e))
                all_tests_passed = False

        # Test via spidev se disponibile
        elif spi_dev and spi_dev.exists():
            log("INFO", f"Test via spidev: {spi_dev}")

            try:
                import spidev
                spi = spidev.SpiDev()
                bus, device = 0, 0
                # Estrai bus/device dal nome (es. spidev0.0)
                parts = spi_dev.name.replace("spidev", "").split(".")
                if len(parts) == 2:
                    bus, device = int(parts[0]), int(parts[1])

                spi.open(bus, device)
                spi.max_speed_hz = 1000000  # 1 MHz per test
                spi.mode = 0

                # Test: Read JEDEC ID (0x9F)
                response = spi.xfer2([self.CMD_READ_JEDEC_ID, 0, 0, 0])
                mfr_id, mem_type, capacity = response[1], response[2], response[3]

                jedec_id = (mfr_id, mem_type, capacity)
                flash_name = self.KNOWN_FLASH_IDS.get(jedec_id, "Sconosciuto")

                jedec_valid = mfr_id != 0x00 and mfr_id != 0xFF
                self._test_result("JEDEC ID flash", jedec_valid,
                                 f"0x{mfr_id:02X} 0x{mem_type:02X} 0x{capacity:02X} ({flash_name})")

                if not jedec_valid:
                    all_tests_passed = False

                # Test: Read Status Register
                response = spi.xfer2([self.CMD_READ_STATUS_REG1, 0])
                status = response[1]
                self._test_result("Lettura Status Register 1", True, f"0x{status:02X}")

                spi.close()

            except ImportError:
                self._test_result("Test spidev", False,
                                 "Modulo spidev non installato (pip install spidev)")
                all_tests_passed = False
            except PermissionError:
                self._test_result("Accesso spidev", False,
                                 "Permesso negato - eseguire come root")
                all_tests_passed = False
            except Exception as e:
                self._test_result("Comunicazione SPI", False, str(e))
                all_tests_passed = False

        else:
            self._test_result("Device SPI disponibile", False,
                             "Nessun MTD o spidev trovato")
            all_tests_passed = False

        # Ripristina X-HEEP come master SPI
        self.set_spi_master_ps(False)

        return all_tests_passed

    def test_gpio_control(self) -> bool:
        """Testa il controllo GPIO per selezione master SPI."""
        log("INFO", "=== Test Controllo GPIO ===")

        if self.mmio_gpio is None:
            self._test_result("MMIO GPIO inizializzato", False, "Non disponibile")
            return False

        self._test_result("MMIO GPIO inizializzato", True,
                         f"@ 0x{self.gpio_addr:08X}")

        # Test toggle bit SPI_SEL
        original = self.get_gpio_bit(0, self.BIT_SPI_SEL)

        # Imposta a 1 (PS)
        self.set_spi_master_ps(True)
        time.sleep(0.01)
        val_ps = self.get_gpio_bit(0, self.BIT_SPI_SEL)

        # Imposta a 0 (X-HEEP)
        self.set_spi_master_ps(False)
        time.sleep(0.01)
        val_xheep = self.get_gpio_bit(0, self.BIT_SPI_SEL)

        toggle_ok = (val_ps == 1) and (val_xheep == 0)
        self._test_result("Toggle bit SPI_SEL (bit 5/idx 4)", toggle_ok,
                         f"PS=1:{val_ps}, X-HEEP=0:{val_xheep}")

        # Ripristina valore originale
        self.set_gpio_bit(self.BIT_SPI_SEL, original)

        return toggle_ok

    def run_all_tests(self) -> bool:
        """Esegue tutti i test."""
        log("INFO", "=" * 60)
        log("INFO", "   SPI FLASH TEST SUITE PER X-HEEP")
        log("INFO", "=" * 60)
        log("INFO", f"Board: {self.board.upper()}")
        log("INFO", f"SPI Mode: {self.spi_mode.upper()}")
        log("INFO", f"DTS Template: {self.dts_template}")
        log("INFO", f"Bitstream: {self.bitstream_path}")
        log("INFO", "")

        # Step 1: Carica bitstream
        if not self.load_bitstream():
            log("CRITICAL", "Caricamento bitstream fallito!")
            return False

        # Step 2: Installa overlay SPI
        if self.spi_addr:
            if not self.install_spi_overlay():
                log("ERROR", "Installazione overlay SPI fallita")
                # Continua comunque per testare cosa è disponibile
        else:
            log("WARNING", "SPI IP non presente nel bitstream, skip overlay")

        # Step 3: Test GPIO control
        self.test_gpio_control()

        # Step 4: Test device tree overlay
        if self.spi_addr:
            self.test_device_tree_overlay()

        # Step 5: Test connessione flash
        self.test_spi_flash_connection()

        # Sommario risultati
        log("INFO", "")
        log("INFO", "=" * 60)
        log("INFO", "   SOMMARIO TEST")
        log("INFO", "=" * 60)

        passed = sum(1 for _, p, _ in self.test_results if p)
        total = len(self.test_results)

        for name, result, details in self.test_results:
            status = "PASS" if result else "FAIL"
            color = COLORS["SUCCESS"] if result else COLORS["ERROR"]
            detail_str = f" - {details}" if details else ""
            print(f"  {color}[{status}]{RESET} {name}{detail_str}")

        log("INFO", "")
        success_rate = (passed / total * 100) if total > 0 else 0
        if success_rate == 100:
            log("SUCCESS", f"Tutti i test passati: {passed}/{total}")
        elif success_rate >= 70:
            log("WARNING", f"Test parzialmente passati: {passed}/{total} ({success_rate:.0f}%)")
        else:
            log("ERROR", f"Test falliti: {passed}/{total} ({success_rate:.0f}%)")

        return passed == total

    def cleanup(self) -> None:
        """Pulizia risorse."""
        # Ripristina X-HEEP come master SPI
        if self.mmio_gpio:
            try:
                self.set_spi_master_ps(False)
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test setup SPI flash per x-heep su Xilinx FPGA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python spi_flash_test.py -o bitstream.bit --spi-mode spidev
  python spi_flash_test.py -o bitstream.bit --board aup-zu3 --spi-mode spidev
  python spi_flash_test.py -o bitstream.bit --board aup-zu3 --spi-mode mtd
  sudo python spi_flash_test.py -o bitstream.bit  # Per accesso device
        """
    )

    parser.add_argument("-o", "--overlay", required=True,
                       help="Path al file bitstream (.bit)")
    parser.add_argument("--board", choices=["pynq-z2", "aup-zu3"],
                       default="pynq-z2",
                       help="Tipo di board (default: pynq-z2)")
    parser.add_argument("--spi-mode", choices=["spidev", "mtd"],
                       default="spidev",
                       help="Modalità SPI: spidev (raw access, debug) o mtd (flash, default: spidev)")
    parser.add_argument("--skip-bitstream", action="store_true",
                       help="Salta caricamento bitstream (usa quello già caricato)")

    args = parser.parse_args()

    # Warning se non root
    if not check_root():
        log("WARNING", "Non eseguito come root - alcuni test potrebbero fallire")
        log("INFO", "Per test completi eseguire: sudo python spi_flash_test.py ...")

    # Imposta variabile BOARD per template DTS
    os.environ["BOARD"] = args.board

    tester = SPIFlashTester(args.overlay, args.board, args.spi_mode)

    try:
        success = tester.run_all_tests()
        return 0 if success else 1
    except KeyboardInterrupt:
        log("WARNING", "Test interrotto dall'utente")
        return 130
    except Exception as e:
        log("CRITICAL", f"Errore imprevisto: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        tester.cleanup()


if __name__ == "__main__":
    sys.exit(main())
