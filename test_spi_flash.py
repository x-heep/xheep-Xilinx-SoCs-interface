#!/usr/bin/env python3
"""
X-HEEP SPI Flash Communication Test

This test verifies PS <-> SPI Flash communication through the multiplexed interface.
The GPIO bit 4 (channel 1) controls the MUX:
  - 0: X-HEEP is the master
  - 1: PS is the master

Test procedure:
1. Load/reuse the X-HEEP overlay
2. Read the SPI controller address from the loaded overlay
3. Switch MUX to PS control (GPIO bit 4 = 1)
4. Bind the SPI device tree overlay
5. Open the SPI device (/dev/spidevX.Y)
6. Send test commands to the flash (read ID, status)
7. Switch MUX back to X-HEEP control (GPIO bit 4 = 0)
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from xheepDriver import xheepDriver, xheepGPIO, xheepSPI, log
from pynq import Overlay


def read_flash_id(spi_dev: Path) -> bytes:
    """
    Read JEDEC ID from SPI flash (command 0x9F).
    Returns: Manufacturer ID (1 byte) + Device ID (2 bytes)
    """
    import spidev

    spi = spidev.SpiDev()
    # Parse /dev/spidevX.Y to get bus and device numbers
    dev_name = spi_dev.name
    if not dev_name.startswith("spidev"):
        raise ValueError(f"Invalid SPI device: {spi_dev}")

    # Extract X.Y from spidevX.Y
    parts = dev_name.replace("spidev", "").split(".")
    if len(parts) != 2:
        raise ValueError(f"Cannot parse SPI device name: {spi_dev}")

    bus = int(parts[0])
    device = int(parts[1])

    log("info", f"Opening SPI device: bus={bus}, device={device}")
    spi.open(bus, device)

    # Configure SPI: mode 0, 10 MHz (matches DTS setting)
    spi.max_speed_hz = 10_000_000
    spi.mode = 0
    spi.bits_per_word = 8

    # Send JEDEC ID command (0x9F) and read 3 bytes response
    cmd = [0x9F, 0x00, 0x00, 0x00]
    response = spi.xfer2(cmd)

    spi.close()

    # Response format: [9F, MFG_ID, DEV_ID_HIGH, DEV_ID_LOW]
    # Return the 3 ID bytes
    return bytes(response[1:4])


def read_flash_status(spi_dev: Path) -> int:
    """
    Read status register from SPI flash (command 0x05).
    Returns: Status register value (1 byte)
    """
    import spidev

    spi = spidev.SpiDev()
    dev_name = spi_dev.name
    parts = dev_name.replace("spidev", "").split(".")
    bus = int(parts[0])
    device = int(parts[1])

    spi.open(bus, device)
    spi.max_speed_hz = 10_000_000
    spi.mode = 0
    spi.bits_per_word = 8

    # Send Read Status Register command (0x05)
    cmd = [0x05, 0x00]
    response = spi.xfer2(cmd)

    spi.close()

    return response[1]


def test_spi_flash_communication(xheep, use_existing: bool = False):
    """
    Test SPI communication with the flash memory.

    Args:
        xheep: xheepDriver instance or stub with gpio and spi attributes
        use_existing: If True, reuse existing bitstream
    """
    log("info", "=" * 60)
    log("info", "X-HEEP SPI Flash Communication Test")
    log("info", "=" * 60)

    # Check if SPI is available
    if not hasattr(xheep, 'spi') or xheep.spi is None:
        log("critical", "SPI interface not available in this overlay")
        log("error", "Make sure your bitstream includes the AXI Quad SPI IP")
        return False

    # Display SPI controller address
    spi_addr = xheep.spi.getAddr()
    log("info", f"SPI Controller Address: 0x{spi_addr:08X}")

    # Step 1: Switch MUX to PS control
    log("info", "\n[Step 1] Switching SPI flash MUX to PS control...")
    gpio_ch1_before = xheep.gpio.getChannel(0)
    log("debug", f"GPIO CH1 before: 0x{gpio_ch1_before:02X}")

    xheep.gpio.setSpiFlashControl(True)  # Sets bit 4 = 1
    time.sleep(0.1)

    gpio_ch1_after = xheep.gpio.getChannel(0)
    log("debug", f"GPIO CH1 after:  0x{gpio_ch1_after:02X}")

    bit4_value = xheep.gpio.getBit(0, xheep.gpio.BIT_SPI_SEL)
    if bit4_value != 1:
        log("error", f"Failed to set MUX control bit! Expected 1, got {bit4_value}")
        return False

    log("info", "✓ MUX switched to PS (bit 4 = 1)")

    # Step 2: Bind SPI overlay if not already done
    log("info", "\n[Step 2] Binding SPI device tree overlay...")
    if not use_existing:
        # Already bound in xheepDriver.__init__
        log("info", "✓ SPI overlay already bound during driver init")
    else:
        # Need to bind if reusing existing bitstream
        xheep.spi.bind()
        log("info", "✓ SPI overlay bound")

    # Step 3: Find SPI device
    log("info", "\n[Step 3] Finding SPI device node...")
    spi_dev = xheep.spi.getSpiDev()
    mtd_dev = xheep.spi.getMtdDev()

    if spi_dev:
        log("info", f"✓ Found SPI device: {spi_dev}")
    else:
        log("warning", "SPI device not found (/dev/spidevX.Y)")

    if mtd_dev:
        log("info", f"✓ Found MTD device: {mtd_dev}")
    else:
        log("warning", "MTD device not found (/dev/mtdX)")

    if not spi_dev:
        log("error", "Cannot proceed without SPI device node")
        log("info", "Debug: Check 'ls -l /dev/spidev*' and 'dmesg | grep spi'")
        xheep.gpio.setSpiFlashControl(False)
        return False

    # Step 4: Communicate with flash
    success = True
    try:
        log("info", "\n[Step 4] Reading flash JEDEC ID...")
        flash_id = read_flash_id(spi_dev)
        log("info", f"✓ Flash JEDEC ID: {flash_id.hex().upper()}")

        # Decode common flash IDs
        mfg_id = flash_id[0]
        dev_id = (flash_id[1] << 8) | flash_id[2]

        manufacturers = {
            0xEF: "Winbond",
            0xC2: "Macronix",
            0x20: "Micron/Numonyx/ST",
            0x01: "Spansion/Cypress",
            0xBF: "SST/Microchip",
            0x1F: "Atmel",
        }

        mfg_name = manufacturers.get(mfg_id, "Unknown")
        log("info", f"  Manufacturer: {mfg_name} (0x{mfg_id:02X})")
        log("info", f"  Device ID: 0x{dev_id:04X}")

        # Check for invalid ID (all 0xFF or all 0x00)
        if flash_id == b'\xFF\xFF\xFF':
            log("warning", "Flash returned 0xFFFFFF - may not be connected or powered")
            success = False
        elif flash_id == b'\x00\x00\x00':
            log("warning", "Flash returned 0x000000 - communication issue")
            success = False

        log("info", "\n[Step 5] Reading flash status register...")
        status = read_flash_status(spi_dev)
        log("info", f"✓ Flash Status Register: 0x{status:02X}")
        log("info", f"  WIP (Write In Progress): {(status >> 0) & 1}")
        log("info", f"  WEL (Write Enable Latch): {(status >> 1) & 1}")
        log("info", f"  Block Protect bits: {(status >> 2) & 0x7}")

    except ImportError:
        log("error", "spidev module not found. Install with: pip3 install spidev")
        success = False
    except Exception as e:
        log("error", f"Flash communication failed: {e}")
        import traceback
        traceback.print_exc()
        success = False

    # Step 6: Switch MUX back to X-HEEP
    log("info", "\n[Step 6] Switching SPI flash MUX back to X-HEEP control...")
    xheep.gpio.setSpiFlashControl(False)  # Sets bit 4 = 0
    time.sleep(0.1)

    bit4_value = xheep.gpio.getBit(0, xheep.gpio.BIT_SPI_SEL)
    if bit4_value != 0:
        log("warning", f"MUX control bit not cleared! Expected 0, got {bit4_value}")
    else:
        log("info", "✓ MUX switched back to X-HEEP (bit 4 = 0)")

    # Summary
    log("info", "\n" + "=" * 60)
    if success:
        log("info", "TEST PASSED: SPI communication successful!")
    else:
        log("warning", "TEST FAILED: SPI communication issues detected")
    log("info", "=" * 60)

    return success


def main():
    parser = argparse.ArgumentParser(
        description="Test SPI flash communication via PS multiplexed interface"
    )
    parser.add_argument(
        "-o", "--overlay",
        type=Path,
        help="Path to X-HEEP bitstream (.bit). If not provided, reuses existing overlay."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reload of bitstream even if already loaded"
    )

    args = parser.parse_args()

    try:
        if args.overlay and (args.force or not Path("/tmp/.xheep_state").exists()):
            # Load fresh bitstream
            if not args.overlay.exists():
                log("critical", f"Bitstream not found: {args.overlay}")
                return 1

            log("info", f"Loading bitstream: {args.overlay}")
            xheep = xheepDriver(str(args.overlay))
            use_existing = False

        else:
            # Reuse existing bitstream
            log("info", "Reusing existing bitstream...")

            if args.overlay:
                bit_path = args.overlay
            else:
                # Try to find bitstream in common locations
                candidates = [
                    Path("bitstream/xheep_system_wrapper.bit"),
                    Path("xheep_system_wrapper.bit"),
                ]
                bit_path = None
                for c in candidates:
                    if c.exists():
                        bit_path = c
                        break

                if not bit_path:
                    log("critical", "No bitstream specified and none found in default locations")
                    log("info", "Use --overlay to specify bitstream path")
                    return 1

            log("info", f"Using bitstream metadata from: {bit_path}")
            ol = Overlay(str(bit_path), download=False)

            gpio_ip = ol.ip_dict["axi_gpio"]
            spi_ip = ol.ip_dict.get("axi_quad_spi")

            if not spi_ip:
                log("critical", "SPI IP not found in overlay!")
                return 1

            # Create stub object with gpio and spi
            class XheepStub:
                pass

            xheep = XheepStub()
            xheep.gpio = xheepGPIO(
                ol,
                int(gpio_ip["phys_addr"]),
                int(gpio_ip["addr_range"])
            )

            # SPI IRQ is at concat position 2 (In2), UART is at position 0 (In0)
            # So SPI_IRQ = UART_IRQ + 2
            board = os.getenv("BOARD", "pynq-z2").lower()
            if board == "aup-zu3":
                spi_irq = 92  # UltraScale+: UART=90 (In0), In1=91, SPI=92 (In2)
            else:
                spi_irq = 32  # Zynq-7000: UART=30 (In0), In1=31, SPI=32 (In2)

            # Use MTD mode for Quad SPI
            xheep.spi = xheepSPI(
                int(spi_ip["phys_addr"]),
                spi_irq,
                use_mtd=True
            )
            # Bind the SPI overlay
            xheep.spi.bind()
            use_existing = True

        # Run the test
        success = test_spi_flash_communication(xheep, use_existing)

        return 0 if success else 1

    except KeyboardInterrupt:
        log("warning", "\nTest interrupted by user")
        return 130
    except Exception as e:
        log("critical", f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
