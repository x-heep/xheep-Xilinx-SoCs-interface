#!/usr/bin/env python3
"""
X-HEEP Quad SPI Flash Test (MTD Mode)

Tests PS <-> Quad SPI Flash communication via MTD interface.
The GPIO bit 4 controls the MUX: 0=X-HEEP, 1=PS

For W25Q flash in Quad mode.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from xheepDriver import xheepDriver, xheepGPIO, xheepSPI, log
from pynq import Overlay


def test_mtd_flash(mtd_dev: Path) -> bool:
    """Test flash via MTD device"""
    import subprocess

    log("info", "\n[Test] Reading flash info via MTD...")

    try:
        # Get flash info
        result = subprocess.run(
            ["mtdinfo", str(mtd_dev)],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            log("info", "MTD Info:")
            for line in result.stdout.split('\n')[:10]:
                if line.strip():
                    log("info", f"  {line}")
            return True
        else:
            log("warning", f"mtdinfo failed: {result.stderr}")

            # Try reading first 256 bytes
            log("info", "Attempting direct read of first 256 bytes...")
            with open(mtd_dev, 'rb') as f:
                data = f.read(256)

            log("info", f"Read {len(data)} bytes from flash")
            log("info", f"First 16 bytes: {data[:16].hex().upper()}")

            # Check if not all 0xFF or 0x00
            if data == b'\xFF' * len(data):
                log("warning", "Flash returns all 0xFF - may be erased or not responding")
                return False
            elif data == b'\x00' * len(data):
                log("warning", "Flash returns all 0x00 - communication issue")
                return False
            else:
                log("info", "✓ Flash data looks valid")
                return True

    except FileNotFoundError:
        log("warning", "mtd-utils not installed. Install with: apt-get install mtd-utils")
        log("info", "Trying direct read...")

        try:
            with open(mtd_dev, 'rb') as f:
                data = f.read(256)
            log("info", f"✓ Direct read successful: {len(data)} bytes")
            log("info", f"First 16 bytes: {data[:16].hex().upper()}")
            return True
        except Exception as e:
            log("error", f"Direct read failed: {e}")
            return False

    except Exception as e:
        log("error", f"MTD test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_spi_communication(xheep, use_existing: bool = False):
    """Test SPI communication with flash"""
    log("info", "=" * 60)
    log("info", "X-HEEP Quad SPI Flash Test (MTD Mode)")
    log("info", "=" * 60)

    # Check SPI availability
    if not hasattr(xheep, 'spi') or xheep.spi is None:
        log("critical", "SPI interface not available")
        return False

    spi_addr = xheep.spi.getAddr()
    log("info", f"SPI Controller: 0x{spi_addr:08X}")

    # Step 1: Switch MUX to PS
    log("info", "\n[Step 1] Switching SPI flash MUX to PS control...")
    gpio_before = xheep.gpio.getChannel(0)
    log("debug", f"GPIO CH1 before: 0x{gpio_before:02X}")

    xheep.gpio.setSpiFlashControl(True)
    time.sleep(0.1)

    gpio_after = xheep.gpio.getChannel(0)
    log("debug", f"GPIO CH1 after:  0x{gpio_after:02X}")

    if not xheep.gpio.getBit(0, xheep.gpio.BIT_SPI_SEL):
        log("error", "Failed to switch MUX!")
        return False
    log("info", "✓ MUX switched to PS (bit 4 = 1)")

    # Step 2: Ensure overlay is bound
    log("info", "\n[Step 2] Binding Quad SPI device tree overlay...")
    if not use_existing:
        log("info", "✓ Overlay already bound during driver init")
    else:
        # Make sure overlay is loaded
        xheep.spi.unbind()  # Clean up any old overlay
        time.sleep(0.2)
        xheep.spi.bind()    # Load fresh overlay
        log("info", "✓ Overlay bound successfully")

    # Step 3: Find MTD device
    log("info", "\n[Step 3] Finding MTD device...")
    mtd_dev = xheep.spi.getMtdDev()
    spi_dev = xheep.spi.getSpiDev()

    if mtd_dev:
        log("info", f"✓ Found MTD device: {mtd_dev}")
    else:
        log("warning", "MTD device not found")

    if spi_dev:
        log("info", f"✓ Found SPI device: {spi_dev}")
    else:
        log("debug", "SPI device not found (expected with MTD mode)")

    if not mtd_dev:
        log("error", "No MTD device available!")
        log("info", "Check: ls -l /dev/mtd* && dmesg | grep -i spi")
        xheep.gpio.setSpiFlashControl(False)
        return False

    # Step 4: Test flash communication
    log("info", "\n[Step 4] Testing flash communication...")
    success = test_mtd_flash(mtd_dev)

    # Step 5: Switch MUX back
    log("info", "\n[Step 5] Switching MUX back to X-HEEP...")
    xheep.gpio.setSpiFlashControl(False)
    time.sleep(0.1)

    if xheep.gpio.getBit(0, xheep.gpio.BIT_SPI_SEL):
        log("warning", "MUX bit not cleared!")
    else:
        log("info", "✓ MUX switched back to X-HEEP (bit 4 = 0)")

    # Summary
    log("info", "\n" + "=" * 60)
    if success:
        log("info", "✅ TEST PASSED: Quad SPI communication successful!")
    else:
        log("warning", "❌ TEST FAILED: Communication issues detected")
    log("info", "=" * 60)

    return success


def cleanup_old_overlay():
    """Clean up old SPI overlay and cache"""
    import subprocess

    log("info", "Cleaning up old overlay and cache...")

    # Remove old DTS files
    try:
        for f in Path("dts").glob("*-patched.dts"):
            f.unlink()
        for f in Path("dts").glob("*-overlay.dtbo"):
            f.unlink()
        log("debug", "  Removed old DTS files")
    except Exception as e:
        log("debug", f"  DTS cleanup: {e}")

    # Remove overlay
    overlay_dir = Path("/sys/kernel/config/device-tree/overlays/axiquadspi")
    if overlay_dir.exists():
        try:
            overlay_dir.rmdir()
            log("debug", "  Removed old overlay")
        except Exception as e:
            log("debug", f"  Overlay removal: {e}")

    # Clear Python cache
    try:
        subprocess.run(
            ["find", ".", "-name", "*.pyc", "-delete"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ["find", ".", "-type", "d", "-name", "__pycache__", "-exec", "rm", "-rf", "{}", "+"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        log("debug", "  Cleared Python cache")
    except Exception as e:
        log("debug", f"  Cache cleanup: {e}")

    log("info", "✓ Cleanup complete")


def main():
    parser = argparse.ArgumentParser(
        description="Test Quad SPI flash via MTD interface"
    )
    parser.add_argument(
        "--o", "--overlay",
        dest="overlay",
        type=Path,
        help="Path to bitstream (.bit)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reload bitstream"
    )

    args = parser.parse_args()

    try:
        # Always cleanup old overlay first
        cleanup_old_overlay()
        # Load or reuse bitstream
        if args.overlay and (args.force or not Path("/tmp/.xheep_state").exists()):
            if not args.overlay.exists():
                log("critical", f"Bitstream not found: {args.overlay}")
                return 1

            log("info", f"Loading bitstream: {args.overlay}")
            xheep = xheepDriver(str(args.overlay))
            use_existing = False

        else:
            # Reuse existing
            log("info", "Reusing existing bitstream...")

            bit_path = args.overlay if args.overlay else Path("xilinx_core_v_mini_mcu_wrapper.bit")

            if not bit_path.exists():
                log("critical", f"Bitstream not found: {bit_path}")
                log("info", "Specify with --o <bitstream.bit>")
                return 1

            log("info", f"Using bitstream metadata: {bit_path}")
            ol = Overlay(str(bit_path), download=False)

            gpio_ip = ol.ip_dict.get("axi_gpio")
            spi_ip = ol.ip_dict.get("axi_quad_spi")

            if not gpio_ip or not spi_ip:
                log("critical", "Required IPs not found in overlay")
                return 1

            # Create stub
            class XheepStub:
                pass

            xheep = XheepStub()
            xheep.gpio = xheepGPIO(
                ol,
                int(gpio_ip["phys_addr"]),
                int(gpio_ip["addr_range"])
            )

            # SPI IRQ = UART_IRQ + 2 (at concat In2)
            board = os.getenv("BOARD", "pynq-z2").lower()
            spi_irq = 92 if board == "aup-zu3" else 32

            xheep.spi = xheepSPI(
                int(spi_ip["phys_addr"]),
                spi_irq,
                use_mtd=True  # Quad SPI uses MTD
            )
            xheep.spi.bind()
            use_existing = True

        # Run test
        success = test_spi_communication(xheep, use_existing)
        return 0 if success else 1

    except KeyboardInterrupt:
        log("warning", "\nInterrupted by user")
        return 130
    except Exception as e:
        log("critical", f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
