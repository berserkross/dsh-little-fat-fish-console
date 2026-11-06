"""诊断包：四个条目齐全、整包脱敏、日志尾部与探测明细都写人话（C3）。"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dshconsole import diagnostics, probe, status


def fake_cfg(root: Path, port: int = 3080):
    stdout = root / "dsh-web.stdout.log"
    stderr = root / "dsh-web.stderr.log"
    return SimpleNamespace(
        port=port,
        harness=root,
        node=Path("C:/node/node.exe"),
        bin_js=root / "node_modules/@deepseek-ai/dsh/lib/bin.js",
        dsh_home=root,
        tailscale=Path("C:/tailscale/tailscale.exe"),
        chrome=None,
        log_files=[stdout, stderr],
        token_log=stdout,
        stderr_log=stderr,
    )


def zip_text(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dsh-diag-"))
        self.dest = self.dir / "diagnostics.zip"

    def test_all_four_entries_are_written(self):
        produced = diagnostics.build(
            self.dest,
            meta={"port": 3080},
            probe_text="== 探测明细 ==",
            log_text="一行日志",
            windows_text="== 系统 ==",
        )
        self.assertEqual(produced, self.dest)
        with zipfile.ZipFile(self.dest) as archive:
            self.assertEqual(sorted(archive.namelist()), sorted(diagnostics.FILES))

    def test_every_secret_in_every_entry_is_masked(self):
        diagnostics.build(
            self.dest,
            meta={"note": "token=abc123", "path": "C:/x"},
            probe_text="看到 token=abc123 和 sk-xxxx 以及 gho_yyyy",
            log_text="Cookie: session=abc123\nsk-xxxx\ngho_yyyy",
            windows_text="Authorization: Bearer abc123",
        )
        for name, text in zip_text(self.dest).items():
            for secret in ("abc123", "sk-xxxx", "gho_yyyy"):
                self.assertNotIn(secret, text, f"{name} 里还有 {secret}")
        self.assertIn("****", zip_text(self.dest)["log-tail.txt"])

    def test_the_parent_directory_is_created(self):
        dest = self.dir / "新目录" / "diagnostics.zip"
        diagnostics.build(dest, meta={}, probe_text="", log_text="", windows_text="")
        self.assertTrue(dest.exists())


class MetaTests(unittest.TestCase):
    def test_meta_has_version_time_interpreter_and_path_fields(self):
        root = Path(tempfile.mkdtemp(prefix="dsh-diag-"))
        meta = diagnostics.meta_dict(fake_cfg(root), status=None, phase="running",
                                     pids=[123], notes=["一句说明"], timings={"node": 12})
        for key in ("app", "version", "generated_at", "python", "frozen", "phase",
                    "pids", "notes", "port", "config_path", "harness", "bin_js",
                    "log_files", "timings_ms"):
            self.assertIn(key, meta)
        self.assertEqual(meta["phase"], "running")
        self.assertEqual(meta["pids"], [123])
        self.assertEqual(meta["timings_ms"], {"node": 12})
        json.dumps(diagnostics._plain(meta), ensure_ascii=False)      # 能进 json

    def test_meta_falls_back_to_the_status_object(self):
        root = Path(tempfile.mkdtemp(prefix="dsh-diag-"))
        state = status.Status(phase=status.Phase.RUNNING, pids=[7], port_open=True,
                              notes=["来自状态"], timings={"total": 99})
        meta = diagnostics.meta_dict(fake_cfg(root), status=state)
        self.assertEqual(meta["phase"], "running")
        self.assertEqual(meta["pids"], [7])
        self.assertEqual(meta["notes"], ["来自状态"])
        self.assertEqual(meta["timings_ms"], {"total": 99})


class ProbeReportTests(unittest.TestCase):
    def test_without_data_it_still_describes_the_status(self):
        state = status.Status(phase=status.Phase.DEGRADED, pids=[1], port_open=True,
                              phone_open=False, ts_ip="100.1.2.3", lan_ips=["10.0.0.2"],
                              notes=["端口被占用"])
        text = diagnostics.probe_report(None, state)
        self.assertIn("异常（端口被占用）", text)
        self.assertIn("说明：端口被占用", text)

    def test_with_data_it_lists_each_timing_and_the_raw_output(self):
        raw = probe.RawProbe(
            processes=[(1, "node bin.js")], process_error=None,
            portproxy_text="0.0.0.0  3080  127.0.0.1  3080", portproxy_error=None,
            firewall=True, firewall_error=None, firewall_text="DSH Web 3080 access",
            addresses=[("10.0.0.2", "以太网")], address_error=None,
            ts_ip="100.1.2.3", ts_error=None,
            timings={"node": 800, "addresses": 40}, total_ms=1200,
        )
        text = diagnostics.probe_report(raw, None)
        self.assertIn("总耗时：1200 ms", text)
        self.assertIn("分项 node：800 ms", text)
        self.assertIn("portproxy| 0.0.0.0  3080", text)
        self.assertIn("firewall| DSH Web 3080 access", text)


class LogTailTests(unittest.TestCase):
    def test_both_logs_are_quoted_with_their_path_and_masked(self):
        root = Path(tempfile.mkdtemp(prefix="dsh-diag-"))
        cfg = fake_cfg(root)
        cfg.log_files[0].write_text("启动 token=abc123\n", encoding="utf-8")
        text = diagnostics.log_tail(cfg)
        self.assertIn(f"===== {cfg.log_files[0]} =====", text)
        self.assertIn("token=****", text)
        self.assertNotIn("abc123", text)
        self.assertIn("读不到", text)                       # stderr 还不存在也要写清楚


class ExportTests(unittest.TestCase):
    def test_export_collects_everything_without_touching_real_powershell(self):
        root = Path(tempfile.mkdtemp(prefix="dsh-diag-"))
        cfg = fake_cfg(root)
        cfg.log_files[0].write_text("dsh web: http://127.0.0.1:3080/?token=abc123\n"
                                    "sk-xxxx\ngho_yyyy\n", encoding="utf-8")
        dest = root / "out.zip"
        with mock.patch.object(diagnostics, "windows_report",
                               lambda port, **kw: f"== 系统 ==\nport={port}"):
            produced = diagnostics.export(dest, cfg=cfg)
        self.assertEqual(produced, dest)
        entries = zip_text(dest)
        self.assertEqual(sorted(entries), sorted(diagnostics.FILES))
        for text in entries.values():
            for secret in ("abc123", "sk-xxxx", "gho_yyyy"):
                self.assertNotIn(secret, text)
        self.assertIn("port=3080", entries["windows.txt"])
        json.loads(entries["meta.json"])


class StartupFailuresTests(unittest.TestCase):
    def test_summarizes_recent_startup_failures(self):
        root = Path(tempfile.mkdtemp(prefix="dsh-diag-"))
        cfg = fake_cfg(root)
        logs = root / "logs"
        logs.mkdir()
        for i in range(25):
            (logs / f"startup-2026-11-0{i % 10}T00-00-00.000Z-uuid-{i}.log").write_text(
                "WARNING: Raw diagnostics may contain configuration values.\n"
                "  error: StartupError: dsh: startup failed: 2 required plugins\n"
                "      Error: listen EADDRINUSE: address already in use 127.0.0.1:3080\n",
                encoding="utf-8")
        text = diagnostics.startup_failures(cfg)
        self.assertEqual(text.count("startup-"), 20)
        self.assertIn("EADDRINUSE", text)

    def test_startup_failures_describes_missing_home(self):
        root = Path(tempfile.mkdtemp(prefix="dsh-diag-"))
        cfg = fake_cfg(root)
        cfg.dsh_home = None
        text = diagnostics.startup_failures(cfg)
        self.assertIn("DSH_HOME", text)


if __name__ == "__main__":
    unittest.main()
