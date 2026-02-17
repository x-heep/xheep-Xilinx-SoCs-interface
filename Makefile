SHELL := /bin/bash
ROOT := $(shell pwd)
USER := xilinx
NOTEBOOK_DIR := /home/$(USER)/jupyter_notebooks/xheep

.PHONY: help install install-notebook clean

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

## @section Cleanup

## Clean build artifacts (none currently)
clean:
	@echo "Nothing to clean yet"
