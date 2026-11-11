
import re, subprocess, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dsh_gui

PORT = 3099
TMP = Path(tempfile.mkdtemp(prefix="dsh-cycle-"))
home = TMP / "home"; home.mkdir(parents=True, exist_ok=True)
out_log = TMP / "dsh-web.stdout.log"
err_log = TMP / "dsh-web.stderr.log"

real = dsh_gui.CFG
assert real.node and real.bin_js and real.harness, "本机探测不完整"
dsh_gui.PORT = PORT
dsh_gui.TOKEN_LOG = str(out_log)
dsh_gui.CFG = SimpleNamespace(node=real.node, bin_js=real.bin_js, harness=real.harness,
                              dsh_home=home, port=PORT, stderr_log=err_log)

def owner(port):
    try:
        txt = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    for line in txt.splitlines():
        if "LISTENING" in line and re.search(rf":{port}\s", line):
            return int(line.split()[-1])
    return None

class App:
    def __init__(self):
        self.lines = []
        self._port_open = lambda: dsh_gui.probe.port_open(PORT)
    def log_async(self, msg):
        self.lines.append(msg); print("LOG:", msg, flush=True)
    def logline(self, msg): self.log_async(msg)
    def refresh(self, force=False): pass
    def _start_direct(self): return dsh_gui.ConsoleApp._start_direct(self)
    def _wait_started(self, timeout, note_every=10.0):
        return dsh_gui.ConsoleApp._wait_started(self, timeout, note_every)
    def _dump_tails(self): return dsh_gui.ConsoleApp._dump_tails(self)
    def _serve_host_arg(self): return ""      # 隔离探针不绑 tailnet 域名
    def _stop(self, pids): return dsh_gui.ConsoleApp._stop(self, pids)

def token_now():
    try:
        m = re.search(r"token=([A-Za-z0-9_\-]+)", out_log.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return m.group(1) if m else None

app = App()
res = {}

t0 = time.time(); res["start1"] = app._start_direct()
res["wait1"] = app._wait_started(90.0, note_every=15.0)
res["boot1_s"] = round(time.time() - t0, 1)
res["tok1"] = token_now()
pid1 = owner(PORT); res["pid1"] = pid1

if pid1:
    t1 = time.time(); app._stop([pid1]); res["stop1_s"] = round(time.time() - t1, 1)
res["closed1"] = dsh_gui.probe.port_open(PORT)

t2 = time.time(); res["start2"] = app._start_direct()
res["wait2"] = app._wait_started(90.0, note_every=15.0)
res["boot2_s"] = round(time.time() - t2, 1)
res["tok2"] = token_now()
pid2 = owner(PORT); res["pid2"] = pid2
if pid2:
    app._stop([pid2])
res["closed2"] = dsh_gui.probe.port_open(PORT)

res["real_3080"] = dsh_gui.probe.port_open(3080)
res["real_3081"] = dsh_gui.probe.port_open(3081)
res["tmp"] = str(TMP)
for k, v in res.items():
    print(f"{k} = {v}")
