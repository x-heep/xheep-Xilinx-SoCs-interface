# Toolchain flavor — selects compiler prefix, march and mabi automatically.
# Allowed values: base (default), float, zfinx
FLAVOR ?= base

_XCV = _xcvmem_xcvmac_xcvbi_xcvalu_xcvsimd_xcvbitmanip

ifeq ($(FLAVOR),float)
  _RISCV_DIR = /opt/openhw-riscv-float
  _ARCH      = rv32imfc_zicsr_zifencei$(_XCV)
  _ABI       = ilp32f
else ifeq ($(FLAVOR),zfinx)
  _RISCV_DIR = /opt/openhw-riscv-zfinx
  _ARCH      = rv32imc_zicsr_zifencei_zfinx$(_XCV)
  _ABI       = ilp32
else
  _RISCV_DIR = /opt/openhw-riscv-base
  _ARCH      = rv32imc_zicsr_zifencei$(_XCV)
  _ABI       = ilp32
endif

RISCV     ?= $(_RISCV_DIR)
ARCH      ?= $(_ARCH)
ABI       ?= $(_ABI)

RISCV_GCC     := $(RISCV)/bin/riscv32-unknown-elf-gcc
RISCV_OBJCOPY := $(RISCV)/bin/riscv32-unknown-elf-objcopy

XHEEP_SW ?= $(CURDIR)

ifeq ($(wildcard $(XHEEP_SW)/device/lib/crt/crt0.S),)
$(error device library not found at '$(XHEEP_SW)/device')
endif

APP    ?= hello_world
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

CFLAGS = \
    -march=$(ARCH) -mabi=$(ABI) \
    -O2 -g -w \
    -nostartfiles \
    -ffunction-sections -fdata-sections \
    -DHOST_BUILD $(LINKER_DEF) -DINTERNAL_CRTO

# nano.specs links against the reduced-footprint newlib (libc_nano), which has
# significantly smaller BSS than the standard newlib used by nosys.specs.
# This keeps data sections within the ram1 budget.
LDFLAGS = \
    -T $(LINKER_SCRIPT) \
    -static \
    -Wl,-Map=$(BUILD_DIR)/$(APP).map \
    -Wl,--gc-sections \
    -ffunction-sections -fdata-sections \
    -specs=nano.specs

LDLIBS = -lc -lgcc

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
