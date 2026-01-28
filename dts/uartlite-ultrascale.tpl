/dts-v1/;
/plugin/;

/ {
    fragment@0 {
        target-path = "/axi";

        __overlay__ {
            #address-cells = <2>;
            #size-cells = <2>;

            serial@######## {
                compatible = "xlnx,axi-uartlite-2.0", "xlnx,xps-uartlite-1.00.a";
                status = "okay";

                reg = <0x0 0x######## 0x0 0x10000>;

                interrupt-parent = <&gic>;
                interrupts = <0 89 4>;

                clocks = <&zynqmp_clk 71>;
                clock-names = "s_axi_aclk";

                current-speed = <115200>;
                xlnx,data-bits = <8>;
                xlnx,use-parity = <0>;
            };
        };
    };
};
