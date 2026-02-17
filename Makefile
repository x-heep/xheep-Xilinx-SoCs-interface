SHELL := /bin/bash
ROOT := $(shell pwd)
USER := xilinx
NOTEBOOK_DIR := /home/$(USER)/jupyter_notebooks/xheep

# Run parameters with defaults
LINKER := on_chip
TARGET := main.bin
OVERLAY := xilinx_core_v_mini_mcu_wrapper.bit

.PHONY: help install install-notebook run clean

## Get help for commands in this folder
help:
	@FILE_FOR_HELP=Makefile util/MakefileHelp

## @section Setup & Installation

## Install all dependencies and configure the environment
## Requires sudo privileges to manage system packages and ConfigFS
install:
	@sudo -v || (echo "sudo is required. Run 'sudo -v' to cache credentials and retry." && exit 1)
	@sudo bash util/install_apt.sh
	@sudo bash util/install_git.sh
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
## @param TARGET=main.bin Path to firmware file (.elf or .bin)
## @param OVERLAY=xilinx_core_v_mini_mcu_wrapper.bit Path to bitstream file
run:
	@python3 src/xheepRun.py --overlay $(OVERLAY) --firmware $(TARGET) --memory $(LINKER)

## @section Cleanup

## Clean build artifacts (none currently)
clean:
	@echo "Nothing to clean yet"
