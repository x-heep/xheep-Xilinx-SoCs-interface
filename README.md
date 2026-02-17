# x-heep Xilinx Interface

This repository provides the software interface and drivers to integrate the [x-heep](https://github.com/x-heep/x-heep) RISC-V core with the Processing System (PS) of Xilinx SoCs.
This framework enables remote connectivity to the boards via SSH to deploy, test, and debug x-heep without physical access to the JTAG or UART headers.

The on-board Processing System enables a full "remote-lab" experience for RISC-V development.
The project acts as a bridge between the Xilinx ARM-based Processing System and the FPGA Programmable Logic (PL) where x-heep resides. It automates the complex process of synchronizing the Linux hardware description (Device Tree) with the live state of the FPGA.

### Key Features

* **Remote Deployment via SSH:** Manage the entire development cycle (programming, execution, and monitoring) over a network connection.
* **Remote Bitstream Loading:** Deploy x-heep hardware designs directly from Python using PYNQ-based drivers.
* **OpenOCD & XVC Integration:** Leverages OpenOCD 0.12.0 and the Xilinx Virtual Cable (XVC) protocol to load `.elf` firmware over AXI JTAG.
* **Dynamic UART Overlay:** Automatically patches, compiles, and loads a Linux Device Tree Overlay (DTO) to expose the AXI UART as a system device.
* **Execution Control:** Full remote control over the core lifecycle, including reset, boot mode selection, and exit status monitoring via GPIO.

---

## Supported Platforms

| Board   | Status    | Notes                                                      |
| ------- | --------- | ---------------------------------------------------------- |
| PYNQ-Z2 | Supported | Requires `PS_ENABLE` to be active in the x-heep bitstream. |
| AUP-ZU3 | Supported | Requires `PS_ENABLE` to be active in the x-heep bitstream. |

> **Important Note:** Ensure that the Vivado version used to implement x-heep is consistent with the Linux distribution installed on the board. For example:

---

## Installation

The installation process is fully automated through a single command.
This script installs system dependencies, builds OpenOCD with specific patches, and configures the Python environment.

```bash
sudo make install
```

> Note: This requires `sudo` privileges to manage system packages, install OpenOCD, and manipulate the kernel's ConfigFS.

### OpenOCD Build and Patch

During installation, the script automatically:

1. **Clones OpenOCD** from the official repository
2. **Applies a custom patch** (`patch/openocd.patch`) required for correct operation with the Xilinx Virtual Cable (XVC) and x-heep integration
3. **Builds OpenOCD** with the following features enabled:
   - FTDI interface support (`--enable-ftdi`)
   - Bitbang driver support (`--enable-bitbang`)
   - Xilinx AXI XVC support (`--enable-xlnx-axi-xvc`)
   - Internal JimTcl interpreter (`--enable-internal-jimtcl`)
4. **Installs OpenOCD** system-wide at `/usr/local/bin/openocd`

The patch is necessary to ensure proper communication between OpenOCD and the AXI JTAG IP core in the FPGA fabric.

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

1. Steps 1-4 same as above.
2. **Flash Programming:** The firmware binary is programmed into external flash using direct MMIO (without requiring kernel drivers).
3. **Flash Boot Configuration:** GPIO is configured to boot from flash.
4. **JTAG Loading:** Firmware is load and executed the same as on-chip mode.

### Flash Execute Mode
Boot and execute directly from flash without JTAG loading. Most persistent mode.

1. Steps 1-3 same as above.
2. **Flash Boot Configuration:** GPIO is configured to execute directly from flash.
3. **Direct Execution:** X-HEEP boots from flash and executes immediately without JTAG intervention.
4. **Monitoring:** Script monitors exit codes via GPIO.

---

## Hardware Configuration & JTAG

### OpenOCD XVC Configuration

The repository uses a specific OpenOCD configuration (`cfg/xheep_xilinx_xvc.cfg`) to enable the Xilinx Virtual Cable. This configuration allows OpenOCD to communicate with the `axi_jtag` IP inside the FPGA by mapping JTAG operations to memory-mapped I/O (MMIO) registers at the address specified by `XVC_DEV_ADDR`.

### GPIO Mapping

The `xheepGPIO` class manages the following control signals via the `axi_gpio` IP:

* **Bit 0 (rst_ni):** Active-low reset for the x-heep core.
* **Bit 1 (boot_select_i):** Selects between JTAG (0) and Flash (1) boot modes.
* **Bit 2 (execute_from_flash_i):** Controls if the core executes directly from Flash memory.
* **Bit 3 (jtag_trst_ni):** Active-low reset for the JTAG TAP controller.
* **Channel 2 (Exit Status):** Used to read the execution results (`exit_valid` and `exit_value`).

---

## Usage

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
* `--verify`: Verify the loaded firmware against the source file
* `--force`: Force a full PL reset and UART reconfiguration even if the bitstream hasn't changed

### Monitoring Serial Output

Once the dynamic overlay is injected *(Step 3 of the Execution Flow)*, the AXI UART is exposed as `/dev/ttyUL0`. You can connect to it using `picocom` at the default baud rate of 9600:

```bash
sudo picocom -b 9600 --imap lfcrlf /dev/ttyUL0
```

---
