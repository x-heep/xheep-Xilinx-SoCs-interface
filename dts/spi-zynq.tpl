/dts-v1/;
/plugin/;

/ {
    fragment@0 {
        target-path = "/axi";
        __overlay__ {
            axi_quad_spi_0: spi@######## {
                compatible = "xlnx,axi-quad-spi-3.2", "xlnx,xps-spi-2.00.a";
                reg = <0x######## 0x10000>;
                interrupt-parent = <&intc>;
                interrupts = <0 INTERRUPT_ID 4>;
                clock-names = "ext_spi_clk", "s_axi_aclk";
                clocks = <&clkc 15>, <&clkc 15>;
                num-cs = <0x1>;
                xlnx,num-ss-bits = <0x1>;
                fifo-size = <16>;
                bits-per-word = <8>;
                #address-cells = <1>;
                #size-cells = <0>;
                
                spidev@0 {
                    compatible = "rohm,dh2228fv";
                    reg = <0>;
                    spi-max-frequency = <50000000>;
                };
            };
        };
    };
};
