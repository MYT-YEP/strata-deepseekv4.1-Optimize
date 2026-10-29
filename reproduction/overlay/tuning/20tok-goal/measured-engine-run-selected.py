"""Run one guarded Xolotl controller while sampling lightweight local telemetry."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil

ROOT = Path(r"F:\STRATA\tuning\20tok-goal")
PYTHON = Path(r"F:\STRATA\terminal\current\python\python.exe")
ALLOWED = {"selected"}


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=sorted(ALLOWED))
    args = parser.parse_args()
    script = ROOT / ("xolotl-profile-" + args.variant + "-controller.py")
    smi = shutil.which("nvidia-smi.exe")
    if not script.is_file() or not PYTHON.is_file() or not smi:
        raise SystemExit("Controller, Python, or nvidia-smi is missing")
    tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
    prefix = ROOT / ("measured-" + args.variant + "-" + tag)
    telemetry = Path(str(prefix) + "-telemetry.jsonl")
    stdout = Path(str(prefix) + "-controller-stdout.log")
    stderr = Path(str(prefix) + "-controller-stderr.log")
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = os.environ.copy()
    env.update(TEMP=r"F:\STRATA\tmp", TMP=r"F:\STRATA\tmp", PYTHONUTF8="1")
    columns = ("temperature.gpu,power.draw,clocks.current.graphics,clocks.current.memory,"
               "utilization.gpu,utilization.memory,memory.used,pstate,pcie.link.gen.current")
    psutil.cpu_percent(None)
    started = time.monotonic()
    with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err, \
            telemetry.open("x", encoding="utf-8") as log:
        proc = subprocess.Popen([str(PYTHON), "-I", "-X", "utf8", str(script)],
                                cwd=r"F:\STRATA", env=env, stdout=out, stderr=err,
                                creationflags=no_window)
        print(json.dumps({"event": "started", "variant": args.variant, "controller_pid": proc.pid,
                          "telemetry": str(telemetry)}, ensure_ascii=False), flush=True)
        try:
            while proc.poll() is None:
                sample = {"time": stamp(), "seconds": round(time.monotonic() - started, 3),
                          "cpu_percent": psutil.cpu_percent(None),
                          "available_gib": round(psutil.virtual_memory().available / 1024**3, 3)}
                try:
                    r = subprocess.run([smi, "--query-gpu=" + columns, "--format=csv,noheader,nounits"],
                                       capture_output=True, text=True, timeout=4, creationflags=no_window)
                    sample["gpu_csv"] = r.stdout.strip() if r.returncode == 0 else None
                    if r.returncode:
                        sample["gpu_error"] = r.stderr.strip()[:300]
                except (subprocess.TimeoutExpired, OSError) as exc:
                    sample["gpu_error"] = str(exc)
                log.write(json.dumps(sample, ensure_ascii=False) + "\n")
                log.flush()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
            raise
    states = []
    for path in ROOT.glob("xolotl-trial-*-state.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("owner_pid") == proc.pid:
                states.append((path, value))
        except (OSError, ValueError):
            continue
    states.sort(key=lambda pair: pair[1].get("created_unix", 0), reverse=True)
    state_path, state = states[0] if states else (None, {})
    result = {"variant": args.variant, "controller_pid": proc.pid, "exit_code": proc.returncode,
              "elapsed_seconds": round(time.monotonic() - started, 3), "telemetry": str(telemetry),
              "state_path": str(state_path) if state_path else None, "run_id": state.get("run_id"),
              "phase": state.get("phase"), "need_restore": state.get("need_restore"), "result": state.get("result"),
              "stdout": str(stdout), "stderr": str(stderr)}
    Path(str(prefix) + "-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "finished", **result}, ensure_ascii=False), flush=True)
    return 0 if proc.returncode == 0 and state.get("phase") == "done" and not state.get("need_restore") else 1


if __name__ == "__main__":
    raise SystemExit(main())
