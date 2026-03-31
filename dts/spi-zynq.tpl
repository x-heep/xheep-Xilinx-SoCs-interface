/dts-v1/;
/plugin/;

/*
 * Copyright 2025 Politecnico di Torino.
 *
 * File: spi-zynq.dts
 * Author: Christian Conti
 * Date: 31/03/2025
 *
 * AXI Quad SPI overlay for Zynq-7000 - SPIDEV version
 * Target: PYNQ-Z2 and similar boards
 *
 * This version creates /dev/spidevX.Y for raw SPI access.
 * Use this for debugging or when spi-nor driver doesn't probe.
 *
 * Placeholders:
 *   ######## -> SPI base address (es. 43c00000)
 */

/ {
    fragment@0 {
        target-path = "/";
        __overlay__ {
            #address-cells = <1>;
            #size-cells = <1>;

            axi_quad_spi_0: spi@######## {
                compatible = "xlnx,axi-quad-spi-3.2", "xlnx,xps-spi-2.00.a";
                reg = <0x######## 0x10000>;

                /* Zynq GIC interrupt: 0=SPI, 31=fabric, 1=rising edge */
                interrupt-parent = <&intc>;
                interrupts = <0 31 1>;

                /* Clocks: use fixed-clock */
                clocks = <&misc_clk_0>;
                clock-names = "ext_spi_clk";

                /* AXI Quad SPI controller properties */
                xlnx,num-ss-bits = <1>;
                xlnx,num-transfer-bits = <8>;
                xlnx,spi-mode = <0>;       /* 0=standard SPI */
                xlnx,fifo-depth = <16>;
                fifo-size = <16>;
                num-cs = <1>;

                #address-cells = <1>;
                #size-cells = <0>;
                status = "okay";

                /* SPIDEV child - creates /dev/spidevX.Y */
                spidev@0 {
                    compatible = "rohm,dh2228fv";  /* Generic SPI device */
                    reg = <0>;
                    spi-max-frequency = <10000000>;
                    status = "okay";
                };
            };

            /* Fixed clock for SPI controller */
            misc_clk_0: misc_clk_0 {
                compatible = "fixed-clock";
                #clock-cells = <0>;
                clock-frequency = <100000000>;
            };
        };
    };
};
