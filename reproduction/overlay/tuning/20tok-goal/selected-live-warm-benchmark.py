"""Measure the already-running selected profile, yielding to other requests.

No service, model, environment or tuning parameter is restarted or changed.
The parent owns only its short-lived benchmark child and stops it on competing
traffic; the normal fast-mode watchdog remains responsible for service recovery.
"""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

import psutil

ROOT = Path(r"F:\STRATA\tuning\20tok-goal")
BENCH = ROOT / "real-benchmark.py"
META = ROOT / "fast-mode.json"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:8150"
ORIGINAL = "http://127.0.0.1:8080"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WARM_PROMPT = ("Give five concise practical steps for debugging a small Python program. "
               "Explain each step in one sentence.")


def get(base, path, timeout=4):
    with HTTP.open(base + path, timeout=timeout) as response:
        return json.load(response)


def stamp():
    return datetime.datetime.now().astimezone().isoformat()


def write_new(path, data):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def preflight():
    meta = json.loads(META.read_text(encoding="utf-8-sig"))
    state = json.loads(Path(meta["state"]).read_text(encoding="utf-8-sig"))
    process = psutil.Process(meta["pid"])
    if not process.is_running() or abs(process.create_time() - meta["created"]) > 0.01:
        raise RuntimeError("The fast manager identity no longer matches")
    if state.get("phase") != "candidate_ready" or not state.get("web_ready"):
        raise RuntimeError("The selected fast service is not ready")
    cfg = json.loads(Path(state["config"]).read_text(encoding="utf-8-sig"))
    if cfg["env"].get("STRATA_TIER_BATCH_PCIE") != "1.0" or cfg.get("model_name") != "deepseek-v4.1-flash":
        raise RuntimeError("The active model configuration is not the selected variant")
    health = get(BASE, "/health")
    models = get(BASE, "/v1/models")
    if not health.get("loaded") or health.get("max_context") != 65536 or health.get("model") != "deepseek-v4.1-flash":
        raise RuntimeError("The selected model is not ready with 64K context")
    if not any(m.get("id") == "deepseek-v4.1-flash" and m.get("status", {}).get("value") == "loaded" for m in models.get("data", [])):
        raise RuntimeError("The selected model is not loaded according to /v1/models")
    for base in (ORIGINAL, BASE):
        status = get(base, "/status")
        if status.get("busy") or status.get("queued"):
            raise RuntimeError("A user request is active or queued; no benchmark was started")
    return meta, state, health


def warm_worker(output):
    spec = importlib.util.spec_from_file_location("selected_real_benchmark", BENCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BASE = BASE
    started = stamp()
    row = module.run_case("warmup", WARM_PROMPT, 160)
    if not row.get("stream_completed") or not row.get("answer", "").strip():
        raise RuntimeError("Warmup did not complete a nonempty response")
    write_new(output, {"started_at": started, "finished_at": stamp(), "row": row})
    print(json.dumps({"event": "warmup_completed", "output_tokens": row["usage"]["completion_tokens"],
                      "decode_tps": row["timings"]["predicted_per_second"],
                      "first_text_seconds": row["first_text_seconds"], "elapsed_seconds": row["elapsed_seconds"],
                      "finish_reason": row["finish_reason"]}, ensure_ascii=False), flush=True)
    return 0


def sample(stop, target):
    smi = shutil.which("nvidia-smi.exe")
    columns = ("temperature.gpu,power.draw,clocks.current.graphics,clocks.current.memory,"
               "utilization.gpu,utilization.memory,memory.used,pstate,pcie.link.gen.current")
    psutil.cpu_percent(None)
    with target.open("x", encoding="utf-8") as handle:
        while not stop.is_set():
            record = {"time": stamp(), "cpu_percent": psutil.cpu_percent(None),
                      "available_gib": round(psutil.virtual_memory().available / 1024**3, 3)}
            if smi:
                try:
                    result = subprocess.run([smi, "--query-gpu=" + columns, "--format=csv,noheader,nounits"],
                                            capture_output=True, text=True, timeout=4, creationflags=NO_WINDOW)
                    record["gpu_csv"] = result.stdout.strip() if result.returncode == 0 else None
                except (OSError, subprocess.TimeoutExpired) as exc:
                    record["gpu_error"] = str(exc)[:300]
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            stop.wait(3)


def run_child(argv, label, log, meta, state):
    env = os.environ.copy()
    env.update(TEMP=r"F:\STRATA\tmp", TMP=r"F:\STRATA\tmp", PYTHONUTF8="1")
    stdout_path = Path(str(log) + "-" + label + "-stdout.log")
    stderr_path = Path(str(log) + "-" + label + "-stderr.log")
    with stdout_path.open("x", encoding="utf-8") as out, stderr_path.open("x", encoding="utf-8") as err:
        proc = subprocess.Popen(argv, cwd=r"F:\STRATA", env=env, stdout=out, stderr=err, creationflags=NO_WINDOW)
        print(json.dumps({"event": "started", "stage": label, "pid": proc.pid}, ensure_ascii=False), flush=True)
        reason = None
        deadline = time.monotonic() + 600
        try:
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    reason = "benchmark child exceeded its time limit"
                    break
                try:
                    active = json.loads(META.read_text(encoding="utf-8-sig"))
                    live_state = json.loads(Path(meta["state"]).read_text(encoding="utf-8-sig"))
                    if active.get("run_id") != meta.get("run_id") or live_state.get("phase") != "candidate_ready" or Path(state["yield_flag"]).exists():
                        reason = "the fast service stopped or yielded"
                        break
                    original = get(ORIGINAL, "/status", timeout=2)
                    candidate = get(BASE, "/status", timeout=2)
                    if original.get("busy") or original.get("queued") or (candidate.get("busy") and candidate.get("queued")):
                        reason = "another request became active or queued"
                        break
                except (OSError, ValueError, KeyError):
                    # A transient status failure is not proof that a service is stopped.
                    pass
                time.sleep(0.7)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        print(json.dumps({"event": "finished", "stage": label, "exit_code": proc.returncode,
                          "yield_reason": reason, "stdout": str(stdout_path), "stderr": str(stderr_path)},
                         ensure_ascii=False), flush=True)
        return proc.returncode == 0 and reason is None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warm-worker", type=Path)
    args = parser.parse_args()
    if args.warm_worker:
        return warm_worker(args.warm_worker)
    meta, state, health = preflight()
    tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
    prefix = ROOT / ("selected-live-warm-" + tag)
    print(json.dumps({"event": "preflight_ok", "run_id": meta["run_id"], "prefix": str(prefix),
                      "model": health["model"], "context": health["max_context"]}, ensure_ascii=False), flush=True)
    stop = threading.Event()
    telemetry = threading.Thread(target=sample, args=(stop, Path(str(prefix) + "-telemetry.jsonl")), daemon=True)
    telemetry.start()
    complete = False
    try:
        warm = Path(str(prefix) + "-warmup.json")
        if not run_child([sys.executable, "-I", "-X", "utf8", str(Path(__file__).resolve()), "--warm-worker", str(warm)],
                         "warmup", prefix, meta, state):
            return 2
        for round_no in (1, 2):
            preflight()
            path = Path(str(prefix) + f"-round{round_no}.json")
            if not run_child([sys.executable, "-I", "-X", "utf8", str(BENCH), "--base", BASE,
                              "--label", "selected-live-warm-" + tag, "--round", str(round_no), "--output", str(path)],
                             f"round{round_no}", prefix, meta, state):
                return 2
        complete = True
        return 0
    finally:
        stop.set()
        telemetry.join(timeout=6)
        write_new(Path(str(prefix) + "-result.json"), {"run_id": meta["run_id"], "finished_at": stamp(),
                  "complete": complete, "warmup": str(prefix) + "-warmup.json",
                  "round1": str(prefix) + "-round1.json", "round2": str(prefix) + "-round2.json",
                  "telemetry": str(prefix) + "-telemetry.jsonl"})


if __name__ == "__main__":
    sys.exit(main())
