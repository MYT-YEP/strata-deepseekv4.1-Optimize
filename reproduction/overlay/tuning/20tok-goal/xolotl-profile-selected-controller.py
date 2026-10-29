"""Run an isolated Xolotl comparison with a fail-safe Strata restore.

The watchdog observes the original service and yields to user traffic.  All
candidate processes are identified by a per-run config path, never by name
alone.  This script does not edit the original configuration or model files.
"""
import argparse
import contextlib
import ctypes
import datetime
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
import uuid

import psutil

ROOT = pathlib.Path(r"F:\STRATA\tuning\20tok-goal")
SOURCE_CONFIG = ROOT / "xolotl-dflash-bias075-full-draft-pcie100-64k.json"
SERVER = pathlib.Path(r"F:\STRATA\research\Xolotl\tools\v41\serve\serve_ds41.py")
PYTHON = pathlib.Path(r"F:\STRATA\terminal\current\python\python.exe")
BENCHMARK = ROOT / "real-benchmark.py"
ORIGINAL = "http://127.0.0.1:8080"
CANDIDATE = "http://127.0.0.1:8150"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RESTORE_HELPER = ROOT / "restore-original-norestart.cmd"


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def record(path, event, **data):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": stamp(), "event": event, **data}, ensure_ascii=False) + "\n")
        f.flush()


def write_json(path, value):
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def request(base, path, data=None, timeout=5):
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(base + path, data=body,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with HTTP.open(req, timeout=timeout) as response:
        return json.load(response)


def path_eq(a, b):
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def candidate_servers(state):
    """Find only servers bearing both the exact script and the unique config."""
    matches = []
    for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            args = p.info["cmdline"] or []
            if (any(path_eq(a, state["server"]) for a in args)
                    and any(path_eq(a, state["config"]) for a in args)
                    and p.info["create_time"] >= state["created_unix"] - 5):
                matches.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            continue
    return matches


def stop_candidate(state, log):
    servers = candidate_servers(state)
    children = []
    for server in servers:
        try:
            children.extend(server.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    # The parent and its recursively obtained children belong to this run.
    processes = children + servers
    if processes:
        record(log, "stopping_candidate", pids=[p.pid for p in processes])
    for p in processes:
        try:
            p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(processes, timeout=15)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if alive:
        _, remaining = psutil.wait_procs(alive, timeout=15)
        if remaining:
            raise RuntimeError("Candidate processes did not stop: " + str([p.pid for p in remaining]))


@contextlib.contextmanager
def restore_mutex():
    """Cross-process lock; Windows releases it even if its owner crashes."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, "Local\\STRATA-20tok-original-restore")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    code = kernel.WaitForSingleObject(handle, 0)
    acquired = code in (0, 0x80)  # WAIT_OBJECT_0 or an abandoned mutex
    try:
        if code not in (0, 0x80, 0x102):
            raise ctypes.WinError(ctypes.get_last_error())
        yield acquired
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def wait_original_health(process, log):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            h = request(ORIGINAL, "/health", timeout=3)
            if h.get("loaded") and h.get("model") == "deepseek-v4.1-flash" and h.get("max_context") == 65536:
                return True
        except Exception:
            pass
        if process is not None and process.poll() not in (None, 0):
            record(log, "restore_launcher_failed", exit_code=process.returncode)
            return False
        time.sleep(2)
    record(log, "restore_launcher_timed_out")
    return False


def start_original_if_missing(state, log):
    """Recover a vanished original server without ever forcing a restart."""
    if state["original"] != ORIGINAL or not RESTORE_HELPER.is_file():
        return False
    with restore_mutex() as acquired:
        if not acquired:
            record(log, "restore_wait_other_launcher")
            return wait_original_health(None, log)
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(("127.0.0.1", 8080)) == 0:
                record(log, "restore_launcher_skipped", reason="port 8080 is already in use")
                return False
        # If a launcher or engine is already starting, wait for it.  This also
        # prevents a watchdog from launching a second copy after its owner died.
        existing = []
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                args = p.info["cmdline"] or []
                if (str(p.info["name"]).lower() == "strata-dsv41.exe"
                        or any(path_eq(x, RESTORE_HELPER) for x in args)):
                    existing.append(p.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
                pass
        process = None
        if existing:
            record(log, "restore_wait_existing", pids=existing)
        else:
            prefix = ROOT / ("xolotl-trial-" + state["run_id"] + "-restore-launch")
            with open(str(prefix) + ".out.log", "a", encoding="utf-8") as out, \
                    open(str(prefix) + ".err.log", "a", encoding="utf-8") as err:
                process = subprocess.Popen([os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
                                            "/c", str(RESTORE_HELPER)], cwd=r"F:\STRATA",
                                           stdout=out, stderr=err, creationflags=CREATE_NO_WINDOW)
            record(log, "restore_launcher_started", pid=process.pid, helper=str(RESTORE_HELPER))
        return wait_original_health(process, log)


def restore_original(state, log):
    base = state["original"]
    for attempt in range(1, 4):
        try:
            health = request(base, "/health", timeout=8)
            if not health.get("loaded"):
                record(log, "original_loading", attempt=attempt)
                reply = request(base, "/load", {}, timeout=900)
                record(log, "original_load_reply", reply=reply)
                health = request(base, "/health", timeout=8)
            if (health.get("loaded") and health.get("model") == "deepseek-v4.1-flash"
                    and health.get("max_context") == 65536):
                models = request(base, "/v1/models", timeout=8)
                if any(x.get("id") == "deepseek-v4.1-flash" for x in models.get("data", [])):
                    record(log, "original_restored", health=health)
                    return True
            raise RuntimeError("Original service did not report the expected loaded model and context")
        except Exception as exc:
            record(log, "restore_attempt_failed", attempt=attempt, error=str(exc))
            if attempt == 1 and start_original_if_missing(state, log):
                continue
            if attempt < 3:
                time.sleep(5)
    return False


def watchdog(state_path):
    state_path = pathlib.Path(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    log = pathlib.Path(state["watchdog_log"])
    ready = pathlib.Path(state["watchdog_ready"])
    signal = pathlib.Path(state["yield_flag"])
    try:
        owner = psutil.Process(state["owner_pid"])
        if abs(owner.create_time() - state["owner_created"]) > 0.01:
            raise RuntimeError("Controller process identity changed")
        ready.write_text(stamp(), encoding="utf-8")
        record(log, "watchdog_ready", owner=owner.pid)
        while True:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            try:
                owner.wait(timeout=0)
                alive = False
            except psutil.TimeoutExpired:
                alive = owner.is_running() and abs(owner.create_time() - state["owner_created"]) < 0.01
            except psutil.NoSuchProcess:
                alive = False
            if not alive:
                record(log, "owner_exited", phase=state.get("phase"), need_restore=state.get("need_restore"))
                stop_candidate(state, log)
                if state.get("need_restore"):
                    ok = restore_original(state, log)
                    record(log, "watchdog_restore_result", ok=ok)
                return 0
            if state.get("phase") in ("candidate_starting", "candidate_ready", "benchmarking"):
                reason = None
                try:
                    status = request(state["original"], "/status", timeout=3)
                    health = request(state["original"], "/health", timeout=3)
                    if status.get("busy") or status.get("queued"):
                        reason = "Original service has a running or queued request"
                    elif health.get("loaded"):
                        reason = "Original model has reloaded"
                    elif psutil.virtual_memory().available < 2 * 1024**3:
                        reason = "Available system memory fell below 2 GiB"
                except Exception as exc:
                    reason = "Original service could not be monitored: " + str(exc)
                if reason and not signal.exists():
                    signal.write_text(reason, encoding="utf-8")
                    record(log, "yielding", reason=reason)
                    stop_candidate(state, log)
            if state.get("phase") == "done" and not state.get("need_restore"):
                record(log, "watchdog_done")
                return 0
            time.sleep(0.7)
    except Exception as exc:
        record(log, "watchdog_error", error=str(exc), traceback=traceback.format_exc())
        return 1


def check_watchdog(proc, signal):
    if proc.poll() is not None:
        raise RuntimeError("Restoration watchdog exited unexpectedly")
    if signal.exists():
        raise InterruptedError(signal.read_text(encoding="utf-8"))


def wait_process(proc, watchdog_proc, signal, limit):
    deadline = time.monotonic() + limit
    while proc.poll() is None:
        check_watchdog(watchdog_proc, signal)
        if time.monotonic() > deadline:
            proc.terminate()
            raise TimeoutError("Benchmark timed out")
        time.sleep(0.5)
    check_watchdog(watchdog_proc, signal)
    if proc.returncode:
        raise RuntimeError("Benchmark failed with exit code " + str(proc.returncode))


def run():
    if not PYTHON.is_file() or not SERVER.is_file() or not SOURCE_CONFIG.is_file():
        raise RuntimeError("Required candidate files are missing")
    cfg = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8-sig"))
    if not pathlib.Path(cfg["exe"]).is_file():
        raise RuntimeError("Candidate engine has not finished building")
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", 8150)) == 0:
            raise RuntimeError("Candidate port 8150 is already in use")
    health = request(ORIGINAL, "/health")
    status = request(ORIGINAL, "/status")
    if (not health.get("loaded") or health.get("model") != "deepseek-v4.1-flash"
            or health.get("max_context") != 65536):
        raise RuntimeError("Original model must already be loaded with 64K context")
    if status.get("busy") or status.get("queued"):
        raise RuntimeError("Original service is busy; nothing was unloaded")

    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
    prefix = ROOT / ("xolotl-trial-" + run_id)
    config_path = pathlib.Path(str(prefix) + "-config.json")
    state_path = pathlib.Path(str(prefix) + "-state.json")
    controller_log = pathlib.Path(str(prefix) + "-controller.jsonl")
    watchdog_log = pathlib.Path(str(prefix) + "-watchdog.jsonl")
    ready = pathlib.Path(str(prefix) + "-watchdog-ready.txt")
    signal = pathlib.Path(str(prefix) + "-yield.txt")
    cfg["log"] = str(prefix) + "-engine.log"
    write_json(config_path, cfg)
    owner = psutil.Process()
    state = {"run_id": run_id, "owner_pid": os.getpid(), "owner_created": owner.create_time(),
             "created_unix": time.time(), "config": str(config_path), "server": str(SERVER),
             "original": ORIGINAL, "candidate": CANDIDATE, "phase": "preflight", "need_restore": False,
             "watchdog_log": str(watchdog_log), "watchdog_ready": str(ready), "yield_flag": str(signal)}
    write_json(state_path, state)
    record(controller_log, "preflight", health=health, status=status, config=str(config_path))
    watchdog_proc = subprocess.Popen([str(PYTHON), "-I", "-X", "utf8", str(pathlib.Path(__file__).resolve()),
                                      "--watchdog", str(state_path)], creationflags=CREATE_NO_WINDOW)
    server_proc = None
    bench_proc = None
    result = "failed"
    try:
        deadline = time.monotonic() + 15
        while not ready.exists():
            if watchdog_proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Restoration watchdog did not start")
            time.sleep(0.2)
        # The service itself rejects /unload atomically if traffic arrived after preflight.
        state.update(phase="unload_intent", need_restore=True)
        write_json(state_path, state)
        reply = request(ORIGINAL, "/unload", {}, timeout=120)
        record(controller_log, "unload_reply", reply=reply)
        if reply.get("status") not in ("unloaded", "not loaded"):
            raise RuntimeError("Original model was not unloaded: " + str(reply))
        if request(ORIGINAL, "/health").get("loaded"):
            raise RuntimeError("Original service still reports a loaded model")
        check_watchdog(watchdog_proc, signal)
        state.update(phase="candidate_starting")
        write_json(state_path, state)
        env = os.environ.copy()
        env.update({"TEMP": r"F:\STRATA\tmp", "TMP": r"F:\STRATA\tmp", "PYTHONUTF8": "1"})
        server_out = open(str(prefix) + "-server.out.log", "w", encoding="utf-8")
        server_err = open(str(prefix) + "-server.err.log", "w", encoding="utf-8")
        cold_started = time.perf_counter()
        check_watchdog(watchdog_proc, signal)
        server_proc = subprocess.Popen([str(PYTHON), "-I", "-X", "utf8", str(SERVER), "--engine", "strata", "--config",
                                        str(config_path), "--host", "127.0.0.1", "--port", "8150"],
                                       cwd=str(SERVER.parents[3]), env=env, stdout=server_out, stderr=server_err,
                                       creationflags=CREATE_NO_WINDOW)
        record(controller_log, "candidate_started", pid=server_proc.pid)
        deadline = time.monotonic() + 900
        candidate_health = None
        while time.monotonic() < deadline:
            check_watchdog(watchdog_proc, signal)
            if server_proc.poll() is not None:
                raise RuntimeError("Candidate server exited with code " + str(server_proc.returncode))
            try:
                candidate_health = request(CANDIDATE, "/health", timeout=2)
                if candidate_health.get("loaded"):
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise TimeoutError("Candidate model did not become ready in 900 seconds")
        cold_seconds = time.perf_counter() - cold_started
        if candidate_health.get("model") != "deepseek-v4.1-flash" or candidate_health.get("max_context") != 65536:
            raise RuntimeError("Candidate reported the wrong model or context: " + str(candidate_health))
        models = request(CANDIDATE, "/v1/models")
        if not any(x.get("id") == "deepseek-v4.1-flash" for x in models.get("data", [])):
            raise RuntimeError("Candidate /v1/models does not list the expected model")
        record(controller_log, "candidate_ready", cold_load_seconds=round(cold_seconds, 3),
               health=candidate_health, models=models)
        engine_log = pathlib.Path(cfg["log"]).read_text(encoding="utf-8", errors="replace")
        if "DSpark: using 78 audited dflash tensor aliases" not in engine_log or "DSpark disabled" in engine_log:
            raise RuntimeError("The existing DSpark sidecar did not load; see the engine log")
        state.update(phase="candidate_ready")
        write_json(state_path, state)
        check_watchdog(watchdog_proc, signal)
        # The first measured prompt is deliberately the first inference after loading.
        record(controller_log, "cold_benchmark_no_warmup")
        state.update(phase="benchmarking")
        write_json(state_path, state)
        for round_no in (1, 2):
            check_watchdog(watchdog_proc, signal)
            output = pathlib.Path(str(prefix) + "-round" + str(round_no) + ".json")
            bench_out = open(str(prefix) + "-round" + str(round_no) + ".log", "w", encoding="utf-8")
            bench_proc = subprocess.Popen([str(PYTHON), "-I", "-X", "utf8", str(BENCHMARK), "--base", CANDIDATE,
                                           "--label", "xolotl-dspark-bias075-pcie100-64k-" + run_id, "--round", str(round_no),
                                           "--output", str(output)], stdout=bench_out, stderr=subprocess.STDOUT,
                                          creationflags=CREATE_NO_WINDOW, env=env)
            record(controller_log, "benchmark_started", round=round_no, pid=bench_proc.pid)
            wait_process(bench_proc, watchdog_proc, signal, 900)
            bench_out.close()
            result_data = json.loads(output.read_text(encoding="utf-8"))
            record(controller_log, "benchmark_completed", round=round_no, summary=result_data.get("summary"))
        result = "screen_completed"
    except Exception as exc:
        record(controller_log, "trial_stopped", error=str(exc), traceback=traceback.format_exc())
    finally:
        if bench_proc is not None and bench_proc.poll() is None:
            bench_proc.terminate()
            try:
                bench_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                bench_proc.kill()
        state.update(phase="restoring")
        write_json(state_path, state)
        try:
            stop_candidate(state, controller_log)
            restored = restore_original(state, controller_log) if state["need_restore"] else True
        except Exception as exc:
            restored = False
            record(controller_log, "restore_error", error=str(exc), traceback=traceback.format_exc())
        state.update(phase="done" if restored else "restore_failed", need_restore=not restored, result=result)
        write_json(state_path, state)
        record(controller_log, "trial_finished", result=result, restored=restored)
    return 0 if result == "screen_completed" and restored else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchdog")
    args = parser.parse_args()
    if args.watchdog:
        sys.exit(watchdog(args.watchdog))
    try:
        sys.exit(run())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
