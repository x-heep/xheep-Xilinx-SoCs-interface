#!/usr/bin/env python3
"""
Script diagnostico per debug AXI Quad SPI.
Stampa tutti i registri e verifica la configurazione.
"""

from pynq import Overlay, MMIO, PL
import time
import sys

# Registri AXI Quad SPI (PG153)
SRR         = 0x40  # Software Reset Register
SPICR       = 0x60  # SPI Control Register
SPISR       = 0x64  # SPI Status Register
SPIDTR      = 0x68  # SPI Data Transmit Register
SPIDRR      = 0x6C  # SPI Data Receive Register
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
GPIO2_TRI   = 0x0C

SPI_BASE    = 0x41E00000

def print_spicr(val):
    """Decodifica SPICR."""
    print(f"  SPICR = 0x{val:08X}")
    print(f"    LOOP (bit 0):          {(val >> 0) & 1}")
    print(f"    SPE (bit 1):           {(val >> 1) & 1}  <- System Enable (1=enabled)")
    print(f"    MASTER (bit 2):        {(val >> 2) & 1}  <- Master mode (1=master)")
    print(f"    CPOL (bit 3):          {(val >> 3) & 1}")
    print(f"    CPHA (bit 4):          {(val >> 4) & 1}")
    print(f"    TX_FIFO_Rst (bit 5):   {(val >> 5) & 1}")
    print(f"    RX_FIFO_Rst (bit 6):   {(val >> 6) & 1}")
    print(f"    Manual_SS (bit 7):     {(val >> 7) & 1}")
    print(f"    MTI (bit 8):           {(val >> 8) & 1}  <- Master Transaction Inhibit (0=enabled)")
    print(f"    LSB_First (bit 9):     {(val >> 9) & 1}")

def print_spisr(val):
    """Decodifica SPISR."""
    print(f"  SPISR = 0x{val:08X}")
    print(f"    RX_Empty (bit 0):      {(val >> 0) & 1}")
    print(f"    RX_Full (bit 1):       {(val >> 1) & 1}")
    print(f"    TX_Empty (bit 2):      {(val >> 2) & 1}")
    print(f"    TX_Full (bit 3):       {(val >> 3) & 1}")
    print(f"    MODF (bit 4):          {(val >> 4) & 1}  <- Mode Fault Error")
    print(f"    Slave_Mode (bit 5):    {(val >> 5) & 1}")
    print(f"    CPOL_CPHA_Err (bit 6): {(val >> 6) & 1}")
    print(f"    Slave_Sel (bit 7):     {(val >> 7) & 1}")
    print(f"    CMD_Error (bit 8):     {(val >> 8) & 1}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_spi.py <bitstream.bit>")
        sys.exit(1)

    bitstream = sys.argv[1]
    print(f"=== Debug AXI Quad SPI ===")
    print(f"Bitstream: {bitstream}")

    # Reset e carica
    print("\n[1] Reset PL e caricamento bitstream...")
    try:
        PL.reset()
        time.sleep(0.2)
    except:
        pass
    
    overlay = Overlay(bitstream)
    print("Bitstream caricato!")

    # Trova indirizzi
    gpio_addr = GPIO_BASE
    spi_addr = SPI_BASE
    for name, info in overlay.ip_dict.items():
        print(f"  IP: {name} @ 0x{info.get('phys_addr', 0):08X}")
        if "gpio" in name.lower():
            gpio_addr = info['phys_addr']
        if "spi" in name.lower():
            spi_addr = info['phys_addr']

    gpio = MMIO(gpio_addr, 0x100)
    spi = MMIO(spi_addr, 0x100)

    # [2] Configura GPIO
    print("\n[2] Configurazione GPIO...")
    gpio.write(GPIO_TRI, 0x00)  # CH1 output
    
    # Leggi valore corrente
    gpio_val = gpio.read(GPIO_DATA)
    print(f"  GPIO CH1 DATA (prima): 0x{gpio_val:08X}")
    
    # Imposta PS mode: bit 4 = 1
    # bit 0: rst_ni = 1, bit 1: bootsel=0, bit 2: exec_flash=0, bit 3: jtag_trst=1, bit 4: spi_sel=1
    gpio_val = 0x1F  # 0b11111
    gpio.write(GPIO_DATA, gpio_val)
    time.sleep(0.01)
    
    gpio_val_read = gpio.read(GPIO_DATA)
    print(f"  GPIO CH1 DATA (dopo):  0x{gpio_val_read:08X}")
    print(f"    SPI_SEL (bit 4): {(gpio_val_read >> 4) & 1}  <- 1=PS, 0=X-HEEP")

    # [3] Leggi registri SPI prima del reset
    print("\n[3] Registri SPI PRIMA del reset:")
    print_spicr(spi.read(SPICR))
    print_spisr(spi.read(SPISR))
    print(f"  SPISSR = 0x{spi.read(SPISSR):08X}")
    print(f"  TXFIFO_OCY = {spi.read(TXFIFO_OCY)}")
    print(f"  RXFIFO_OCY = {spi.read(RXFIFO_OCY)}")

    # [4] Reset SPI
    print("\n[4] Reset del controller SPI...")
    spi.write(SRR, 0x0000000A)
    time.sleep(0.01)

    # [5] Registri dopo reset
    print("\n[5] Registri SPI DOPO il reset:")
    print_spicr(spi.read(SPICR))
    print_spisr(spi.read(SPISR))

    # [6] Configura SPI
    print("\n[6] Configurazione SPI come master...")
    # Reset FIFOs + Master + SPE + Manual_SS
    spicr = (1 << 6) | (1 << 5) | (1 << 2) | (1 << 1) | (1 << 7)
    print(f"  Writing SPICR = 0x{spicr:08X} (reset FIFOs)")
    spi.write(SPICR, spicr)
    time.sleep(0.001)

    # Clear reset bits, mantieni config + MTI
    spicr = (1 << 2) | (1 << 1) | (1 << 7) | (1 << 8)
    print(f"  Writing SPICR = 0x{spicr:08X} (normal + MTI)")
    spi.write(SPICR, spicr)
    time.sleep(0.001)

    print("\n[7] Registri SPI dopo configurazione:")
    print_spicr(spi.read(SPICR))
    print_spisr(spi.read(SPISR))

    # [8] Test transazione
    print("\n[8] Test transazione JEDEC ID (0x9F)...")
    
    # Assert CS
    print("  SPISSR = 0xFFFFFFFE (CS0 active)")
    spi.write(SPISSR, 0xFFFFFFFE)
    time.sleep(0.0001)

    # Scrivi comando
    print("  Writing DTR: 0x9F (JEDEC ID cmd)")
    spi.write(SPIDTR, 0x9F)
    spi.write(SPIDTR, 0x00)
    spi.write(SPIDTR, 0x00)
    spi.write(SPIDTR, 0x00)

    print("\n  Stato dopo scrittura TX:")
    print_spisr(spi.read(SPISR))
    print(f"  TXFIFO_OCY = {spi.read(TXFIFO_OCY)}")

    # Start transfer (clear MTI)
    spicr = spi.read(SPICR)
    print(f"\n  SPICR prima di clear MTI: 0x{spicr:08X}")
    spicr_new = spicr & ~(1 << 8)
    print(f"  Writing SPICR = 0x{spicr_new:08X} (clear MTI - START)")
    spi.write(SPICR, spicr_new)
    
    # Attendi TX empty
    print("\n  Attesa TX empty...")
    for i in range(100):
        spisr = spi.read(SPISR)
        if spisr & (1 << 2):  # TX Empty
            print(f"  TX Empty dopo {i} iterazioni")
            break
        time.sleep(0.001)
    else:
        print("  TIMEOUT: TX non si svuota!")
    
    time.sleep(0.01)
    
    print("\n  Stato dopo transazione:")
    print_spisr(spi.read(SPISR))
    print(f"  RXFIFO_OCY = {spi.read(RXFIFO_OCY)}")

    # Leggi RX
    print("\n[9] Lettura RX FIFO:")
    rx_data = []
    for i in range(16):
        spisr = spi.read(SPISR)
        if spisr & (1 << 0):  # RX Empty
            break
        byte = spi.read(SPIDRR) & 0xFF
        rx_data.append(byte)
        print(f"  RX[{i}] = 0x{byte:02X}")
    
    if not rx_data:
        print("  RX FIFO vuoto!")
    else:
        print(f"\n  RX Data: {' '.join(f'{b:02X}' for b in rx_data)}")
        if len(rx_data) >= 4:
            print(f"  JEDEC ID: 0x{rx_data[1]:02X} 0x{rx_data[2]:02X} 0x{rx_data[3]:02X}")

    # Deassert CS e re-enable MTI
    spi.write(SPISSR, 0xFFFFFFFF)
    spicr = spi.read(SPICR) | (1 << 8)
    spi.write(SPICR, spicr)

    print("\n[10] Fine diagnosi")
    print("=" * 50)

if __name__ == "__main__":
    main()
