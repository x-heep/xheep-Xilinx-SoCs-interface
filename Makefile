SHELL := /bin/bash
ROOT := $(shell pwd)
USER := xilinx
NOTEBOOK_DIR := /home/$(USER)/jupyter_notebooks/xheep

# Run parameters with defaults
LINKER  := on_chip
TARGET  := sw/build/$(APP)/$(APP).elf
OVERLAY := xilinx_core_v_mini_mcu_wrapper.bit

# App build parameters with defaults
APP       ?= hello_world
XHEEP_SW  ?= sw

.PHONY: help install install-notebook run app app-clean clean

# help target (documented in MakefileHelp script)
help:
	@FILE_FOR_HELP=Makefile util/MakefileHelp

## @section Setup & Installation

## Install all dependencies and configure the environment
## Requires sudo privileges to manage system packages and ConfigFS
install:
	@sudo -v || (echo "sudo is required. Run 'sudo -v' to cache credentials and retry." && exit 1)
	@sudo bash util/install_apt.sh
	@sudo bash util/install_git.sh
	@bash util/install_riscv_toolchain.sh
	@sudo bash -c "grep -qxF 'source /etc/profile.d/pynq_venv.sh' /root/.bashrc || echo 'source /etc/profile.d/pynq_venv.sh' >> /root/.bashrc"
	@sudo bash -c "grep -qxF 'cd /home/xilinx' /root/.bashrc || echo 'cd /home/xilinx' >> /root/.bashrc"

## Install notebook and dependencies to jupyter_notebooks directory
## @param USER=xilinx(default) Username for jupyter installation path
install-notebook:
	@bash util/install_python.sh
	@mkdir -p $(NOTEBOOK_DIR)/src
	@mkdir -p $(NOTEBOOK_DIR)/cfg
	@mkdir -p $(NOTEBOOK_DIR)/dts
	@cp notebook/xheepNotebook.ipynb $(NOTEBOOK_DIR)/
	@cp notebook/notebookUtils.py $(NOTEBOOK_DIR)/
	@cp src/xheepDriver.py $(NOTEBOOK_DIR)/src/
	@cp src/xheepRun.py $(NOTEBOOK_DIR)/src/
	@cp cfg/xheep_xilinx_xvc.cfg $(NOTEBOOK_DIR)/cfg/
	@cp dts/*.tpl $(NOTEBOOK_DIR)/dts/
	@echo "Notebook installed to $(NOTEBOOK_DIR)"

## @section Execution

## Run x-heep with specified firmware and overlay
## @param LINKER=on_chip Linker/execution mode: on_chip (JTAG), flash_load, or flash_exec
## @param TARGET=sw/build/APP/APP.elf Path to firmware .elf (xheepRun.py finds .bin for flash modes)
## @param OVERLAY=xilinx_core_v_mini_mcu_wrapper.bit Path to bitstream file
run:
	@python3 src/xheepRun.py -o $(OVERLAY) -f $(TARGET) -m $(LINKER)

## @section Application Build

## Compile a RISC-V application for x-heep (produces .elf and .bin)
## @param APP=hello_world Application name (folder under sw/applications/)
## @param LINKER=on_chip Linker/execution mode: on_chip, flash_load, flash_exec
## @param XHEEP_SW=sw Device library root (default: bundled sw/device/)
app:
	@$(MAKE) -C sw APP=$(APP) LINKER=$(LINKER) XHEEP_SW=$(ROOT)/$(XHEEP_SW)
	@echo "Firmware ready: sw/build/$(APP)/$(APP).elf  sw/build/$(APP)/$(APP).bin"

## Clean application build artefacts
app-clean:
	@$(MAKE) -C sw clean

## @section Cleanup

## Clean all build artifacts
clean: app-clean
	@echo "Clean complete"
