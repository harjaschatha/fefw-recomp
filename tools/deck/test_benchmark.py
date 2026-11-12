import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("benchmark.py")
spec = importlib.util.spec_from_file_location("benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkTests(unittest.TestCase):
    def test_gpu_profile_disables_cpu_sampler_even_if_inherited(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            code = "import os; assert os.environ['NXRT_PROF_SAMPLE_HZ']=='0'; assert os.environ['NXRT_PROF_GPU_PASSES']=='1'; assert os.environ['NXRT_PROF_TRACE'].endswith('/frame.trace'); assert os.environ['NXRT_PROF_TRACE'].startswith('Z:'); assert os.environ['NXRT_PROF_DELAY_SEC']=='180.0'; assert os.environ['NXRT_PROF_DURATION_SEC']=='60.0'"
            env = dict(benchmark.os.environ, NXRT_PROF_SAMPLE_HZ="100")
            result = subprocess.run([sys.executable, str(SCRIPT), "--game-dir", temp, "--output", str(root / "runs"),
                                     "--profile", "--delay", "180", "--duration", "60", "--", sys.executable, "-c", code], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = json.loads((root / "runs/latest/metadata.json").read_text())
            self.assertTrue(metadata["profile"])
            self.assertFalse(metadata["cpu_profile"])

    def test_sensor_units_and_cpu_deltas(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def put(path, value):
                p = root / path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(value)
            put("sys/class/hwmon/hwmon0/name", "amdgpu")
            put("sys/class/hwmon/hwmon0/temp1_input", "65000")
            put("sys/class/hwmon/hwmon0/power1_average", "12000000")
            put("proc/stat", "cpu 10 0 10 80 0 0 0 0 0 0\n")
            put("proc/meminfo", "MemTotal: 16384 kB\nMemAvailable: 8192 kB\n")
            hardware = benchmark.Hardware(root)
            first = hardware.sample()
            self.assertEqual(first["amdgpu_temp1_temp1_input_c"], 65)
            self.assertEqual(first["amdgpu_power1_power1_average_w"], 12)
            self.assertEqual(first["system_ram_used_mib"], 8)
            put("proc/stat", "cpu 20 0 20 160 0 0 0 0 0 0\n")
            self.assertAlmostEqual(hardware.sample()["system_cpu_busy_percent"], 20)

    def test_wrapper_collects_fresh_log_and_preserves_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / "game folder"
            game.mkdir()
            (game / "fefw.log").write_text("old fps 99.0, present pass GPU 9.000 ms avg\n" * 100)
            code = "import pathlib,time,sys,os; assert os.environ['NXRT_GFX_LOG_FPS']=='1'; pathlib.Path(sys.argv[1]).write_text('fps 24.0, present pass GPU 1.500 ms avg\\n'); time.sleep(.4); sys.exit(7)"
            run = subprocess.run([sys.executable, str(SCRIPT), "--game-dir", str(game), "--output", str(root / "runs"),
                                  "--interval", ".2", "--", sys.executable, "-c", code, str(game / "fefw.log")], capture_output=True, text=True)
            self.assertEqual(run.returncode, 7, run.stderr)
            report = json.loads((root / "runs/latest/summary.json").read_text())
            self.assertEqual(report["metrics"]["fps"]["mean"], 24)
            self.assertEqual(report["measured_fps_samples"], 1)
            self.assertTrue((root / "runs/latest/fefw.log").exists())

    def test_manual_window_without_start_has_no_measured_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = subprocess.run([sys.executable, str(SCRIPT), "--game-dir", temp, "--output", str(root / "runs"),
                                     "--manual", "--", sys.executable, "-c", "pass"], capture_output=True)
            self.assertEqual(result.returncode, 0)
            report = json.loads((root / "runs/latest/summary.json").read_text())
            self.assertEqual(report["measured_hardware_samples"], 0)

    def test_failed_launch_still_writes_report_without_stale_fps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "fefw.log").write_text("fps 99.0, present pass GPU 9.000 ms avg\n")
            result = subprocess.run([sys.executable, str(SCRIPT), "--game-dir", temp, "--output", str(root / "runs"),
                                     "--", str(root / "missing-runner")], capture_output=True)
            self.assertEqual(result.returncode, 1)
            report = json.loads((root / "runs/latest/summary.json").read_text())
            self.assertEqual(report["measured_fps_samples"], 0)
            self.assertIn("Launch failed", (root / "runs/latest/runner.log").read_text())
            self.assertFalse((root / "runs/latest/fefw.log").exists())

    def test_timed_window_excludes_loading_and_after_window(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = subprocess.run([sys.executable, str(SCRIPT), "--game-dir", temp, "--output", str(root / "runs"),
                                     "--interval", ".2", "--delay", ".3", "--duration", ".3", "--",
                                     sys.executable, "-c", "import time; time.sleep(1)"], capture_output=True)
            self.assertEqual(result.returncode, 0)
            with (root / "runs/latest/hardware.csv").open() as stream:
                rows = list(benchmark.csv.DictReader(stream))
            measured = [float(row["elapsed_s"]) for row in rows if row["measuring"] == "1"]
            self.assertTrue(measured)
            self.assertTrue(all(.3 <= elapsed < .8 for elapsed in measured))
            self.assertEqual(rows[0]["measuring"], "0")
            self.assertEqual(rows[-1]["measuring"], "0")


if __name__ == "__main__":
    unittest.main()
