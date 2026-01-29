import sys
import time
import struct
import socket
import subprocess
import hashlib
import telnetlib
import threading
import serial
from pathlib import Path
from IPython.display import display, HTML, clear_output
import ipywidgets as widgets

src_path = Path("src").resolve()
if src_path.exists() and str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from xheepDriver import xheepDriver

class _S:
    def __init__(self):
        self.drv = None
        self.bit_hash = self.bit_path = None
        self.ocd = self.ocd_fh = None
        self.ser_t = None
        self.ser_stop = threading.Event()
        self.ok = False
    
    def fhash(self, p):
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for c in iter(lambda: f.read(8192), b''): h.update(c)
        return h.hexdigest()
    
    def changed(self, p):
        if not self.bit_path: 
            return True
        if self.bit_path != p.resolve(): 
            return True
        return self.fhash(p) != self.bit_hash
    
    def upd(self, p): 
        self.bit_path, self.bit_hash = p.resolve(), self.fhash(p)
    
    def stop_ser(self):
        if self.ser_t and self.ser_t.is_alive():
            self.ser_stop.set(); self.ser_t.join(timeout=2)
        self.ser_stop.clear()
    
    def stop_ocd(self):
        if self.ocd and self.ocd.poll() is None:
            try: _cmd(["shutdown"], t=3)
            except: 
                pass
            if self.ocd.poll() is None: 
                self.ocd.terminate()
            try: 
                self.ocd.wait(timeout=2)
            except: 
                self.ocd.kill(); self.ocd.wait()
            if self.ocd_fh: 
                self.ocd_fh.close()
            self.ocd = self.ocd_fh = None
    def clean(self): self.stop_ser(); self.stop_ocd()

ctrl = _S()

def _tcp(h, p, t):
    dl = time.monotonic() + t
    while time.monotonic() < dl:
        try:
            with socket.create_connection((h, p), timeout=0.5): return
        except: 
            time.sleep(0.1)
    raise TimeoutError()

def _cmd(cmds, h="127.0.0.1", p=4444, t=30):
    tok = f"__D{time.monotonic_ns()}__"
    tn = telnetlib.Telnet(h, p, timeout=t)
    tn.read_until(b">", timeout=t)
    for c in cmds: 
        tn.write(c.encode() + b"\n")
    tn.write(f"echo {tok}\n".encode())
    return tn.read_until(tok.encode(), timeout=t).decode(errors="replace")

def _ocd(cfg, log, addr):
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log, "wb", buffering=0)
    return subprocess.Popen(["openocd", "-c", f"set XVC_DEV_ADDR 0x{addr:08x}", "-f", str(cfg)], stdout=fh, stderr=fh), fh

def _b(m, ok=True):
    c = ("#e8f5e9","#2e7d32") if ok else ("#ffebee","#c62828")
    return HTML(f'<div style="padding:8px 12px;border-left:4px solid {c[1]};background:{c[0]};color:{c[1]};font-family:monospace;border-radius:3px;">{m}</div>')

def init(bit, force=False):
    p = Path(bit).resolve()
    if not p.is_file(): 
        display(_b(f"❌ {p}", False))
        return False
    
    if force or ctrl.changed(p):
        ctrl.drv = xheepDriver(str(p))
        ctrl.upd(p)
        ctrl.ok = True
    
    display(_b("✓ Ready"))
    return True

def run(fw, verify=False):
    p = Path(fw).resolve()
    cfg = Path("cfg/xheep_xilinx_xvc.cfg").resolve()
    log = Path("xheep_logs/openocd.log")
    
    if not ctrl.ok: 
        display(_b("❌ Not initialized", False))
        return
    if not p.is_file(): 
        display(_b(f"❌ {p}", False))
        return
    
    try:
        ctrl.stop_ocd()
        ctrl.drv.gpio.bootFromJTAG()
        ctrl.drv.gpio.resetJTAG()
        ctrl.drv.gpio.resetXheep()
        time.sleep(0.05)
        
        entry = struct.unpack_from("<I", p.read_bytes()[:0x34], 0x18)[0]
        ctrl.ocd, ctrl.ocd_fh = _ocd(cfg, log, ctrl.drv.jtag.getAddr())
        time.sleep(0.2)
        if ctrl.ocd.poll() is not None: 
            display(_b("❌ OpenOCD failed", False))
            return
        
        _tcp("127.0.0.1", 4444, 10)
        fwq = "{" + str(p).replace("}", r"\}") + "}"
        cmds = ["targets riscv0", "halt", f"load_image {fwq}"]
        if verify: 
            cmds.append(f"verify_image {fwq}")
        _cmd(cmds, t=60)
        _cmd(["targets riscv0", f"resume 0x{entry:08x}"], t=15)
        
        v, e = ctrl.drv.gpio.getExitCode()
        while not v: 
            time.sleep(0.01); v, e = ctrl.drv.gpio.getExitCode()
        
        display(_b(f"exit_valid={v} | exit_value={e}", e == 0))
        return (v, e)
    except KeyboardInterrupt:
        v, e = ctrl.drv.gpio.getExitCode()
        display(_b(f"Interrupted: {v},{e}", False))
        return (v, e)
    finally:
        ctrl.stop_ocd()

def serialWidget():
    out = widgets.Output(layout=widgets.Layout(width='100%', height='250px', border='1px solid #ccc', overflow='auto'))
    btn_s = widgets.Button(description="▶", button_style='success')
    btn_x = widgets.Button(description="⏹", button_style='danger', disabled=True)
    btn_c = widgets.Button(description="⌫")

    def _rd():
        try:
            ser = serial.Serial("/dev/ttyUL0", 9600, timeout=0.1)
            while not ctrl.ser_stop.is_set():
                d = ser.read(256)
                if d:
                    with out: print(d.decode(errors='replace'), end='')
            ser.close()
        except Exception as e:
            with out: print(f"[{e}]")

    def _on_s(b):
        ctrl.ser_stop.clear()
        ctrl.ser_t = threading.Thread(target=_rd, daemon=True); ctrl.ser_t.start()
        btn_s.disabled, btn_x.disabled = True, False

    def _on_x(b): 
        ctrl.stop_ser()
        btn_s.disabled, btn_x.disabled = False, True

    btn_s.on_click(_on_s)
    btn_x.on_click(_on_x)
    btn_c.on_click(lambda b: out.clear_output())
    return widgets.VBox([widgets.HBox([btn_s, btn_x, btn_c]), out])
