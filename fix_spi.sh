#!/bin/bash
# Fix SPI communication by setting correct environment and clearing cache

echo "=== Fixing SPI Setup ==="

# Step 1: Clear Python cache
echo "[1/4] Clearing Python cache..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null

# Step 2: Remove old overlay
echo "[2/4] Removing old SPI overlay..."
if [ -d "/sys/kernel/config/device-tree/overlays/axiquadspi" ]; then
    rmdir /sys/kernel/config/device-tree/overlays/axiquadspi 2>/dev/null || echo "  (overlay removal failed, may need manual cleanup)"
fi

# Step 3: Detect board type
echo "[3/4] Detecting board type..."
if grep -q "ZynqMP" /proc/device-tree/compatible 2>/dev/null; then
    export BOARD=aup-zu3
    echo "  Detected: Zynq UltraScale+ (ZynqMP)"
    echo "  Setting: BOARD=aup-zu3"
    echo "  Expected IRQ: 92 (UART=90 at In0, SPI=92 at In2)"
else
    export BOARD=pynq-z2
    echo "  Detected: Zynq-7000"
    echo "  Setting: BOARD=pynq-z2"
    echo "  Expected IRQ: 32 (UART=30 at In0, SPI=32 at In2)"
fi

# Step 4: Export for use
echo "[4/4] Exporting BOARD environment variable..."
echo "export BOARD=$BOARD" > /tmp/board_env.sh

echo ""
echo "=== Setup Complete ==="
echo "Run the following command to set environment:"
echo "  source /tmp/board_env.sh"
echo ""
echo "Then run your test again:"
echo "  python test.py --o xilinx_core_v_mini_mcu_wrapper.bit"
