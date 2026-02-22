# x-heep Xilinx SoCs Interface

This repository provides the software interface and drivers to integrate the [x-heep](https://github.com/x-heep/x-heep) RISC-V core with the Processing System (PS) of Xilinx SoCs.
This framework enables remote connectivity to the boards via SSH to deploy, test, and debug x-heep without physical access to the JTAG or UART headers.

The on-board Processing System enables a full "remote-lab" experience for RISC-V development.
The project acts as a bridge between the Xilinx ARM-based Processing System and the FPGA Programmable Logic (PL) where x-heep resides. It automates the complex process of synchronizing the Linux hardware description (Device Tree) with the live state of the FPGA.

### Key Features

* **Remote Deployment via SSH:** Manage the entire development cycle (programming, execution, and monitoring) over a network connection.
* **Remote Bitstream Loading:** Deploy x-heep hardware designs directly from Python using PYNQ-based drivers.
* **OpenOCD & XVC Integration:** Leverages OpenOCD 0.12.0 and the Xilinx Virtual Cable (XVC) protocol to load `.elf` firmware over AXI JTAG.
* **Dynamic UART Overlay:** Automatically patches, compiles, and loads a Linux Device Tree Overlay (DTO) to expose the AXI UART as a system device.
* **Dynamic SPI Overlay:** Automatically manages the AXI Quad SPI device tree overlay to expose the SPI bus for flash programming.
* **Direct Flash Programming:** Programs external SPI NOR flash via direct MMIO access, without requiring kernel SPI drivers.
* **Execution Control:** Full remote control over the core lifecycle, including reset, boot mode selection, and exit status monitoring via GPIO.
* **Bitstream Change Detection:** SHA256-based tracking avoids unnecessary PL resets when the same bitstream is reused.

---

## Supported Platforms

| Board    | SoC                | Status    | Notes                                                      |
| -------- | ------------------ | --------- | ---------------------------------------------------------- |
| PYNQ-Z2  | Zynq-7000 (XC7Z020)| Supported | Requires `PS_ENABLE` to be active in the x-heep bitstream. |
| AUP-ZU3  | ZynqMP (XCZU3EG)   | Supported | Requires `PS_ENABLE` to be active in the x-heep bitstream. |

> **Important:** Ensure that the Vivado version used to implement x-heep is consistent with the Linux distribution installed on the board. Mismatched versions may cause issues with JTAG TAP identification and bitstream loading.

---

## Installation

The installation process is fully automated through a single command.
This script installs system dependencies, builds OpenOCD with specific patches, and configures the Python environment.

```bash
make install                  # Install the default toolchain flavor (base — rv32imc, no FPU)
make install FLAVOR=float     # Install the hardware FPU flavor (rv32imfc)
make install FLAVOR=zfinx     # Install the Zfinx flavor (rv32imc_zfinx)
make install FLAVOR=all       # Install all three flavors at once
```

Only the selected flavor is downloaded and installed. Use `FLAVOR=all` to install all three in one shot.

> Note: This requires `sudo` privileges to manage system packages, install OpenOCD, and manipulate the kernel's ConfigFS.

### OpenOCD Build and Patch

During installation, the script automatically:

1. **Clones OpenOCD** from the official repository at version v0.12.0
2. **Applies a custom patch** (`patch/openocd.patch`) required for correct operation with the x-heep RISC-V core:
   - Disables `vlenb` register probing unless the vector extension (V) is present in MISA
   - Disables `MTOPI`/`MTOPEI` privileged interrupt register probing
   - Replaces hard assertions with warnings for graceful degradation
3. **Builds OpenOCD** with the following features enabled:
   - FTDI interface support (`--enable-ftdi`)
   - Bitbang driver support (`--enable-bitbang`)
   - Xilinx AXI XVC support (`--enable-xlnx-axi-xvc`)
   - Internal JimTcl interpreter (`--enable-internal-jimtcl`)
4. **Installs OpenOCD** system-wide at `/usr/local/bin/openocd`

### Notebook Installation

To install the Jupyter notebook interface to the board's default notebook directory:

```bash
make install-notebook
```

This copies all necessary files (notebook, drivers, config, DTS templates) to `~/jupyter_notebooks/xheep`. The target user can be customized with `USER=<username>`.

---

## Dependencies

### System Packages
- `device-tree-compiler` — compiles `.dts` templates into `.dtbo` binaries
- `picocom` — serial terminal for UART monitoring
- `jdupes` — hardlink deduplication across toolchain flavors to reduce disk usage

### RISC-V CoreV Toolchain
`make install` automatically downloads and installs the **CoreV RISC-V toolchain** from the
[riscv-Xilinx-SoCs-toolchain](https://github.com/Christian-Conti/riscv-Xilinx-SoCs-toolchain)
GitHub releases. Only the flavor selected by `FLAVOR` is installed under `/opt/`:

| `FLAVOR` | Symlink | `-march` | `-mabi` | Use case |
|---|---|---|---|---|
| `base` (default) | `/opt/openhw-riscv-base` | `rv32imc` | `ilp32` | No FPU |
| `float` | `/opt/openhw-riscv-float` | `rv32imfc` | `ilp32f` | Hardware FPU |
| `zfinx` | `/opt/openhw-riscv-zfinx` | `rv32imc_zfinx` | `ilp32` | Zfinx (float in integer regs) |

Use `make install FLAVOR=<flavor>` to install a single flavor, or `make install FLAVOR=all` to install all three at once. If multiple flavors are present, `jdupes` automatically deduplicates shared files using hardlinks to minimize disk usage.

The active flavor is selected at build time via the same `FLAVOR` variable (see [Building Applications](#building-applications)).

### Python Packages
- `pynq` — FPGA bitstream management and MMIO access
- `pyserial` — UART serial communication
- `ipywidgets` — interactive widgets for the Jupyter notebook

### External Tools
- OpenOCD v0.12.0 (built and patched during `make install`)
- Vivado-generated `.bit` bitstream with the x-heep design and PS\_ENABLE active

---

## Execution Flow

The `xheepRun.py` script follows a strict sequence to ensure hardware stability and kernel synchronization. It supports three execution modes controlled via the `--memory` flag:

### On-Chip Memory Mode (JTAG) — Default
The fastest execution mode, suitable for small programs that fit in internal RAM.

1. **UART Cleanup:** Before any hardware changes, the script checks if the AXI UART is active. It performs a driver unbind and removes the existing overlay to prevent kernel hangs during PL reset.
2. **PL Reset & Programming:** The Programmable Logic is reset and the new bitstream is loaded via the PYNQ Overlay manager.
3. **Dynamic Overlay Injection:** The driver retrieves the AXI UART physical address from the bitstream, patches the `uartlite-overlay.tpl` file, compiles it into a `.dtbo`, and injects it into the live kernel via ConfigFS. This re-attaches the UART, creating `/dev/ttyUL0`.
4. **User Confirmation:** The system halts and waits for the user to press Enter.
5. **JTAG Firmware Load:** OpenOCD starts an XVC server using the AXI JTAG base address. The script connects via Telnet to halt the core and load the `.elf` firmware into memory.
6. **Monitoring:** Once execution begins, the script monitors GPIO signals. Upon completion, it displays the Exit Valid and Exit Value codes.

### Flash Load Mode
Program the external flash memory and load/execute via JTAG. Useful for larger programs.

1. Steps 1–4 same as above.
2. **Flash Programming:** The firmware binary is programmed into external SPI NOR flash using direct MMIO (without requiring kernel SPI drivers).
3. **Flash Boot Configuration:** GPIO is configured to boot from flash.
4. **JTAG Loading:** Firmware is loaded and executed the same as on-chip mode.

### Flash Execute Mode
Boot and execute directly from flash without JTAG loading. Most persistent mode.

1. Steps 1–3 same as above.
2. **Flash Boot Configuration:** GPIO is configured to execute directly from flash.
3. **Direct Execution:** X-HEEP boots from flash and executes immediately without JTAG intervention.
4. **Monitoring:** Script monitors exit codes via GPIO.

---

## Hardware Configuration & JTAG

### OpenOCD XVC Configuration

The repository uses a specific OpenOCD configuration (`cfg/xheep_xilinx_xvc.cfg`) to enable the Xilinx Virtual Cable. This configuration allows OpenOCD to communicate with the `axi_jtag` IP inside the FPGA by mapping JTAG operations to memory-mapped I/O (MMIO) registers at the address specified by `XVC_DEV_ADDR`.

The configuration exposes the following network ports:
- **4444** — Telnet command interface
- **3333** — GDB remote debugging
- **6666** — TCL RPC interface

### GPIO Mapping

The `xheepGPIO` class manages the following control signals via the `axi_gpio` IP:

| Bit / Channel | Signal                  | Description                                           |
| ------------- | ----------------------- | ----------------------------------------------------- |
| Bit 0         | `rst_ni`                | Active-low reset for the x-heep core                 |
| Bit 1         | `boot_select_i`         | Selects JTAG (0) or Flash (1) boot mode               |
| Bit 2         | `execute_from_flash_i`  | Enables direct execution from Flash memory            |
| Bit 3         | `jtag_trst_ni`          | Active-low reset for the JTAG TAP controller          |
| Bit 4         | `spi_sel`               | Selects SPI flash access: PS (0) or X-HEEP (1)        |
| Channel 2     | Exit Status             | Reads `exit_valid` and `exit_value` after execution   |

---

## Usage

### Makefile

```bash
make install                  # Install dependencies + base toolchain flavor (rv32imc)
make install FLAVOR=float     # Install dependencies + float toolchain flavor (rv32imfc)
make install FLAVOR=zfinx     # Install dependencies + zfinx toolchain flavor
make install FLAVOR=all       # Install dependencies + all three toolchain flavors
make uninstall                # Remove all installed toolchain flavors and clean PATH entries (requires sudo)
make install-notebook      # Install Jupyter notebook interface to ~/jupyter_notebooks/xheep
make uninstall-notebook    # Remove the Jupyter notebook interface
make app                   # Compile hello_world (rv32imc, no FPU)
make app APP=my_app        # Compile a custom application
make app APP=my_app LINKER=flash_load            # Compile for flash boot
make app APP=my_app FLAVOR=float                 # Compile with hardware FPU (rv32imfc)
make app APP=my_app FLAVOR=zfinx                 # Compile with Zfinx (rv32imc_zfinx)
make run                   # Run with default parameters
make run LINKER=flash_load OVERLAY=xilinx_core_v_mini_mcu_wrapper.bit
make help                  # Show all available targets and parameters
```

**Makefile parameters:**

| Variable    | Default                                   | Description                                                      |
| ----------- | ----------------------------------------- | ---------------------------------------------------------------- |
| `OVERLAY`   | `xilinx_core_v_mini_mcu_wrapper.bit`      | Path to the FPGA bitstream                                       |
| `LINKER`    | `on_chip`                                 | Execution mode: `on_chip`, `flash_load`, `flash_exec`            |
| `USER`      | `xilinx`                                  | Username for notebook installation path                          |
| `APP`       | `hello_world`                             | Application name (folder under `sw/applications/`)               |
| `BOARD`     | `pynq-z2`                                 | Target board: `pynq-z2`, `aup-zu3`                               |
| `FLAVOR`    | `base`                                    | Toolchain flavor: `base`, `float`, `zfinx` (or `all` for `make install`) |

### Building Applications

Applications live under `sw/applications/<app_name>/main.c`.
The build system uses `riscv32-unknown-elf-gcc` (CoreV toolchain) to compile for the CV32E40P core and produces both a `.elf` and a flat `.bin` image in `sw/build/<app_name>/`.

```bash
# Build hello_world (on-chip execution, PYNQ-Z2 clock/UART settings, no FPU)
# No external dependencies needed — device library is bundled in sw/device/
make app

# Build a custom application
make app APP=my_app

# Build for flash boot
make app APP=my_app LINKER=flash_load

# Build with hardware FPU support (requires xheep-float toolchain)
make app APP=my_app FLAVOR=float

# Build with Zfinx (float in integer registers)
make app APP=my_app FLAVOR=zfinx

# Run immediately after build
make app APP=my_app && make run LINKER=on_chip
```

#### Creating a new application

1. Create a directory `sw/applications/<app_name>/`
2. Add a `main.c` file (standard C, bare-metal)
3. Run `make app APP=<app_name>`

The runtime provides `printf` output over the AXI UART (accessible via `/dev/ttyUL0` after `make run`).

#### Supported target boards

The `BOARD` variable selects the board-specific `x-heep.h` header (clock frequency, UART baud rate, etc.):

| `BOARD` value | Board           | Clock  |
| ------------- | --------------- | ------ |
| `pynq-z2`     | PYNQ-Z2         | 15 MHz |
| `aup-zu3`     | AUP-ZU3         | 50 MHz |

Pass `BOARD=<value>` to `make app` to select a different board (default: `pynq-z2`).

#### Toolchain

The `sw/Makefile` uses `riscv32-unknown-elf-gcc` from the CoreV toolchain installed by `make install`.
The active toolchain is selected by the `FLAVOR` flag, which automatically sets `-march`, `-mabi`, and `RISCV` path:

| `FLAVOR` | Toolchain path | `-march` | `-mabi` |
|---|---|---|---|
| `base` (default) | `/opt/openhw-riscv-base` | `rv32imc` | `ilp32` |
| `float` | `/opt/openhw-riscv-float` | `rv32imfc` | `ilp32f` |
| `zfinx` | `/opt/openhw-riscv-zfinx` | `rv32imc_zfinx` | `ilp32` |

The x-heep device library (startup code, runtime, UART/SoC drivers) is **bundled directly in `sw/device/`**, so no external x-heep clone is required on the board.

### CLI

To program the FPGA and run a firmware image remotely:

```bash
python src/xheepRun.py \
  -o path/to/xheep_top.bit \
  -f path/to/firmware.elf  \
  --memory on_chip
```

### Argument Details

* `-o, --overlay`: Path to the FPGA bitstream (`.bit`) [required]
* `-f, --firmware`: Path to the compiled RISC-V `.elf` or `.bin` firmware [required]
* `-m, --memory`: Execution mode: `on_chip` (default), `flash_load`, or `flash_exec`
  - `on_chip`: Load and execute from internal RAM via JTAG (fastest, suitable for small programs)
  - `flash_load`: Program flash, then load and execute via JTAG (for larger programs)
  - `flash_exec`: Program flash and boot directly (persistent, no JTAG loading needed)
* `--verify`: Verify the loaded firmware against the source file after programming
* `--force`: Force a full PL reset and UART reconfiguration even if the bitstream hasn't changed

### Monitoring Serial Output

Once the dynamic overlay is injected *(Step 3 of the Execution Flow)*, the AXI UART is exposed as `/dev/ttyUL0`. You can connect to it using `picocom` at the default baud rate of 9600:

```bash
sudo picocom -b 9600 --imap lfcrlf /dev/ttyUL0
```

---

## Jupyter Notebook Interface

An interactive Jupyter notebook is available at `notebook/xheepNotebook.ipynb`. It provides the same functionality as the CLI but with an interactive widget-based UI, including:

- Bitstream and firmware path configuration
- One-click initialization and UART setup
- Interactive serial terminal with start/stop controls
- Buttons for each execution mode (on-chip, flash load, flash execute)
- Force reload and verification options

After running `make install-notebook`, the notebook is available at `~/jupyter_notebooks/xheep/xheepNotebook.ipynb` on the board's Jupyter server.

---
