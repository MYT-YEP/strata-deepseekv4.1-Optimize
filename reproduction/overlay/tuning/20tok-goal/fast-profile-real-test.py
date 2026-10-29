"""Exercise the separate fast Harness profile with a read-only real tool call."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid

root = Path(r"F:\STRATA\tuning\20tok-goal")
workspace = Path(r"F:\STRATA\harness-workspace")
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with http.open("http://127.0.0.1:8150/health", timeout=5) as response:
    health = json.load(response)
if not health.get("loaded") or health.get("model") != "deepseek-v4.1-flash":
    raise SystemExit("The expected candidate model is not ready")
with http.open("http://127.0.0.1:8150/status", timeout=5) as response:
    status = json.load(response)
if status.get("busy") or status.get("queued"):
    raise SystemExit("The candidate model is busy; no test was started")
tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
prefix = root / ("fast-profile-real-" + tag)
fixture_dir = workspace / "20tok-tests"
fixture_dir.mkdir(parents=True, exist_ok=True)
nonce = "STRATA_" + uuid.uuid4().hex
fixture = fixture_dir / ("fast-nonce-" + tag + ".txt")
fixture.write_text(nonce + "\n", encoding="utf-8")
events_path = Path(str(prefix) + "-events.jsonl")
metrics_path = Path(str(prefix) + "-metrics.json")
err_path = Path(str(prefix) + "-stderr.log")
env = os.environ.copy()
env.update(DSH_PERMISSION_MODE="read-only", HARNESS_BENCH_OUTPUT=str(metrics_path),
           TEMP=r"F:\STRATA\tmp", TMP=r"F:\STRATA\tmp")
task = "请使用文件读取工具读取 " + str(fixture) + "，仅回复文件中的验证码，不执行其他操作。"
started = time.perf_counter()
with events_path.open("w", encoding="utf-8") as events, err_path.open("w", encoding="utf-8") as errors:
    process = subprocess.run([r"F:\STRATA\toolchains\node-24.14.0\node.exe", str(root / "bench-fast-profile.cjs"), "--profile", "headless",
                              "--patch", str(root / "xolotl-harness-overlay.yml"), "--json", task],
                             cwd=workspace, env=env, stdout=events, stderr=errors,
                             timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
elapsed = time.perf_counter() - started
events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
calls = [e for e in events if e.get("type") == "tool_call"]
results = [e for e in events if e.get("type") == "tool_result"]
texts = [e.get("text", "") for e in events if e.get("type") in ("text", "final")]
metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
requests = metrics.get("requests", [])
passed = (process.returncode == 0 and any(x.get("tool") == "read" for x in calls)
          and any(x.get("status") == "completed" for x in results)
          and any(nonce in t for t in texts) and bool(requests)
          and all(x.get("maxTokens") == 16384 for x in requests))
result = {"passed": passed, "return_code": process.returncode, "elapsed_seconds": round(elapsed, 3),
          "model": health.get("model"), "fixture": str(fixture), "read_calls": sum(x.get("tool") == "read" for x in calls),
          "completed_tool_results": sum(x.get("status") == "completed" for x in results),
          "answer_contains_nonce": any(nonce in t for t in texts), "requests": requests}
Path(str(prefix) + "-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"result_file": str(prefix) + "-check.json", **result}, ensure_ascii=False), flush=True)
raise SystemExit(0 if passed else 1)
