#!/usr/bin/env python3
"""
Test script per AXI Quad SPI IP con verifica lettura/scrittura flash.

Questo script testa la comunicazione SPI con flash W25Q tramite:
1. Lettura JEDEC ID per identificare la flash
2. Lettura Status Registers
3. Lettura memoria flash
4. (Opzionale) Test di scrittura/verifica con pattern

L'IP AXI Quad SPI e' configurato in modalita Quad (C_SPI_MODE=2).
Il MUX ECO permette al PS di controllare la flash via GPIO bit 4.

Uso:
    python test_quadspi_flash.py --bit <bitstream.bit>
    python test_quadspi_flash.py --bit <bitstream.bit> --test-write
    python test_quadspi_flash.py --bit <bitstream.bit> --test-write --write-addr 0x100000
"""

from pynq import Overlay, MMIO
import argparse
import time
import sys

# ============================================================================
# Registri AXI Quad SPI (PG153)
# ============================================================================
SRR         = 0x40  # Software Reset Register
SPICR       = 0x60  # SPI Control Register
SPISR       = 0x64  # SPI Status Register
SPIDTR      = 0x68  # SPI Data Transmit Register (FIFO)
SPIDRR      = 0x6C  # SPI Data Receive Register (FIFO)
SPISSR      = 0x70  # SPI Slave Select Register
TXFIFO_OCY  = 0x74  # TX FIFO Occupancy
RXFIFO_OCY  = 0x78  # RX FIFO Occupancy
DGIER       = 0x1C  # Global Interrupt Enable
IPISR       = 0x20  # IP Interrupt Status
IPIER       = 0x28  # IP Interrupt Enable

# Registri GPIO
GPIO_BASE   = 0x41200000
GPIO_DATA   = 0x00
GPIO_TRI    = 0x04
GPIO2_DATA  = 0x08

# Base SPI (default, verra aggiornato dal bitstream)
SPI_BASE    = 0x41E00000

# ============================================================================
# Comandi SPI Flash W25Q (Winbond)
# ============================================================================
CMD_WRITE_ENABLE     = 0x06
CMD_WRITE_DISABLE    = 0x04
CMD_READ_STATUS_REG1 = 0x05
CMD_READ_STATUS_REG2 = 0x35
CMD_WRITE_STATUS_REG = 0x01
CMD_READ_DATA        = 0x03  # Standard Read
CMD_FAST_READ        = 0x0B  # Fast Read (richiede dummy byte)
CMD_PAGE_PROGRAM     = 0x02
CMD_SECTOR_ERASE     = 0x20  # 4KB
CMD_BLOCK_ERASE_32K  = 0x52
CMD_BLOCK_ERASE_64K  = 0xD8
CMD_CHIP_ERASE       = 0xC7
CMD_READ_JEDEC_ID    = 0x9F
CMD_POWER_DOWN       = 0xB9
CMD_RELEASE_PD       = 0xAB
CMD_READ_UNIQUE_ID   = 0x4B

# Status Register bits
SR1_BUSY = 0x01
SR1_WEL  = 0x02

# JEDEC IDs noti
KNOWN_FLASH_IDS = {
    (0xEF, 0x40, 0x14): "W25Q80 (8Mbit/1MB)",
    (0xEF, 0x40, 0x15): "W25Q16 (16Mbit/2MB)",
    (0xEF, 0x40, 0x16): "W25Q32 (32Mbit/4MB)",
    (0xEF, 0x40, 0x17): "W25Q64 (64Mbit/8MB)",
    (0xEF, 0x40, 0x18): "W25Q128 (128Mbit/16MB)",
    (0xEF, 0x40, 0x19): "W25Q256 (256Mbit/32MB)",
    (0xEF, 0x70, 0x18): "W25Q128JV (128Mbit/16MB)",
    (0xEF, 0x70, 0x17): "W25Q64JV (64Mbit/8MB)",
    (0xC2, 0x20, 0x17): "MX25L6433F (64Mbit/8MB)",
    (0xC2, 0x20, 0x18): "MX25L12835F (128Mbit/16MB)",
}

# ============================================================================
# Colori ANSI
# ============================================================================
RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BOLD = "\033[1m"

def print_header(msg):
    print(f"\n{BOLD}{'='*60}")
    print(f" {msg}")
    print(f"{'='*60}{RESET}")

def print_ok(msg):
    print(f"{GREEN}[OK]{RESET} {msg}")

def print_err(msg):
    print(f"{RED}[ERR]{RESET} {msg}")

def print_warn(msg):
    print(f"{YELLOW}[WARN]{RESET} {msg}")

def print_info(msg):
    print(f"{CYAN}[INFO]{RESET} {msg}")

def print_test(name, passed, details=""):
    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    detail_str = f" - {details}" if details else ""
    print(f"{MAGENTA}[TEST]{RESET} {name}: {status}{detail_str}")


class QuadSPIController:
    """Controller per AXI Quad SPI IP."""

    def __init__(self, spi_mmio):
        self.spi = spi_mmio
        self.verbose = False

    def reset(self):
        """Reset del controller SPI."""
        self.spi.write(SRR, 0x0000000A)
        time.sleep(0.01)

    def configure(self):
        """Configura SPI come master."""
        # Reset FIFOs + Master + SPE + Manual SS
        spicr = (1 << 6) | (1 << 5) | (1 << 2) | (1 << 1) | (1 << 7)
        self.spi.write(SPICR, spicr)
        time.sleep(0.001)

        # Clear reset bits, mantieni config + MTI (Master Transaction Inhibit)
        spicr = (1 << 2) | (1 << 1) | (1 << 7) | (1 << 8)
        self.spi.write(SPICR, spicr)

    def get_status(self):
        """Legge SPISR."""
        return self.spi.read(SPISR)

    def print_status(self, label=""):
        """Stampa dettagli SPISR."""
        spisr = self.get_status()
        print(f"\nSPISR {label}: 0x{spisr:08X}")
        print(f"  RX_EMPTY: {(spisr >> 0) & 1}, RX_FULL: {(spisr >> 1) & 1}")
        print(f"  TX_EMPTY: {(spisr >> 2) & 1}, TX_FULL: {(spisr >> 3) & 1}")
        print(f"  MODF: {(spisr >> 4) & 1}, Slave_Mode: {(spisr >> 5) & 1}")

    def drain_rx_fifo(self):
        """Svuota il FIFO RX e ritorna i byte."""
        data = []
        for _ in range(256):
            status = self.spi.read(SPISR)
            if status & (1 << 0):  # RX Empty
                break
            byte = self.spi.read(SPIDRR) & 0xFF
            data.append(byte)
        return data

    def transfer(self, tx_bytes, description=""):
        """
        Esegue un trasferimento SPI.
        Ritorna i byte ricevuti.
        """
        if self.verbose and description:
            print(f"  Transfer: {description}")
            print(f"    TX: {' '.join(f'{b:02X}' for b in tx_bytes)}")

        # Svuota RX
        self.drain_rx_fifo()

        # Assert CS (attivo basso)
        self.spi.write(SPISSR, 0xFFFFFFFE)
        time.sleep(0.0001)

        # Scrivi TX nel FIFO
        for byte in tx_bytes:
            self.spi.write(SPIDTR, byte)

        # Start transfer (clear MTI)
        spicr = self.spi.read(SPICR)
        self.spi.write(SPICR, spicr & ~(1 << 8))

        # Attendi completamento
        timeout = 2000
        while timeout > 0:
            status = self.spi.read(SPISR)
            if status & (1 << 2):  # TX Empty
                break
            timeout -= 1
            time.sleep(0.0001)

        if timeout == 0:
            print_warn("Timeout waiting for TX Empty!")

        time.sleep(0.001)

        # Leggi RX
        rx_bytes = self.drain_rx_fifo()

        # Deassert CS
        self.spi.write(SPISSR, 0xFFFFFFFF)

        # Re-enable MTI
        spicr = self.spi.read(SPICR)
        self.spi.write(SPICR, spicr | (1 << 8))

        if self.verbose:
            print(f"    RX: {' '.join(f'{b:02X}' for b in rx_bytes)}")

        return rx_bytes

    def read_jedec_id(self):
        """Legge JEDEC ID della flash."""
        rx = self.transfer([CMD_READ_JEDEC_ID, 0x00, 0x00, 0x00], "RDID")
        if len(rx) >= 4:
            return (rx[1], rx[2], rx[3])
        return (0xFF, 0xFF, 0xFF)

    def read_status_reg1(self):
        """Legge Status Register 1."""
        rx = self.transfer([CMD_READ_STATUS_REG1, 0x00], "RDSR1")
        return rx[1] if len(rx) >= 2 else 0xFF

    def read_status_reg2(self):
        """Legge Status Register 2."""
        rx = self.transfer([CMD_READ_STATUS_REG2, 0x00], "RDSR2")
        return rx[1] if len(rx) >= 2 else 0xFF

    def write_enable(self):
        """Abilita scrittura (WREN)."""
        self.transfer([CMD_WRITE_ENABLE], "WREN")
        time.sleep(0.001)
        # Verifica WEL bit
        sr1 = self.read_status_reg1()
        return (sr1 & SR1_WEL) != 0

    def write_disable(self):
        """Disabilita scrittura."""
        self.transfer([CMD_WRITE_DISABLE], "WRDI")

    def wait_busy(self, timeout_s=30.0):
        """Attende che la flash sia pronta (BUSY=0)."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            sr1 = self.read_status_reg1()
            if sr1 == 0xFF:
                return False  # Errore di comunicazione
            if not (sr1 & SR1_BUSY):
                return True
            time.sleep(0.01)
        return False

    def read_data(self, address, length):
        """Legge dati dalla flash (standard read 0x03)."""
        tx = [CMD_READ_DATA,
              (address >> 16) & 0xFF,
              (address >> 8) & 0xFF,
              address & 0xFF]
        tx.extend([0x00] * length)

        rx = self.transfer(tx, f"READ @ 0x{address:06X}")
        return rx[4:] if len(rx) > 4 else []

    def sector_erase(self, address):
        """Cancella un settore (4KB) all'indirizzo specificato."""
        print_info(f"Cancellazione settore @ 0x{address:06X}...")

        if not self.write_enable():
            print_err("Write Enable fallito!")
            return False

        tx = [CMD_SECTOR_ERASE,
              (address >> 16) & 0xFF,
              (address >> 8) & 0xFF,
              address & 0xFF]
        self.transfer(tx, "SE")

        if not self.wait_busy(timeout_s=5.0):
            print_err("Timeout durante erase!")
            return False

        return True

    def page_program(self, address, data):
        """
        Programma una pagina (max 256 byte).
        L'indirizzo deve essere allineato alla pagina.
        """
        if len(data) > 256:
            print_err("Page Program: max 256 byte per volta!")
            return False

        if not self.write_enable():
            print_err("Write Enable fallito!")
            return False

        tx = [CMD_PAGE_PROGRAM,
              (address >> 16) & 0xFF,
              (address >> 8) & 0xFF,
              address & 0xFF]
        tx.extend(data)

        self.transfer(tx, f"PP @ 0x{address:06X}")

        if not self.wait_busy(timeout_s=5.0):
            print_err("Timeout durante program!")
            return False

        return True


class FlashTester:
    """Test suite per flash SPI."""

    def __init__(self, bitstream_path, gpio_base=GPIO_BASE):
        self.bitstream_path = bitstream_path
        self.gpio_base = gpio_base
        self.overlay = None
        self.gpio = None
        self.spi = None
        self.test_results = []

    def setup(self):
        """Inizializza hardware."""
        print_header("Setup Hardware")

        # Carica overlay
        print_info(f"Caricamento bitstream: {self.bitstream_path}")
        try:
            self.overlay = Overlay(self.bitstream_path)
        except Exception as e:
            print_err(f"Errore caricamento overlay: {e}")
            return False

        # Trova indirizzo SPI
        spi_addr = SPI_BASE
        for name, info in self.overlay.ip_dict.items():
            print_info(f"  IP: {name} @ 0x{info.get('phys_addr', 0):08X}")
            if "spi" in name.lower():
                spi_addr = info['phys_addr']

        print_ok(f"SPI IP @ 0x{spi_addr:08X}")

        # Inizializza GPIO
        print_info("Configurazione GPIO per PS mode...")
        self.gpio = MMIO(self.gpio_base, 0x100)
        self.gpio.write(GPIO_TRI, 0x00)  # CH1 output

        # Imposta bit per PS mode:
        # bit 0: rst_ni = 1 (no reset)
        # bit 1: boot_select = 0
        # bit 2: execute_from_flash = 0
        # bit 3: jtag_trst_ni = 1
        # bit 4: spi_sel = 1 (PS mode)
        gpio_val = 0x1F  # 0b11111 - tutti alti incluso SPI_SEL
        self.gpio.write(GPIO_DATA, gpio_val)
        time.sleep(0.01)
        print_ok(f"GPIO configurato: 0x{self.gpio.read(GPIO_DATA):02X}")

        # Inizializza controller SPI
        spi_mmio = MMIO(spi_addr, 0x100)
        self.spi = QuadSPIController(spi_mmio)

        print_info("Reset e configurazione SPI...")
        self.spi.reset()
        self.spi.configure()
        print_ok("SPI configurato")

        return True

    def record_test(self, name, passed, details=""):
        """Registra risultato test."""
        self.test_results.append((name, passed, details))
        print_test(name, passed, details)

    def test_jedec_id(self):
        """Test lettura JEDEC ID."""
        print_header("Test JEDEC ID")

        jedec = self.spi.read_jedec_id()
        mfr, mem_type, capacity = jedec

        print_info(f"Manufacturer ID: 0x{mfr:02X}")
        print_info(f"Memory Type:     0x{mem_type:02X}")
        print_info(f"Capacity:        0x{capacity:02X}")

        if jedec in KNOWN_FLASH_IDS:
            flash_name = KNOWN_FLASH_IDS[jedec]
            print_ok(f"Flash identificata: {flash_name}")
            self.record_test("JEDEC ID", True, flash_name)
            return True
        elif mfr == 0xFF and mem_type == 0xFF and capacity == 0xFF:
            print_err("JEDEC ID = 0xFF 0xFF 0xFF - Flash non risponde!")
            print_err("Possibili cause:")
            print_err("  1. ECO non applicato correttamente (MISO tristate)")
            print_err("  2. Bus contention su IO1")
            print_err("  3. Flash non alimentata/connessa")
            print_err("  4. MUX select non corretto")
            self.record_test("JEDEC ID", False, "All 0xFF - no response")
            return False
        elif mfr == 0x00 and mem_type == 0x00:
            print_err("JEDEC ID = 0x00 0x00 0x00 - Bus stuck LOW!")
            self.record_test("JEDEC ID", False, "All 0x00 - bus stuck")
            return False
        else:
            print_warn(f"Flash sconosciuta: 0x{mfr:02X} 0x{mem_type:02X} 0x{capacity:02X}")
            self.record_test("JEDEC ID", True, f"Unknown: 0x{mfr:02X}{mem_type:02X}{capacity:02X}")
            return True

    def test_status_registers(self):
        """Test lettura Status Registers."""
        print_header("Test Status Registers")

        sr1 = self.spi.read_status_reg1()
        sr2 = self.spi.read_status_reg2()

        print_info(f"Status Register 1: 0x{sr1:02X}")
        print_info(f"  BUSY: {sr1 & 0x01}, WEL: {(sr1 >> 1) & 0x01}")
        print_info(f"  BP[2:0]: {(sr1 >> 2) & 0x07} (Block Protect)")

        print_info(f"Status Register 2: 0x{sr2:02X}")
        print_info(f"  QE: {(sr2 >> 1) & 0x01} (Quad Enable)")

        if sr1 == 0xFF and sr2 == 0xFF:
            print_err("Status Registers = 0xFF - Flash non risponde!")
            self.record_test("Status Registers", False, "All 0xFF")
            return False

        self.record_test("Status Registers", True, f"SR1=0x{sr1:02X}, SR2=0x{sr2:02X}")
        return True

    def test_read_memory(self, address=0x000000, length=32):
        """Test lettura memoria."""
        print_header(f"Test Lettura Memoria @ 0x{address:06X}")

        data = self.spi.read_data(address, length)

        if not data:
            print_err("Nessun dato ricevuto!")
            self.record_test("Read Memory", False, "No data")
            return False

        # Formatta output in righe da 16 byte
        print_info(f"Data ({len(data)} bytes):")
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_str = ' '.join(f'{b:02X}' for b in chunk)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            print(f"  {address+i:06X}: {hex_str:<48} |{ascii_str}|")

        # Verifica contenuto
        if all(b == 0xFF for b in data):
            print_info("Flash vuota (tutti 0xFF)")
            self.record_test("Read Memory", True, "All 0xFF (erased)")
        elif all(b == 0x00 for b in data):
            print_warn("Tutti 0x00 - potrebbe indicare problema")
            self.record_test("Read Memory", True, "All 0x00 (suspicious)")
        else:
            self.record_test("Read Memory", True, f"{len(data)} bytes read")

        return True

    def test_write_verify(self, test_address=0x010000):
        """
        Test completo di write e verifica.
        ATTENZIONE: Cancella e scrive all'indirizzo specificato!
        """
        print_header(f"Test Write/Verify @ 0x{test_address:06X}")
        print_warn("Questo test CANCELLERA' i dati nel settore specificato!")

        # Pattern di test con vari valori
        test_pattern = bytes([
            0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE,
            0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0,
            0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
            0xF0, 0xE0, 0xD0, 0xC0, 0xB0, 0xA0, 0x90, 0x80
        ])

        print_info("Pattern di test (32 bytes):")
        print(f"  {' '.join(f'{b:02X}' for b in test_pattern[:16])}")
        print(f"  {' '.join(f'{b:02X}' for b in test_pattern[16:])}")

        # Step 1: Leggi dati originali
        print_info("\n1. Lettura dati originali...")
        original_data = self.spi.read_data(test_address, len(test_pattern))
        print(f"   {' '.join(f'{b:02X}' for b in original_data[:16])}")

        # Step 2: Cancella settore
        print_info("\n2. Cancellazione settore (4KB)...")
        if not self.spi.sector_erase(test_address):
            print_err("   Sector Erase fallito!")
            self.record_test("Write/Verify", False, "Erase failed")
            return False

        # Verifica cancellazione
        erased_data = self.spi.read_data(test_address, len(test_pattern))
        if not all(b == 0xFF for b in erased_data):
            print_err(f"   Verifica erase fallita!")
            print_err(f"   Letto: {' '.join(f'{b:02X}' for b in erased_data[:16])}")
            self.record_test("Write/Verify", False, "Erase verify failed")
            return False
        print_ok("   Settore cancellato e verificato")

        # Step 3: Programma pagina
        print_info("\n3. Programmazione pagina...")
        if not self.spi.page_program(test_address, list(test_pattern)):
            print_err("   Page Program fallito!")
            self.record_test("Write/Verify", False, "Program failed")
            return False
        print_ok("   Pagina programmata")

        # Step 4: Verifica
        print_info("\n4. Verifica dati scritti...")
        readback = self.spi.read_data(test_address, len(test_pattern))
        print_info(f"   Letto: {' '.join(f'{b:02X}' for b in readback[:16])}")
        print_info(f"          {' '.join(f'{b:02X}' for b in readback[16:])}")

        if bytes(readback) == test_pattern:
            print_ok("   VERIFICA OK - I dati corrispondono!")
            self.record_test("Write/Verify", True, "Data matches")
            return True
        else:
            print_err("   VERIFICA FALLITA - I dati NON corrispondono!")
            # Mostra differenze
            errors = 0
            for i, (expected, actual) in enumerate(zip(test_pattern, readback)):
                if expected != actual:
                    print_err(f"   Byte {i}: expected 0x{expected:02X}, got 0x{actual:02X}")
                    errors += 1
                    if errors >= 10:
                        print_err(f"   ... ({len([1 for e,a in zip(test_pattern,readback) if e!=a]) - 10} more errors)")
                        break
            self.record_test("Write/Verify", False, f"{errors} byte errors")
            return False

    def print_summary(self):
        """Stampa sommario risultati."""
        print_header("SOMMARIO TEST")

        passed = 0
        failed = 0
        for name, result, details in self.test_results:
            status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
            detail_str = f" - {details}" if details else ""
            print(f"  [{status}] {name}{detail_str}")
            if result:
                passed += 1
            else:
                failed += 1

        print()
        total = passed + failed
        if failed == 0:
            print_ok(f"Tutti i test passati ({passed}/{total})")
        else:
            print_err(f"Test falliti: {failed}/{total}")

        return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="Test AXI Quad SPI con verifica flash W25Q",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python test_quadspi_flash.py --bit bitstream.bit
  python test_quadspi_flash.py --bit bitstream.bit --test-write
  python test_quadspi_flash.py --bit bitstream.bit --test-write --write-addr 0x100000
  python test_quadspi_flash.py --bit bitstream.bit --verbose
        """
    )
    parser.add_argument("--bit", required=True, help="Path al bitstream (.bit)")
    parser.add_argument("--test-write", action="store_true",
                       help="Esegui test di scrittura/verifica (CANCELLA DATI!)")
    parser.add_argument("--write-addr", type=lambda x: int(x, 0), default=0x010000,
                       help="Indirizzo per test write (default: 0x010000)")
    parser.add_argument("--read-addr", type=lambda x: int(x, 0), default=0x000000,
                       help="Indirizzo per test lettura (default: 0x000000)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Output verboso")
    args = parser.parse_args()

    print_header("AXI Quad SPI Flash Test Suite")
    print_info(f"Bitstream: {args.bit}")

    tester = FlashTester(args.bit)

    if not tester.setup():
        return 1

    if args.verbose:
        tester.spi.verbose = True

    # Test di base
    tester.test_jedec_id()
    tester.test_status_registers()
    tester.test_read_memory(address=args.read_addr)

    # Test di scrittura (opzionale)
    if args.test_write:
        print()
        print_warn(f"Test di scrittura all'indirizzo 0x{args.write_addr:06X}")
        print_warn("Questo CANCELLERA' i dati esistenti in quel settore!")
        try:
            response = input("Continuare? [y/N] ")
            if response.lower() == 'y':
                tester.test_write_verify(args.write_addr)
            else:
                print_info("Test di scrittura annullato")
        except KeyboardInterrupt:
            print_info("\nTest annullato")

    # Sommario
    success = tester.print_summary()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
