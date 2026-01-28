SHELL := /bin/bash
ROOT := $(shell pwd)

.PHONY: help install install_apt install_git install_python clean

help:
	@FILE_FOR_HELP=Makefile util/MakefileHelp

## Install all dependencies and configure the environment
install:
	@sudo -v || (echo "sudo is required. Run 'sudo -v' to cache credentials and retry." && exit 1)
	@sudo bash util/install_apt.sh
	@sudo bash util/install_git.sh
	@sudo bash -c "grep -qxF 'source /etc/profile.d/pynq_venv.sh' /root/.bashrc || echo 'source /etc/profile.d/pynq_venv.sh' >> /root/.bashrc"
	@sudo bash -c "grep -qxF 'cd /home/xilinx' /root/.bashrc || echo 'cd /home/xilinx' >> /root/.bashrc"

clean:
	@if [ -d openocd ]; then \
		$(MAKE) -C openocd clean-recursive || true; \
	fi