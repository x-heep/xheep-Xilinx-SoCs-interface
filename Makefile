SHELL := /bin/bash
ROOT := $(shell pwd)
USER := xilinx
NOTEBOOK_DIR := /home/$(USER)/jupyter_notebooks/xheep

# Run parameters
LINKER  := on_chip
OVERLAY := xilinx_core_v_mini_mcu_wrapper.bit

# Application — only hello_world on pynq-z2 is supported for now
APP    := hello_world
TARGET := sw/build/$(APP)/$(APP).elf

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

## Load hello_world onto PYNQ-Z2 via JTAG and run it
## @param OVERLAY=xilinx_core_v_mini_mcu_wrapper.bit Path to bitstream file
run:
	@python3 src/xheepRun.py -o $(OVERLAY) -f $(TARGET) -m $(LINKER)

## @section Application Build

## Compile hello_world for PYNQ-Z2 using the installed PULP RISC-V toolchain
## Produces sw/build/hello_world/hello_world.{elf,bin}
app:
	@$(MAKE) -C sw LINKER=$(LINKER)
	@echo "Firmware ready: $(TARGET)"

## Clean application build artefacts
app-clean:
	@$(MAKE) -C sw clean

## @section Cleanup

## Clean all build artifacts
clean: app-clean
	@echo "Clean complete"
