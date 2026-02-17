/dts-v1/;
/plugin/;

/*
 * AXI Quad SPI overlay for ZynqMP (UltraScale+) - SPIDEV version
 * Target: AUP-ZU3 and similar boards
 *
 * This version creates /dev/spidevX.Y for raw SPI access.
 * Use this for debugging or when spi-nor driver doesn't probe.
 *
 * Placeholders:
 *   ######## -> SPI base address (es. a0030000)
 */

/ {
    fragment@0 {
        target-path = "/";
        __overlay__ {
            #address-cells = <2>;
            #size-cells = <2>;

            axi_quad_spi_0: spi@######## {
                compatible = "xlnx,axi-quad-spi-3.2", "xlnx,xps-spi-2.00.a";
                reg = <0x0 0x######## 0x0 0x10000>;

                /* GIC SPI interrupt: 0=SPI, 89=pl_ps_irq0[0], 4=level high */
                interrupt-parent = <&gic>;
                interrupts = <0 91 1>;

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
