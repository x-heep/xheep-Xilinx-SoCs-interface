# SPI Interrupt Configuration

## Hardware IRQ Assignment

The interrupts are concatenated in Vivado using an `xlconcat` IP before entering the PS interrupt controller:
- **In0**: UART interrupt
- **In1**: (reserved/other)
- **In2**: SPI interrupt

### IRQ Mapping

| Platform | UART IRQ (In0) | In1 IRQ | SPI IRQ (In2) | Notes |
|----------|----------------|---------|---------------|-------|
| **Zynq-7000** (PYNQ-Z2) | 30 | 31 | **32** | Base + 2 |
| **Zynq UltraScale+** (AUP-ZU3) | 90 | 91 | **92** | Base + 2 |

## Device Tree Configuration

### Zynq-7000 (dts/spi-zynq.tpl)

```dts
interrupt-parent = <&intc>;
interrupts = <0 32 1>;  // IRQ 32 (concat In2)
```

### Zynq UltraScale+ (dts/spi-ultrascale.tpl)

```dts
interrupt-parent = <&gic>;
interrupts = <0 92 4>;  // IRQ 92 (concat In2)
```

## Software Implementation

The IRQ ID is automatically selected based on the `BOARD` environment variable:

```python
board = os.getenv("BOARD", "pynq-z2").lower()
if board == "aup-zu3":
    spi_irq = 92  # UltraScale+: UART=90 (In0), SPI=92 (In2)
else:
    spi_irq = 32  # Zynq-7000: UART=30 (In0), SPI=32 (In2)

xheep.spi = xheepSPI(spi_addr, spi_irq)
```

## Vivado Hardware Concatenation

In the Vivado block design, the interrupt connections are:

```
UART IP → IRQ Out → Concat In0 ┐
    ???           → Concat In1  ├─→ PS pl_ps_irq0[2:0]
SPI IP  → IRQ Out → Concat In2 ┘
```

This means:
- UART (In0) uses the **base IRQ** assigned in PS (e.g., 90)
- In1 uses **base IRQ + 1** (e.g., 91)
- SPI (In2) uses **base IRQ + 2** (e.g., 92)

## Verification

After loading the overlay, you can verify the IRQ assignment:

```bash
# Check SPI device info
cat /sys/bus/platform/devices/a0030000.spi/uevent

# Check interrupt in device tree
cat /sys/bus/platform/devices/a0030000.spi/of_node/interrupts | od -An -tx1

# Check kernel messages for IRQ assignment
dmesg | grep -i "spi\|irq"
```

Expected output:
```
xilinx_spi a0030000.spi: at 0xA0030000 mapped to 0x... irq=31/91
```

## Troubleshooting

### Wrong IRQ causes timeout

**Symptom**: `/dev/spidevX.Y` exists but SPI communication times out

**Cause**: Incorrect IRQ assignment - driver waiting for interrupt that never arrives

**Solution**:
1. Verify Vivado IRQ concatenation order
2. Check `BOARD` environment variable is set correctly
3. Update IRQ values in code if your hardware differs

### Check current IRQ configuration

```bash
# Set board type
export BOARD=pynq-z2  # or aup-zu3

# Check what IRQ is used in the loaded DTS
cat dts/spi-patched.dts | grep interrupts
```

## Notes

- The IRQ type (last parameter in DTS) differs between platforms:
  - Zynq-7000: `<0 31 1>` (type 1 = edge-triggered)
  - UltraScale+: `<0 91 4>` (type 4 = level-high)

- If you modify the Vivado design IRQ order, update the IRQ values in:
  - [src/xheepDriver.py](src/xheepDriver.py) - xheepDriver.__init__()
  - [src/xheepRun.py](src/xheepRun.py) - _Stub.__init__()
  - [test_spi_flash.py](test_spi_flash.py) - XheepStub creation
