/dts-v1/;
/plugin/;

/ {
  fragment@0 {
  target-path = "/axi";
  
    __overlay__ {
      axi_quad_spi: spi@######## {
        compatible = "xlnx,axi-quad-spi-3.2", "xlnx,xps-spi-2.00.a";
        
        reg = <0x######## 0x10000>;
        
        interrupt-parent = <&gic>;
        interrupts = <0 INTERRUPT_ID 4>;
        
        clock-names = "ext_spi_clk", "s_axi_aclk";
        clocks = <&zynqmp_clk 71>, <&zynqmp_clk 71>;
        
        num-cs = <0x1>;
        xlnx,num-ss-bits = <0x1>;
        
        #address-cells = <1>;
        #size-cells = <0>;
        
        flash@0 {
          compatible = "jedec,spi-nor";
          
          reg = <0>;
          
          spi-max-frequency = <50000000>;
          
          #address-cells = <1>;
          #size-cells = <1>;
        };
      };
    };
  };
};