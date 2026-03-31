/dts-v1/;
/plugin/;

/*
 * Copyright 2025 Politecnico di Torino.
 *
 * File: uartlite-zynq.dts
 * Author: Christian Conti
 * Date: 31/03/2025
 *
 * AXI UARTLite overlay for for Zynq-7000
 * Target: PYNQ-Z2 and similar boards
 *
 * Placeholders:
 *   ######## -> UARTLite base address (es. 43c00000)
 */

/ {
  fragment@0 {
    target-path = "/axi";

    __overlay__ {
      serial@######## {
        compatible = "xlnx,axi-uartlite-2.0", "xlnx,xps-uartlite-1.00.a";
        status = "okay";

        reg = <0x######## 0x00010000>;

        interrupt-parent = <&intc>;
        interrupts = <0 30 1>;

        clocks = <&clkc 0x0000000f>;
        clock-names = "s_axi_aclk";

        current-speed = <9600>;
        xlnx,data-bits = <8>;
        xlnx,use-parity = <0>;
      };
    };
  };
};