#!/usr/bin/env python3
"""Debug script to check SPI driver binding and configuration"""

import sys
from pathlib import Path
import subprocess

def run_cmd(cmd):
    """Run command and return output"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr

def main():
    print("=" * 60)
    print("SPI Debug Information")
    print("=" * 60)

    # Check platform devices
    print("\n1. Platform Devices:")
    print(run_cmd("ls -la /sys/bus/platform/devices/*spi* 2>/dev/null"))

    # Check SPI driver binding
    print("\n2. SPI Driver Binding:")
    spi_devs = list(Path("/sys/bus/platform/devices").glob("*spi*"))
    for dev in spi_devs:
        print(f"\nDevice: {dev.name}")
        driver_link = dev / "driver"
        if driver_link.exists():
            print(f"  Driver: {driver_link.resolve().name}")
        else:
            print("  Driver: NOT BOUND")

        # Check resources
        if (dev / "resources").exists():
            print("  Resources:")
            print("    " + (dev / "resources").read_text().replace("\n", "\n    "))

    # Check available drivers
    print("\n3. Available SPI Drivers:")
    print(run_cmd("ls -la /sys/bus/platform/drivers/*spi* 2>/dev/null"))

    # Check SPI devices
    print("\n4. SPI Character Devices:")
    print(run_cmd("ls -la /dev/spidev* 2>/dev/null"))

    # Check MTD devices
    print("\n5. MTD Devices:")
    print(run_cmd("ls -la /dev/mtd* 2>/dev/null"))
    print(run_cmd("cat /sys/class/mtd/*/name 2>/dev/null"))

    # Check kernel messages
    print("\n6. Kernel Messages (SPI related):")
    print(run_cmd("dmesg | grep -i 'spi\\|a0030000' | tail -20"))

    # Check device tree overlay
    print("\n7. Device Tree Overlays:")
    print(run_cmd("ls -la /sys/kernel/config/device-tree/overlays/"))

    # Check patched DTS
    print("\n8. Patched DTS Content:")
    dts_path = Path("dts/spi-patched.dts")
    if dts_path.exists():
        print(dts_path.read_text())
    else:
        print("  Not found")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
