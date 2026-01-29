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

The `xheepRun.py` script follows a strict sequence to ensure hardware stability and kernel synchronization:

1. **UART Cleanup:** Before any hardware changes, the script checks if the AXI UART is active. It performs a driver unbind and removes the existing overlay to prevent kernel hangs during PL reset.
2. **PL Reset & Programming:** The Programmable Logic is reset and the new bitstream is loaded via the PYNQ Overlay manager.
3. **Dynamic Overlay Injection:** The driver retrieves the AXI UART physical address from the bitstream, patches the `uartlite-overlay.tpl` file, compiles it into a `.dtbo`, and injects it into the live kernel via ConfigFS. This re-attaches the UART, creating `/dev/ttyUL0`.
4. **User Confirmation:** The system halts and waits for the user to press Enter. This allows the user to prepare external debuggers or serial monitors.
5. **JTAG Firmware Load:** OpenOCD starts an XVC server using the AXI JTAG base address. The script connects via Telnet to halt the core and load the `.elf` firmware into memory.
6. **Monitoring:** Once execution begins, the script monitors GPIO signals. Upon completion, it displays the Exit Valid and Exit Value codes to indicate if the program succeeded or failed.

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
  --verify
```

### Argument Details

* `-o`: Path to the FPGA bitstream (`.bit`)
* `-f`: Path to the compiled RISC-V `.elf` firmware
* `--verify`: Verify the loaded firmware

### Monitoring Serial Output

Once the dynamic overlay is injected *(Step 3 of the Execution Flow)*, the AXI UART is exposed as `/dev/ttyUL0`. You can connect to it using `picocom` at the default baud rate of 9600:

```bash
sudo picocom -b 9600 --imap lfcrlf /dev/ttyUL0
```

---
