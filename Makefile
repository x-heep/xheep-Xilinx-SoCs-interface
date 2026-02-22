SHELL := /bin/bash
ROOT := $(shell pwd)
USER := xilinx
NOTEBOOK_DIR := /home/$(USER)/jupyter_notebooks/xheep

# Run / build parameters — all overridable on the command line
LINKER    ?= on_chip
BOARD     ?= pynq-z2
APP       ?= hello_world
OVERLAY   ?= xilinx_core_v_mini_mcu_wrapper.bit
FLAVOR    ?= base

# Derived path to firmware (used by 'make run')
TARGET  := sw/build/$(APP)/$(APP).elf

.PHONY: help install install-notebook uninstall uninstall-notebook run app app-clean clean

# help target (documented in MakefileHelp script)
help:
	@FILE_FOR_HELP=Makefile util/MakefileHelp

## @section Setup & Installation

## Install dependencies, the selected toolchain flavor(s), and sync sw/device from x-heep
## Requires sudo privileges to manage system packages and ConfigFS
## @param FLAVOR=base         Toolchain flavor(s) to install: base, float, zfinx, all
## @param XHEEP_REPO=...      x-heep git URL (default: https://github.com/x-heep/x-heep)
install:
	@sudo -v || (echo "sudo is required. Run 'sudo -v' to cache credentials and retry." && exit 1)
	@sudo bash util/install_apt.sh
	@sudo bash util/install_git.sh
	@bash util/install_riscv_toolchain.sh $(FLAVOR)
	@bash util/install_xheep_sw.sh $(if $(XHEEP_REPO),$(XHEEP_REPO),)
	@sudo bash -c "grep -qxF 'source /etc/profile.d/pynq_venv.sh' /root/.bashrc || echo 'source /etc/profile.d/pynq_venv.sh' >> /root/.bashrc"
	@sudo bash -c "grep -qxF 'cd /home/xilinx' /root/.bashrc || echo 'cd /home/xilinx' >> /root/.bashrc"

## Uninstall toolchain and remove PATH entries from shell profiles
uninstall:
	@sudo -v || (echo "sudo is required. Run 'sudo -v' to cache credentials and retry." && exit 1)
	@bash util/uninstall_riscv_toolchain.sh

## Uninstall notebook files from jupyter_notebooks directory
## @param USER=xilinx(default) Username for jupyter installation path
uninstall-notebook:
	@rm -rf $(NOTEBOOK_DIR)
	@echo "Notebook uninstalled from $(NOTEBOOK_DIR)"

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

## Run firmware on x-heep via JTAG (or flash for flash_load/flash_exec)
## @param APP=hello_world     Application to run (must be built first)
## @param LINKER=on_chip      Execution mode: on_chip, flash_load, flash_exec
## @param OVERLAY=...bit      Path to FPGA bitstream
run:
	@python3 src/xheepRun.py -o $(OVERLAY) -f $(TARGET) -m $(LINKER)

## @section Application Build

## Compile a RISC-V application using the installed CoreV RISC-V toolchain
## Produces sw/build/APP/APP.{elf,bin}
## Always removes any previous build of the same APP before recompiling.
## @param APP=hello_world     Application folder under sw/applications/
## @param LINKER=on_chip      Linker mode: on_chip, flash_load, flash_exec
## @param BOARD=pynq-z2       Target board: pynq-z2, aup-zu3
## @param FLAVOR=base         Toolchain flavor: base (rv32imc), float (rv32imfc), zfinx (rv32imc_zfinx)
app:
	@rm -rf sw/build/$(APP)
	@$(MAKE) -C sw APP=$(APP) LINKER=$(LINKER) TARGET=$(BOARD) FLAVOR=$(FLAVOR)

## Clean application build artefacts
app-clean:
	@$(MAKE) -C sw clean

## @section Cleanup

## Clean all build artifacts
clean: app-clean
	@echo "Clean complete"
