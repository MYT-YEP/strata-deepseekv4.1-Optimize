"""Run the optional text-only Harness mode and restore the normal model on exit."""
import contextlib
import ctypes
import datetime
import importlib.util
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from ctypes import wintypes

import psutil

ROOT = pathlib.Path(r"F:\STRATA\tuning\20tok-goal")
SUPPORT = ROOT / "xolotl-run-controller.py"
CFG = ROOT / "xolotl-dflash-bias075-full-draft-64k.json"
META = ROOT / "fast-mode.json"
FAST_LAUNCHER = pathlib.Path(r"F:\STRATA\harness-fast-launch.cjs")
spec = importlib.util.spec_from_file_location("strata_fast_support", SUPPORT)
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


@contextlib.contextmanager
def fast_mutex():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, "Local\\STRATA-20tok-fast-mode")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    code = kernel.WaitForSingleObject(handle, 0)
    acquired = code in (0, 0x80)
    try:
        if code not in (0, 0x80, 0x102):
            raise ctypes.WinError(ctypes.get_last_error())
        yield acquired
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def port_available(port):
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def run():
    if not CFG.is_file() or not FAST_LAUNCHER.is_file():
        raise RuntimeError("Fast model or isolated Harness profile is missing")
    node_path = pathlib.Path(r"F:\STRATA\toolchains\node-24.14.0\node.exe")
    if not node_path.is_file():
        raise RuntimeError("The local Node.js runtime is missing from F:\\STRATA\\toolchains")
    node = str(node_path)
    if not port_available(8150) or not port_available(3081):
        raise RuntimeError("The candidate model or fast Harness port is already in use")
    health = support.request(support.ORIGINAL, "/health")
    status = support.request(support.ORIGINAL, "/status")
    if (not health.get("loaded") or health.get("model") != "deepseek-v4.1-flash"
            or health.get("max_context") != 65536):
        raise RuntimeError("Start the original 64K model before enabling fast mode")
    if status.get("busy") or status.get("queued"):
        raise RuntimeError("Original model is busy; fast mode did not start")
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    if not pathlib.Path(cfg["exe"]).is_file():
        raise RuntimeError("Fast engine executable is missing")

    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
    prefix = ROOT / ("xolotl-trial-" + run_id)
    config_path = pathlib.Path(str(prefix) + "-config.json")
    state_path = pathlib.Path(str(prefix) + "-state.json")
    log = pathlib.Path(str(prefix) + "-controller.jsonl")
    watchdog_log = pathlib.Path(str(prefix) + "-watchdog.jsonl")
    ready = pathlib.Path(str(prefix) + "-watchdog-ready.txt")
    signal = pathlib.Path(str(prefix) + "-yield.txt")
    stop = pathlib.Path(str(prefix) + "-stop.txt")
    web_script = pathlib.Path(str(prefix) + "-fast-web.cjs")
    web_log = pathlib.Path(str(prefix) + "-fast-web.out.log")
    web_err = pathlib.Path(str(prefix) + "-fast-web.err.log")
    cfg["log"] = str(prefix) + "-engine.log"
    support.write_json(config_path, cfg)
    if web_script.exists():
        raise RuntimeError("The per-run web launcher already exists")
    web_script.write_text("require('F:/STRATA/harness-fast-launch.cjs');\n", encoding="utf-8")
    owner = psutil.Process()
    state = {"run_id": run_id, "owner_pid": os.getpid(), "owner_created": owner.create_time(),
             "created_unix": time.time(), "config": str(config_path), "server": str(support.SERVER),
             "original": support.ORIGINAL, "candidate": support.CANDIDATE, "phase": "preflight",
             "need_restore": False, "watchdog_log": str(watchdog_log), "watchdog_ready": str(ready),
             "yield_flag": str(signal), "web_script": str(web_script), "web_ready": False,
             "stop_flag": str(stop)}
    support.write_json(state_path, state)
    support.write_json(META, {"run_id": run_id, "pid": os.getpid(), "created": owner.create_time(),
                              "state": str(state_path), "web_log": str(web_log), "stop_flag": str(stop),
                              "port": 3081, "sessions": "separate"})
    support.record(log, "fast_preflight", health=health, status=status)
    watchdog = subprocess.Popen([str(support.PYTHON), "-I", "-X", "utf8", str(SUPPORT),
                                  "--watchdog", str(state_path)], creationflags=support.CREATE_NO_WINDOW)
    server_proc = None
    web_proc = None
    result = "failed"
    restored = False
    try:
        deadline = time.monotonic() + 15
        while not ready.exists():
            if watchdog.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Restoration watchdog did not start")
            time.sleep(0.2)
        state.update(phase="unload_intent", need_restore=True)
        support.write_json(state_path, state)
        reply = support.request(support.ORIGINAL, "/unload", {}, timeout=120)
        support.record(log, "unload_reply", reply=reply)
        if reply.get("status") not in ("unloaded", "not loaded"):
            raise RuntimeError("Original model could not be unloaded")
        if support.request(support.ORIGINAL, "/health").get("loaded"):
            raise RuntimeError("Original model still reports loaded")
        support.check_watchdog(watchdog, signal)
        state.update(phase="candidate_starting")
        support.write_json(state_path, state)
        env = os.environ.copy()
        env.update({"TEMP": r"F:\STRATA\tmp", "TMP": r"F:\STRATA\tmp"})
        server_out = open(str(prefix) + "-server.out.log", "w", encoding="utf-8")
        server_err = open(str(prefix) + "-server.err.log", "w", encoding="utf-8")
        started = time.perf_counter()
        support.check_watchdog(watchdog, signal)
        server_proc = subprocess.Popen([str(support.PYTHON), "-I", "-X", "utf8", str(support.SERVER),
                                        "--engine", "strata", "--config", str(config_path),
                                        "--host", "127.0.0.1", "--port", "8150"],
                                       cwd=r"F:\STRATA\research\Xolotl", env=env,
                                       stdout=server_out, stderr=server_err, creationflags=support.CREATE_NO_WINDOW)
        support.record(log, "candidate_started", pid=server_proc.pid)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            support.check_watchdog(watchdog, signal)
            if stop.exists():
                raise InterruptedError("Fast mode was stopped while loading")
            if server_proc.poll() is not None:
                raise RuntimeError("Fast engine exited while loading")
            try:
                candidate = support.request(support.CANDIDATE, "/health", timeout=2)
                if candidate.get("loaded"):
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise TimeoutError("Fast model did not become ready")
        if candidate.get("model") != "deepseek-v4.1-flash" or candidate.get("max_context") != 65536:
            raise RuntimeError("Fast service reported the wrong model or context")
        engine_log = pathlib.Path(cfg["log"]).read_text(encoding="utf-8", errors="replace")
        if "DSpark: using 78 audited dflash tensor aliases" not in engine_log or "DSpark disabled" in engine_log:
            raise RuntimeError("DSpark did not load")
        models = support.request(support.CANDIDATE, "/v1/models")
        if not any(x.get("id") == "deepseek-v4.1-flash" for x in models.get("data", [])):
            raise RuntimeError("Fast model is missing from /v1/models")
        state.update(phase="candidate_ready")
        support.write_json(state_path, state)
        support.record(log, "candidate_ready", cold_load_seconds=round(time.perf_counter()-started, 3), health=candidate)
        smoke = support.request(support.CANDIDATE, "/v1/messages", {"model": "deepseek-v4.1-flash",
                                "max_tokens": 16, "temperature": 0, "thinking": {"type": "disabled"},
                                "messages": [{"role": "user", "content": "请只回答：3 + 4 = ?"}]}, timeout=300)
        answer = "".join(x.get("text", "") for x in smoke.get("content", []) if x.get("type") == "text").strip()
        if answer != "7" or smoke.get("stop_reason") != "end_turn":
            raise RuntimeError("Fast model failed its startup inference check")
        support.record(log, "startup_inference_ok", usage=smoke.get("usage"))
        support.check_watchdog(watchdog, signal)
        with open(web_log, "w", encoding="utf-8") as out, open(web_err, "w", encoding="utf-8") as err:
            web_proc = subprocess.Popen([node, str(web_script), "--profile", "web", "--no-open",
                                         "--host", "127.0.0.1", "--port", "3081"],
                                        cwd=r"F:\STRATA\harness-workspace", env=env, stdout=out, stderr=err,
                                        creationflags=support.CREATE_NO_WINDOW)
        support.record(log, "fast_web_started", pid=web_proc.pid, port=3081)
        deadline = time.monotonic() + 90
        pattern = re.compile(r"http://127\.0\.0\.1:3081/\?token=[A-Za-z0-9_-]+")
        web_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor()
        )
        while time.monotonic() < deadline:
            support.check_watchdog(watchdog, signal)
            if stop.exists():
                raise InterruptedError("Fast mode was stopped while starting the web app")
            if web_proc.poll() is not None:
                raise RuntimeError("Fast Harness web app exited during startup")
            raw = web_log.read_text(encoding="utf-8", errors="replace") if web_log.exists() else ""
            match = pattern.search(raw)
            if match:
                try:
                    with web_opener.open(match.group(0), timeout=3) as response:
                        if response.status == 200:
                            break
                except Exception:
                    pass
            time.sleep(1)
        else:
            raise TimeoutError("Fast Harness web app did not become ready")
        state.update(web_ready=True)
        support.write_json(state_path, state)
        support.record(log, "fast_ready", port=3081)
        while True:
            support.check_watchdog(watchdog, signal)
            if stop.exists():
                result = "stopped"
                break
            if server_proc.poll() is not None or web_proc.poll() is not None:
                raise RuntimeError("Fast model or web app exited unexpectedly")
            time.sleep(0.7)
    except Exception as exc:
        support.record(log, "fast_stopped", error=str(exc), traceback=traceback.format_exc())
    finally:
        state.update(phase="restoring", web_ready=False)
        support.write_json(state_path, state)
        try:
            support.stop_candidate(state, log)
            restored = support.restore_original(state, log) if state["need_restore"] else True
        except Exception as exc:
            support.record(log, "restore_error", error=str(exc), traceback=traceback.format_exc())
            restored = False
        state.update(phase="done" if restored else "restore_failed", need_restore=not restored, result=result)
        support.write_json(state_path, state)
        support.record(log, "fast_finished", result=result, restored=restored)
    return 0 if result == "stopped" and restored else 1


if __name__ == "__main__":
    try:
        with fast_mutex() as acquired:
            if not acquired:
                raise RuntimeError("Fast mode is already starting or running")
            sys.exit(run())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
