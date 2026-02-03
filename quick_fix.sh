#!/bin/bash
# Quick fix for SPI IRQ issue

echo "=== Quick SPI Fix ==="

# 1. Set BOARD environment
export BOARD=aup-zu3
echo "[1/5] Set BOARD=$BOARD"

# 2. Remove old patched DTS
rm -f dts/spi-patched.dts dts/spi-overlay.dtbo
echo "[2/5] Removed old DTS files"

# 3. Remove overlay
rmdir /sys/kernel/config/device-tree/overlays/axiquadspi 2>/dev/null
echo "[3/5] Removed overlay"

# 4. Clear Python cache
find . -name "*.pyc" -delete 2>/dev/null
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
echo "[4/5] Cleared Python cache"

# 5. Export environment
echo "export BOARD=aup-zu3" > /tmp/board_env.sh
echo "[5/5] Created /tmp/board_env.sh"

echo ""
echo "=== Now run: ==="
echo "source /tmp/board_env.sh"
echo "python test.py --o xilinx_core_v_mini_mcu_wrapper.bit"
