# sw/Makefile — RISC-V bare-metal application build for x-heep
#
# Compiles a bare-metal application for the x-heep (CV32E40P) RISC-V 32-bit
# processor using the PULP RISC-V toolchain (riscv32-unknown-elf-gcc).
#
# Usage (from this directory):
#   make                               # hello_world, on_chip, pynq-z2
#   make LINKER=flash_load             # flash-load mode
#   make LINKER=flash_exec             # flash-exec mode
#   make TARGET=aup-zu3                # different board
#   make APP=hello_world               # explicit app (only one supported now)
#
# Supported LINKER modes : on_chip (default), flash_load, flash_exec
# Supported TARGET boards : pynq-z2 (default), aup-zu3

# PULP RISC-V toolchain installed by 'make install' at /opt/pulp-riscv.
# Override RISCV to point at a different installation if needed.
RISCV         ?= /opt/pulp-riscv
RISCV_GCC     ?= $(RISCV)/bin/riscv32-unknown-elf-gcc
RISCV_OBJCOPY ?= $(RISCV)/bin/riscv32-unknown-elf-objcopy
ARCH          ?= rv32imc
ABI           ?= ilp32

# Device library root — defaults to the bundled sw/device/ in this repo.
# Override with the x-heep sw/ path if you have a full clone available:
#   make app XHEEP_SW=/path/to/x-heep/sw
XHEEP_SW ?= $(CURDIR)

ifeq ($(wildcard $(XHEEP_SW)/device/lib/crt/crt0.S),)
$(error device library not found at '$(XHEEP_SW)/device'. \
  The bundled sw/device/ may be missing — check your checkout.)
endif

APP    ?= hello_world
LINKER ?= on_chip
TARGET ?= pynq-z2

BUILD_DIR = build/$(APP)

ifeq ($(LINKER),flash_load)
  LINKER_SCRIPT = linker/link_flash_load.ld
else ifeq ($(LINKER),flash_exec)
  LINKER_SCRIPT = linker/link_flash_exec.ld
else
  LINKER_SCRIPT = linker/link.ld
endif

# crt0.S gates the flash→RAM .data copy and the flash-load bootstrap behind
# #ifdef FLASH_EXEC / #ifdef FLASH_LOAD.  The define MUST match the linker
# script, otherwise global initialised data is never copied and the firmware
# crashes on first access to any global variable.
ifeq ($(LINKER),flash_exec)
  LINKER_DEF := -DFLASH_EXEC
else ifeq ($(LINKER),flash_load)
  LINKER_DEF := -DFLASH_LOAD
else
  LINKER_DEF := -DON_CHIP
endif

CFLAGS = \
	-march=$(ARCH) -mabi=$(ABI) \
	-O2 -g -w \
	-nostartfiles \
	-ffunction-sections -fdata-sections \
	-DHOST_BUILD $(LINKER_DEF) -DINTERNAL_CRTO

# LDLIBS is intentionally kept separate and appended AFTER $(ALL_SRCS) in the
# link rule so that our compiled objects (which define stdout, _sbrk, etc.)
# are visible to the linker before it searches the C library archives.
LDFLAGS = \
	-T $(LINKER_SCRIPT) \
	-static \
	-Wl,-Map=$(BUILD_DIR)/$(APP).map \
	-Wl,--gc-sections \
	-ffunction-sections -fdata-sections \
	-specs=nosys.specs

LDLIBS = -lc -lgcc

INCLUDES = \
	-I$(XHEEP_SW)/device/target/$(TARGET) \
	-I$(XHEEP_SW)/device/lib/runtime \
	-I$(XHEEP_SW)/device/lib/base \
	-I$(XHEEP_SW)/device/lib/base/freestanding \
	-I$(XHEEP_SW)/device/lib/drivers/soc_ctrl \
	-I$(XHEEP_SW)/device/lib/drivers/uart \
	-I$(XHEEP_SW)/device/lib/drivers/fast_intr_ctrl \
	-I$(XHEEP_SW)/device/lib/drivers/$(TARGET) \
	-Iapplications/$(APP)

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

ALL_SRCS = $(CRT_SRCS) $(RUNTIME_SRCS) $(DRIVER_SRCS) $(APP_SRCS)

.PHONY: all clean

all: $(BUILD_DIR)/$(APP).bin
	@echo ""
	@echo "  ELF: $(BUILD_DIR)/$(APP).elf"
	@echo "  BIN: $(BUILD_DIR)/$(APP).bin"

$(BUILD_DIR)/$(APP).elf: $(ALL_SRCS) $(LINKER_SCRIPT)
	@mkdir -p $(BUILD_DIR)
	$(RISCV_GCC) $(CFLAGS) $(INCLUDES) $(LDFLAGS) -o $@ $(ALL_SRCS) $(LDLIBS)

$(BUILD_DIR)/$(APP).bin: $(BUILD_DIR)/$(APP).elf
	$(RISCV_OBJCOPY) -O binary $< $@

clean:
	rm -rf build
