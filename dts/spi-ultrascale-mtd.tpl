/dts-v1/;
/plugin/;
/ {
    fragment@0 {
        target-path = "/axi";
        __overlay__ {
            #address-cells = <2>;
            #size-cells = <2>;
            axi_quad_spi_0: spi@######## {
                compatible = "xlnx,axi-quad-spi-3.2", "xlnx,xps-spi-2.00.a";
                reg = <0x0 0x######## 0x0 0x10000>;
                interrupt-parent = <&gic>;
                interrupts = <0 INTERRUPT_ID 4>;
                clock-names = "ext_spi_clk", "s_axi_aclk";
                clocks = <&zynqmp_clk 71>, <&zynqmp_clk 71>;
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
