# sw/Makefile — RISC-V bare-metal application build for x-heep on PYNQ-Z2
#
# Compiles hello_world for the x-heep (CV32E40P) RISC-V 32-bit processor
# using the PULP RISC-V toolchain (riscv32-unknown-elf-gcc at /opt/pulp-riscv).
# Produces both .elf and .bin under sw/build/hello_world/.
#
# Usage:
#   make                      # build hello_world (on_chip mode)
#   make LINKER=flash_load    # build for flash-load mode
#
# Supported LINKER modes : on_chip (default), flash_load, flash_exec

# ── Toolchain ─────────────────────────────────────────────────────────────────
# PULP RISC-V toolchain installed by 'make install' at /opt/pulp-riscv.
# Override RISCV to point at a different installation if needed.
RISCV         ?= /opt/pulp-riscv
RISCV_GCC     ?= $(RISCV)/bin/riscv32-unknown-elf-gcc
RISCV_OBJCOPY ?= $(RISCV)/bin/riscv32-unknown-elf-objcopy
ARCH          ?= rv32imc
ABI           ?= ilp32

# ── Paths ─────────────────────────────────────────────────────────────────────
# Device library root — defaults to the bundled sw/device/ in this repo.
# Override with the x-heep sw/ path if you have a full clone available:
#   make app XHEEP_SW=/path/to/x-heep/sw
XHEEP_SW ?= $(CURDIR)

# ── Validate XHEEP_SW ─────────────────────────────────────────────────────────
ifeq ($(wildcard $(XHEEP_SW)/device/lib/crt/crt0.S),)
$(error device library not found at '$(XHEEP_SW)/device'. \
  The bundled sw/device/ may be missing — check your checkout.)
endif

# ── Build parameters ──────────────────────────────────────────────────────────
# Only hello_world on pynq-z2 is supported for now.
APP    := hello_world
LINKER ?= on_chip
TARGET := pynq-z2

BUILD_DIR = build/$(APP)

# ── Linker script selection ───────────────────────────────────────────────────
ifeq ($(LINKER),flash_load)
  LINKER_SCRIPT = linker/link_flash_load.ld
else ifeq ($(LINKER),flash_exec)
  LINKER_SCRIPT = linker/link_flash_exec.ld
else
  LINKER_SCRIPT = linker/link.ld
endif

# ── Linker-mode preprocessor define ──────────────────────────────────────────
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

# ── Compiler flags ────────────────────────────────────────────────────────────
CFLAGS = \
	-march=$(ARCH) -mabi=$(ABI) \
	-O2 -g -w \
	-nostartfiles \
	-ffunction-sections -fdata-sections \
	-DHOST_BUILD $(LINKER_DEF) -DINTERNAL_CRTO

# ── Linker flags ──────────────────────────────────────────────────────────────
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

# ── Include paths ─────────────────────────────────────────────────────────────
INCLUDES = \
	-I$(XHEEP_SW)/device/target/$(TARGET) \
	-I$(XHEEP_SW)/device/lib/runtime \
	-I$(XHEEP_SW)/device/lib/base \
	-I$(XHEEP_SW)/device/lib/base/freestanding \
	-I$(XHEEP_SW)/device/lib/drivers/soc_ctrl \
	-I$(XHEEP_SW)/device/lib/drivers/uart \
	-I$(XHEEP_SW)/device/lib/drivers/fast_intr_ctrl \
	-Iapplications/$(APP)

# ── Source files ──────────────────────────────────────────────────────────────
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

# ── Targets ───────────────────────────────────────────────────────────────────
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
