SHELL := /bin/bash
ROOT := $(shell pwd)
NOTEBOOK_DIR := /home/$(USER)/jupyter_notebooks/xheep

.PHONY: help install install-notebook clean

help:
	@FILE_FOR_HELP=Makefile util/MakefileHelp

## Install all dependencies and configure the environment
install:
	@sudo -v || (echo "sudo is required. Run 'sudo -v' to cache credentials and retry." && exit 1)
	@sudo bash util/install_apt.sh
	@sudo bash util/install_git.sh
	@bash util/install_python.sh
	@sudo bash -c "grep -qxF 'source /etc/profile.d/pynq_venv.sh' /root/.bashrc || echo 'source /etc/profile.d/pynq_venv.sh' >> /root/.bashrc"
	@sudo bash -c "grep -qxF 'cd /home/xilinx' /root/.bashrc || echo 'cd /home/xilinx' >> /root/.bashrc"

## Install notebook and dependencies to jupyter_notebooks
install-notebook: install
	@mkdir -p $(NOTEBOOK_DIR)/src
	@mkdir -p $(NOTEBOOK_DIR)/cfg
	@mkdir -p $(NOTEBOOK_DIR)/dts
	@cp notebooks/xheep_interface.ipynb $(NOTEBOOK_DIR)/
	@cp src/xheepDriver.py $(NOTEBOOK_DIR)/src/
	@cp src/xheepRun.py $(NOTEBOOK_DIR)/src/
	@cp cfg/xheep_xilinx_xvc.cfg $(NOTEBOOK_DIR)/cfg/
	@cp dts/*.tpl $(NOTEBOOK_DIR)/dts/

clean:
	@echo "Nothing to clean yet"