#!/usr/bin/env python3
import sys
import time
sys.path.insert(0, 'src')

from pynq import Overlay
from xheepDriver import xheepGPIO

bit = "xilinx_core_v_mini_mcu_wrapper.bit"
ol = Overlay(bit, download=False)
gpio_ip = ol.ip_dict["axi_gpio"]

gpio = xheepGPIO(ol, int(gpio_ip["phys_addr"]), int(gpio_ip["addr_range"]))

print("Testing SPI flash multiplexer control...")
print("Watch your debug LED - it should toggle")

for i in range(5):
    print(f"\n[{i}] Setting to X-HEEP (LED should be OFF)")
    gpio.setSpiFlashControl(False)
    ch = gpio.getChannel(0)
    print(f"    GPIO Channel 0 value: 0b{ch:05b} (bit 4 = {(ch >> 4) & 1})")
    time.sleep(2)
    
    print(f"[{i}] Setting to PS (LED should be ON)")
    gpio.setSpiFlashControl(True)
    ch = gpio.getChannel(0)
    print(f"    GPIO Channel 0 value: 0b{ch:05b} (bit 4 = {(ch >> 4) & 1})")
    time.sleep(2)

print("\nFinal: Setting back to X-HEEP")
gpio.setSpiFlashControl(False)