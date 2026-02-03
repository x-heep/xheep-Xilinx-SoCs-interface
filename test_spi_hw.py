#!/usr/bin/env python3
"""
Direct hardware test for AXI Quad SPI
Bypasses Linux driver to test raw MMIO access
"""

import sys
import time
from pathlib import Path
from pynq import MMIO, Overlay

# AXI Quad SPI Register Offsets (from PG153)
SRR    = 0x40  # Software Reset Register
SPICR  = 0x60  # SPI Control Register
SPISR  = 0x64  # SPI Status Register
SPIDTR = 0x68  # SPI Data Transmit Register
SPIDRR = 0x6C  # SPI Data Receive Register
SPISSR = 0x70  # SPI Slave Select Register
DGIER  = 0x1C  # Device Global Interrupt Enable Register
IPISR  = 0x20  # IP Interrupt Status Register
IPIER  = 0x28  # IP Interrupt Enable Register

# Control Register Bits
SPICR_MASTER    = (1 << 2)  # Master mode
SPICR_SPE       = (1 << 1)  # System enable
SPICR_MANUAL_SS = (1 << 7)  # Manual slave select
SPICR_TXRST     = (1 << 5)  # TX FIFO reset
SPICR_RXRST     = (1 << 6)  # RX FIFO reset

# Status Register Bits
SPISR_TX_EMPTY = (1 << 2)
SPISR_TX_FULL  = (1 << 3)
SPISR_RX_EMPTY = (1 << 0)
SPISR_RX_FULL  = (1 << 1)

def reset_spi(mmio: MMIO):
    """Software reset of SPI controller"""
    print("  Resetting SPI controller...")
    mmio.write(SRR, 0x0000000A)  # Magic reset value
    time.sleep(0.01)

def configure_spi(mmio: MMIO):
    """Configure SPI in master mode, manual SS"""
    print("  Configuring SPI...")

    # Disable SPI
    mmio.write(SPICR, 0)

    # Reset FIFOs
    ctrl = SPICR_TXRST | SPICR_RXRST | SPICR_MASTER | SPICR_MANUAL_SS
    mmio.write(SPICR, ctrl)
    time.sleep(0.01)

    # Enable SPI in master mode with manual SS
    ctrl = SPICR_MASTER | SPICR_MANUAL_SS | SPICR_SPE
    mmio.write(SPICR, ctrl)

    # Deselect all slaves (SS = 1)
    mmio.write(SPISSR, 0xFFFFFFFF)

    print(f"  SPICR = 0x{mmio.read(SPICR):08X}")
    print(f"  SPISR = 0x{mmio.read(SPISR):08X}")

def spi_transfer(mmio: MMIO, data: int) -> int:
    """Transfer one byte and read response"""
    # Select slave (SS0 = 0)
    mmio.write(SPISSR, 0xFFFFFFFE)

    # Wait for TX FIFO empty
    timeout = 1000
    while timeout > 0:
        sr = mmio.read(SPISR)
        if sr & SPISR_TX_EMPTY:
            break
        timeout -= 1
        time.sleep(0.001)

    if timeout == 0:
        print("  ERROR: TX FIFO not empty!")
        return 0xFF

    # Write data
    mmio.write(SPIDTR, data & 0xFF)

    # Wait for RX FIFO not empty
    timeout = 1000
    while timeout > 0:
        sr = mmio.read(SPISR)
        if not (sr & SPISR_RX_EMPTY):
            break
        timeout -= 1
        time.sleep(0.001)

    if timeout == 0:
        print("  ERROR: RX FIFO empty (no response)!")
        # Deselect slave
        mmio.write(SPISSR, 0xFFFFFFFF)
        return 0xFF

    # Read response
    resp = mmio.read(SPIDRR) & 0xFF

    # Deselect slave
    mmio.write(SPISSR, 0xFFFFFFFF)

    return resp

def read_jedec_id(mmio: MMIO):
    """Read JEDEC ID using direct SPI transfer"""
    print("\n[Test] Reading JEDEC ID (0x9F)...")

    # Send command 0x9F
    print("  TX: 0x9F (JEDEC ID command)")
    spi_transfer(mmio, 0x9F)

    # Read 3 bytes
    mfg = spi_transfer(mmio, 0x00)
    dev1 = spi_transfer(mmio, 0x00)
    dev2 = spi_transfer(mmio, 0x00)

    print(f"  RX: 0x{mfg:02X} 0x{dev1:02X} 0x{dev2:02X}")

    if mfg == 0xFF and dev1 == 0xFF and dev2 == 0xFF:
        print("  ❌ All 0xFF - Flash not responding or not powered")
        return False
    elif mfg == 0x00 and dev1 == 0x00 and dev2 == 0x00:
        print("  ❌ All 0x00 - Communication problem")
        return False
    else:
        manufacturers = {
            0xEF: "Winbond",
            0xC2: "Macronix",
            0x20: "Micron",
        }
        print(f"  ✅ Manufacturer: {manufacturers.get(mfg, 'Unknown')} (0x{mfg:02X})")
        print(f"  ✅ Device ID: 0x{(dev1 << 8) | dev2:04X}")
        return True

def main():
    print("=" * 60)
    print("Direct SPI Hardware Test")
    print("=" * 60)

    # Load overlay metadata
    bit_path = Path("xilinx_core_v_mini_mcu_wrapper.bit")
    if not bit_path.exists():
        print(f"ERROR: Bitstream not found: {bit_path}")
        return 1

    ol = Overlay(str(bit_path), download=False)

    # Get SPI IP address
    spi_ip = ol.ip_dict.get("axi_quad_spi")
    if not spi_ip:
        print("ERROR: SPI IP not found in overlay")
        return 1

    spi_addr = int(spi_ip["phys_addr"])
    spi_range = int(spi_ip["addr_range"])

    print(f"\nSPI Controller: 0x{spi_addr:08X} (range: 0x{spi_range:X})")

    # Get GPIO for MUX control
    gpio_ip = ol.ip_dict["axi_gpio"]
    gpio_addr = int(gpio_ip["phys_addr"])
    gpio_range = int(gpio_ip["addr_range"])

    gpio_mmio = MMIO(gpio_addr, gpio_range)

    # Switch MUX to PS
    print("\n[Setup] Switching MUX to PS control...")
    CH1_DATA = 0x00
    gpio_val = int(gpio_mmio.read(CH1_DATA))
    print(f"  GPIO CH1 before: 0x{gpio_val:02X}")

    gpio_val |= (1 << 4)  # Set bit 4
    gpio_mmio.write(CH1_DATA, gpio_val)
    time.sleep(0.1)

    gpio_val = int(gpio_mmio.read(CH1_DATA))
    print(f"  GPIO CH1 after:  0x{gpio_val:02X}")

    if not (gpio_val & (1 << 4)):
        print("  ❌ Failed to switch MUX!")
        return 1
    print("  ✅ MUX switched to PS")

    # Direct MMIO access to SPI
    print(f"\n[Setup] Opening SPI MMIO at 0x{spi_addr:08X}...")
    mmio = MMIO(spi_addr, spi_range)

    # Read initial registers
    print("\nInitial Register State:")
    print(f"  SPICR  (0x60) = 0x{mmio.read(SPICR):08X}")
    print(f"  SPISR  (0x64) = 0x{mmio.read(SPISR):08X}")
    print(f"  SPISSR (0x70) = 0x{mmio.read(SPISSR):08X}")

    # Reset and configure
    reset_spi(mmio)
    configure_spi(mmio)

    # Test communication
    success = read_jedec_id(mmio)

    # Switch MUX back to X-HEEP
    print("\n[Cleanup] Switching MUX back to X-HEEP...")
    gpio_val = int(gpio_mmio.read(CH1_DATA))
    gpio_val &= ~(1 << 4)  # Clear bit 4
    gpio_mmio.write(CH1_DATA, gpio_val)

    print("\n" + "=" * 60)
    if success:
        print("✅ TEST PASSED: SPI hardware is working!")
    else:
        print("❌ TEST FAILED: SPI hardware not responding")
    print("=" * 60)

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
