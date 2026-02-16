#!/usr/bin/env python3
"""
Direct SPI flash programmer using MMIO.
Bypasses xheepDriver to ensure clean SPI state.
Based on debug_spi.py which works correctly.
"""

from pynq import Overlay, MMIO, PL
import time
import sys
import argparse
from pathlib import Path

# AXI Quad SPI registers (PG153)
SRR         = 0x40  # Software Reset Register
SPICR       = 0x60  # SPI Control Register
SPISR       = 0x64  # SPI Status Register
SPIDTR      = 0x68  # SPI Data Transmit Register
SPIDRR      = 0x6C  # SPI Data Receive Register
SPISSR      = 0x70  # SPI Slave Select Register
TXFIFO_OCY  = 0x74  # TX FIFO Occupancy
RXFIFO_OCY  = 0x78  # RX FIFO Occupancy

# GPIO registers
GPIO_BASE   = 0x41200000
GPIO_DATA   = 0x00
GPIO_TRI    = 0x04

SPI_BASE    = 0x41E00000

# SPI Flash commands (Winbond W25Q128)
CMD_WRITE_ENABLE     = 0x06
CMD_WRITE_DISABLE    = 0x04
CMD_READ_STATUS_1    = 0x05
CMD_READ_STATUS_2    = 0x35
CMD_WRITE_STATUS     = 0x01
CMD_PAGE_PROGRAM     = 0x02
CMD_SECTOR_ERASE     = 0x20  # 4KB
CMD_BLOCK_ERASE_32K  = 0x52
CMD_BLOCK_ERASE_64K  = 0xD8
CMD_CHIP_ERASE       = 0xC7
CMD_READ_DATA        = 0x03
CMD_FAST_READ        = 0x0B
CMD_JEDEC_ID         = 0x9F
CMD_RELEASE_PWRDOWN  = 0xAB

# Flash parameters
PAGE_SIZE   = 256
SECTOR_SIZE = 4096


def spi_reset(spi):
    """Reset SPI controller."""
    spi.write(SRR, 0x0000000A)
    time.sleep(0.01)  # Match debug_spi.py delay


def spi_init(spi):
    """Initialize SPI as master - exact copy from debug_spi.py."""
    # Reset first
    spi_reset(spi)
    
    # Debug
    print(f"[DEBUG] After reset: SPICR=0x{spi.read(SPICR):08X}, SPISR=0x{spi.read(SPISR):08X}")
    
    # Reset FIFOs + Master + SPE + Manual_SS
    spicr = (1 << 6) | (1 << 5) | (1 << 2) | (1 << 1) | (1 << 7)
    spi.write(SPICR, spicr)
    time.sleep(0.001)
    
    # Clear reset bits, keep Master + SPE + Manual_SS + MTI
    spicr = (1 << 2) | (1 << 1) | (1 << 7) | (1 << 8)
    spi.write(SPICR, spicr)
    time.sleep(0.001)
    
    print(f"[DEBUG] After init: SPICR=0x{spi.read(SPICR):08X}, SPISR=0x{spi.read(SPISR):08X}")


def spi_transfer(spi, tx_data, rx_len=0):
    """
    Perform SPI transfer - exact copy from debug_spi.py.
    
    Args:
        spi: MMIO object for SPI controller
        tx_data: bytes to transmit
        rx_len: number of additional bytes to receive
        
    Returns:
        bytes received (including dummy bytes during TX)
    """
    # Flush RX FIFO
    for _ in range(256):
        if spi.read(SPISR) & (1 << 0):  # RX_Empty
            break
        spi.read(SPIDRR)
    
    # Assert CS
    spi.write(SPISSR, 0xFFFFFFFE)
    time.sleep(0.0001)
    
    # Write TX data
    for b in tx_data:
        spi.write(SPIDTR, b)
    
    # Write dummy bytes for RX
    for _ in range(rx_len):
        spi.write(SPIDTR, 0x00)
    
    # Start transfer (clear MTI)
    spicr = spi.read(SPICR) & ~(1 << 8)
    spi.write(SPICR, spicr)
    
    # Wait for TX empty
    for i in range(1000):
        spisr = spi.read(SPISR)
        if spisr & (1 << 2):  # TX_Empty
            break
        time.sleep(0.001)
    else:
        print(f"[ERROR] SPI timeout: SPISR=0x{spi.read(SPISR):08X}")
        spi.write(SPISSR, 0xFFFFFFFF)
        spi.write(SPICR, spi.read(SPICR) | (1 << 8))
        return b''
    
    time.sleep(0.001)
    
    # Stop transfer (set MTI)
    spi.write(SPICR, spi.read(SPICR) | (1 << 8))
    
    # Deassert CS
    spi.write(SPISSR, 0xFFFFFFFF)
    
    # Read RX data
    rx_data = []
    for _ in range(len(tx_data) + rx_len):
        if spi.read(SPISR) & (1 << 0):  # RX_Empty
            break
        rx_data.append(spi.read(SPIDRR) & 0xFF)
    
    return bytes(rx_data)


def flash_read_jedec_id(spi):
    """Read JEDEC ID."""
    rx = spi_transfer(spi, bytes([CMD_JEDEC_ID]), rx_len=3)
    if len(rx) >= 4:
        return (rx[1], rx[2], rx[3])
    return (0, 0, 0)


def flash_write_enable(spi):
    """Enable write operations."""
    spi_transfer(spi, bytes([CMD_WRITE_ENABLE]))


def flash_read_status(spi):
    """Read status register 1."""
    rx = spi_transfer(spi, bytes([CMD_READ_STATUS_1]), rx_len=1)
    if len(rx) >= 2:
        return rx[1]
    return 0xFF


def flash_wait_ready(spi, timeout_sec=10):
    """Wait for flash to be ready (WIP=0)."""
    start = time.time()
    while time.time() - start < timeout_sec:
        status = flash_read_status(spi)
        if not (status & 0x01):  # WIP (write in progress) bit
            return True
        time.sleep(0.001)
    return False


def flash_erase_sector(spi, addr):
    """Erase 4KB sector."""
    flash_write_enable(spi)
    tx = bytes([CMD_SECTOR_ERASE, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF])
    spi_transfer(spi, tx)
    return flash_wait_ready(spi, timeout_sec=2)


def flash_page_program(spi, addr, data):
    """Program a page (up to 256 bytes)."""
    if len(data) > PAGE_SIZE:
        data = data[:PAGE_SIZE]
    
    flash_write_enable(spi)
    tx = bytes([CMD_PAGE_PROGRAM, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF]) + data
    spi_transfer(spi, tx)
    return flash_wait_ready(spi, timeout_sec=1)


def flash_read(spi, addr, length):
    """Read data from flash."""
    tx = bytes([CMD_READ_DATA, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF])
    rx = spi_transfer(spi, tx, rx_len=length)
    if len(rx) >= 4:
        return rx[4:]  # Skip command echo
    return b''


def program_flash(spi, data, verify=True):
    """Program data to flash starting at address 0."""
    total_len = len(data)
    
    # Calculate sectors to erase
    num_sectors = (total_len + SECTOR_SIZE - 1) // SECTOR_SIZE
    print(f"[INFO] Erasing {num_sectors} sectors ({num_sectors * SECTOR_SIZE} bytes)...")
    
    for i in range(num_sectors):
        addr = i * SECTOR_SIZE
        print(f"  Erasing sector {i+1}/{num_sectors} @ 0x{addr:06X}...", end='\r')
        if not flash_erase_sector(spi, addr):
            print(f"\n[ERROR] Erase timeout at sector {i}")
            return False
    print(f"  Erased {num_sectors} sectors" + " " * 20)
    
    # Program pages
    num_pages = (total_len + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"[INFO] Programming {num_pages} pages ({total_len} bytes)...")
    
    for i in range(num_pages):
        addr = i * PAGE_SIZE
        page_data = data[addr:addr + PAGE_SIZE]
        print(f"  Programming page {i+1}/{num_pages} @ 0x{addr:06X}...", end='\r')
        if not flash_page_program(spi, addr, page_data):
            print(f"\n[ERROR] Program timeout at page {i}")
            return False
    print(f"  Programmed {num_pages} pages" + " " * 20)
    
    # Verify
    if verify:
        print("[INFO] Verifying...")
        for i in range(num_pages):
            addr = i * PAGE_SIZE
            expected = data[addr:addr + PAGE_SIZE]
            actual = flash_read(spi, addr, len(expected))
            print(f"  Verifying page {i+1}/{num_pages} @ 0x{addr:06X}...", end='\r')
            if actual != expected:
                print(f"\n[ERROR] Verify failed at 0x{addr:06X}")
                print(f"  Expected: {expected[:16].hex()}...")
                print(f"  Actual:   {actual[:16].hex()}...")
                return False
        print(f"  Verified {num_pages} pages" + " " * 20)
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Direct SPI flash programmer")
    parser.add_argument("-o", "--overlay", required=True, help="Path to bitstream .bit file")
    parser.add_argument("-f", "--firmware", required=True, help="Path to firmware .bin file")
    parser.add_argument("-m", "--mode", choices=["flash_load", "flash_exec"], default="flash_exec",
                       help="Boot mode: flash_load or flash_exec")
    parser.add_argument("--verify", action="store_true", help="Verify after programming")
    parser.add_argument("--no-program", action="store_true", help="Skip programming, just test JEDEC ID")
    args = parser.parse_args()
    
    bitstream = Path(args.overlay).resolve()
    firmware = Path(args.firmware).resolve()
    
    if not bitstream.exists():
        print(f"[ERROR] Bitstream not found: {bitstream}")
        sys.exit(1)
    
    if not firmware.exists() and not args.no_program:
        print(f"[ERROR] Firmware not found: {firmware}")
        sys.exit(1)
    
    print("=== Direct SPI Flash Programmer ===")
    print(f"Bitstream: {bitstream}")
    if not args.no_program:
        print(f"Firmware:  {firmware}")
    print(f"Mode:      {args.mode}")
    
    # Step 1: Reset PL and load bitstream (EXACTLY like debug_spi.py)
    print("\n[1] Resetting PL and loading bitstream...")
    try:
        PL.reset()
        time.sleep(0.2)
    except Exception as e:
        print(f"  Warning: PL.reset() failed: {e}")
    
    overlay = Overlay(str(bitstream))
    print("  Bitstream loaded!")
    
    # Print IP addresses
    for name, info in overlay.ip_dict.items():
        print(f"  IP: {name} @ 0x{info.get('phys_addr', 0):08X}")
    
    # Step 2: Create MMIO objects
    print("\n[2] Creating MMIO interfaces...")
    gpio = MMIO(GPIO_BASE, 0x100)
    spi = MMIO(SPI_BASE, 0x100)
    
    # Step 3: Configure GPIO FIRST (before any SPI operations)
    print("\n[3] Configuring GPIO for PS SPI control...")
    gpio.write(GPIO_TRI, 0x00)  # Set as outputs
    gpio.write(GPIO_DATA, 0x1F)  # All bits high: rst=1, boot=1, exec=1, trst=1, spi_sel=1
    time.sleep(0.01)
    
    gpio_val = gpio.read(GPIO_DATA)
    print(f"  GPIO DATA = 0x{gpio_val:08X} (SPI_SEL={((gpio_val >> 4) & 1)}, should be 1 for PS)")
    
    # Step 4: Initialize SPI
    print("\n[4] Initializing SPI controller...")
    spi_init(spi)
    
    # Step 5: Wake up flash and read JEDEC ID
    print("\n[5] Reading flash JEDEC ID...")
    spi_transfer(spi, bytes([CMD_RELEASE_PWRDOWN]), rx_len=3)  # Wake up
    time.sleep(0.01)
    
    mfr, mem_type, capacity = flash_read_jedec_id(spi)
    print(f"  JEDEC ID: 0x{mfr:02X} 0x{mem_type:02X} 0x{capacity:02X}")
    
    if mfr == 0x00 or mfr == 0xFF:
        print("[ERROR] No flash detected!")
        sys.exit(1)
    
    # Decode flash
    if mfr == 0xEF:
        mfr_name = "Winbond"
    else:
        mfr_name = f"Unknown (0x{mfr:02X})"
    
    capacity_mb = 1 << (capacity - 20 + 1) if capacity >= 0x11 else 0
    print(f"  Flash: {mfr_name}, {capacity_mb}Mbit")
    
    # Step 6: Program flash (if not skipped)
    if not args.no_program:
        print(f"\n[6] Programming flash with {firmware}...")
        data = firmware.read_bytes()
        print(f"  Firmware size: {len(data)} bytes")
        
        if not program_flash(spi, data, verify=args.verify):
            print("\n[ERROR] Flash programming failed!")
            sys.exit(1)
        
        print("\n[INFO] Flash programming complete!")
    
    # Step 7: Configure GPIO for boot mode
    print(f"\n[7] Configuring for {args.mode} boot...")
    
    # Boot mode bits:
    # bit 0: rst_ni = 1 (not reset)
    # bit 1: boot_select = 1 (boot from flash)
    # bit 2: execute_from_flash = 1 for flash_exec, 0 for flash_load
    # bit 3: jtag_trst = 1
    # bit 4: spi_sel = 0 (X-HEEP controls flash now)
    
    if args.mode == "flash_exec":
        gpio_val = 0x0F  # rst=1, boot=1, exec=1, trst=1, spi_sel=0
    else:  # flash_load
        gpio_val = 0x0B  # rst=1, boot=1, exec=0, trst=1, spi_sel=0
    
    gpio.write(GPIO_DATA, gpio_val)
    time.sleep(0.01)
    
    # Toggle reset
    print("[8] Resetting X-HEEP...")
    gpio.write(GPIO_DATA, gpio_val & ~0x01)  # rst_ni = 0
    time.sleep(0.01)
    gpio.write(GPIO_DATA, gpio_val)  # rst_ni = 1
    
    final_gpio = gpio.read(GPIO_DATA)
    print(f"  Final GPIO = 0x{final_gpio:08X}")
    print(f"    boot_select = {(final_gpio >> 1) & 1}")
    print(f"    execute_from_flash = {(final_gpio >> 2) & 1}")
    print(f"    spi_sel = {(final_gpio >> 4) & 1} (should be 0 for X-HEEP)")
    
    print("\n=== Done! X-HEEP should now be executing from flash ===")


if __name__ == "__main__":
    main()
