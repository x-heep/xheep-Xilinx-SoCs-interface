# Copyright 2019 Clifford Wolf
# Copyright 2019 Robert Balas
# Copyright 2022 Jose Miranda
# Copyright 2023 Juan Sapriza
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

# Author: Jose Miranda, Juan Sapriza (jose.mirandacalero / juan.sapriza @epfl.ch)

RISCV     ?= $(HOME)/.riscv
ARCH      ?= rv32imc_zicsr
ABI       ?= ilp32

ifneq ($(wildcard $(RISCV)/bin/riscv32-corev-elf-gcc),)
  RISCV_PREFIX  := riscv32-corev-elf
else
  RISCV_PREFIX  := riscv32-unknown-elf
endif

RISCV_GCC     := $(RISCV)/bin/$(RISCV_PREFIX)-gcc
RISCV_OBJCOPY := $(RISCV)/bin/$(RISCV_PREFIX)-objcopy

XHEEP_SW ?= $(CURDIR)

ifeq ($(wildcard $(XHEEP_SW)/device/lib/crt/crt0.S),)
$(error device library not found at '$(XHEEP_SW)/device')
endif

APP    ?= hello_world
# RISC-V toolchain — CORE-V GCC, the same toolchain used by x-heep.
# Installed by util/install_riscv_toolchain.sh to $HOME/.riscv.
# Override the path with:  make RISCV=/path/to/toolchain
LINKER ?= on_chip
TARGET ?= pynq-z2

TARGET_LC := $(shell echo $(TARGET) | tr '[:upper:]' '[:lower:]')
BUILD_DIR = build/$(APP)

ifeq ($(LINKER),flash_load)
  LINKER_SCRIPT = linker/link_flash_load.ld
else ifeq ($(LINKER),flash_exec)
  LINKER_SCRIPT = linker/link_flash_exec.ld
else
  LINKER_SCRIPT = linker/link.ld
endif

ifeq ($(LINKER),flash_exec)
  LINKER_DEF := -DFLASH_EXEC
else ifeq ($(LINKER),flash_load)
  LINKER_DEF := -DFLASH_LOAD
else
  LINKER_DEF := -DON_CHIP
endif

# Flags match x-heep's cmake build exactly:
#   -march=rv32imc_zicsr   (no xcv, no zifencei — matches the PYNQ-Z2 bitstream)
#   -DHOST_BUILD           (keeps memory.c from redefining memset/memcpy/etc.)
#   -DINTERNAL_CRTO        (use our own crt0.S instead of the toolchain's crt0)
CFLAGS = \
    -march=$(ARCH) -mabi=$(ABI) \
    -O2 -g -w \
    -nostartfiles \
    -ffunction-sections -fdata-sections \
    -DHOST_BUILD \
    $(LINKER_DEF) -DINTERNAL_CRTO

# nano.specs links against the reduced-footprint newlib (libc_nano).
# -L points to the toolchain's own lib directory so the correct libc_nano is
# found instead of a system default.
LDFLAGS = \
    -T $(LINKER_SCRIPT) \
    -static \
    -Wl,-Map=$(BUILD_DIR)/$(APP).map \
    -Wl,--gc-sections \
    -ffunction-sections -fdata-sections \
    -L $(RISCV)/riscv32-corev-elf/lib \
    -L $(RISCV)/riscv-corev-elf/lib \
    -specs=nano.specs

LDLIBS = -lc -lm -lgcc

INCLUDES = \
    -I$(XHEEP_SW)/device/target/$(TARGET_LC) \
    -I$(XHEEP_SW)/device/lib/runtime \
    -I$(XHEEP_SW)/device/lib/base \
    -I$(XHEEP_SW)/device/lib/base/freestanding \
    -I$(XHEEP_SW)/device/lib/drivers/soc_ctrl \
    -I$(XHEEP_SW)/device/lib/drivers/uart \
    -I$(XHEEP_SW)/device/lib/drivers/fast_intr_ctrl \
    -Iapplications/$(APP)

# Extra sources and includes needed only for flash_load (SPI flash boot):
# crt0.S calls w25q128jw_init_crt0 and w25q128jw_read_standard, which live
# in the SPI host driver and W25Q BSP.
ifeq ($(LINKER),flash_load)
FLASH_SRCS = \
    $(XHEEP_SW)/device/lib/drivers/spi_host/spi_host.c \
    $(XHEEP_SW)/device/bsp/w25q/w25q.c

FLASH_INCLUDES = \
    -I$(XHEEP_SW)/device/lib/drivers/spi_host \
    -I$(XHEEP_SW)/device/lib/drivers/rv_plic \
    -I$(XHEEP_SW)/device/lib/drivers/dma \
    -I$(XHEEP_SW)/device/bsp/w25q
else
FLASH_SRCS    =
FLASH_INCLUDES =
endif

CRT_SRCS = \
    $(XHEEP_SW)/device/lib/crt/crt0.S \
    $(XHEEP_SW)/device/lib/crt/vectors.S

RUNTIME_SRCS = \
    $(XHEEP_SW)/device/lib/runtime/syscalls.c \
    $(XHEEP_SW)/device/lib/runtime/core_v_mini_mcu.c \
    $(XHEEP_SW)/device/lib/runtime/handler.c \
    $(XHEEP_SW)/device/lib/runtime/init.c \
    $(XHEEP_SW)/device/lib/base/memory.c \
    $(XHEEP_SW)/device/lib/base/mmio.c

DRIVER_SRCS = \
    $(XHEEP_SW)/device/lib/drivers/uart/uart.c \
    $(XHEEP_SW)/device/lib/drivers/soc_ctrl/soc_ctrl.c \
    $(XHEEP_SW)/device/lib/drivers/fast_intr_ctrl/fast_intr_ctrl.c

APP_SRCS = applications/$(APP)/main.c

ALL_SRCS = $(CRT_SRCS) $(RUNTIME_SRCS) $(DRIVER_SRCS) $(FLASH_SRCS) $(APP_SRCS)

.PHONY: all clean

all: $(BUILD_DIR)/$(APP).bin
	@echo ""
	@echo "  ELF: $(BUILD_DIR)/$(APP).elf"
	@echo "  BIN: $(BUILD_DIR)/$(APP).bin"

$(BUILD_DIR)/$(APP).elf: $(ALL_SRCS) $(LINKER_SCRIPT)
	@mkdir -p $(BUILD_DIR)
	$(RISCV_GCC) $(CFLAGS) $(INCLUDES) $(FLASH_INCLUDES) $(LDFLAGS) -o $@ $(ALL_SRCS) $(LDLIBS)

$(BUILD_DIR)/$(APP).bin: $(BUILD_DIR)/$(APP).elf
	$(RISCV_OBJCOPY) -O binary $< $@

clean:
	rm -rf build
