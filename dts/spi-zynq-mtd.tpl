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
                interrupts = <0 INTERRUPT_ID 1>;
                clock-names = "ext_spi_clk", "s_axi_aclk";
                clocks = <&clkc 15>, <&clkc 15>;
                num-cs = <0x1>;
                xlnx,num-ss-bits = <0x1>;
                xlnx,spi-mode = <2>;  /* 0=standard, 1=dual, 2=quad */
                fifo-size = <16>;
                #address-cells = <1>;
                #size-cells = <0>;
                status = "okay";

                flash@0 {
                    compatible = "jedec,spi-nor";
                    reg = <0>;
                    spi-max-frequency = <10000000>;
                    status = "okay";

                    partitions {
                        compatible = "fixed-partitions";
                        #address-cells = <1>;
                        #size-cells = <1>;

                        partition@0 {
                            label = "xheep-firmware";
                            reg = <0x0 0x1000000>;  // 16MB, adjust based on your flash size
                        };
                    };
                };
            };
        };
    };
};
