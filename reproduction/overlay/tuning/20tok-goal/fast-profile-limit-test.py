"""Measure whether one real Harness request can reach its configured 16K limit."""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

root = Path(r"F:\STRATA\tuning\20tok-goal")
workspace = Path(r"F:\STRATA\harness-workspace")
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with http.open("http://127.0.0.1:8150/health", timeout=5) as response:
    health = json.load(response)
with http.open("http://127.0.0.1:8150/status", timeout=5) as response:
    status = json.load(response)
if not health.get("loaded") or health.get("model") != "deepseek-v4.1-flash" or status.get("busy") or status.get("queued"):
    raise SystemExit("The candidate model is not ready or is busy; no test was started")
tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
prefix = root / ("fast-profile-limit-" + tag)
events_path = Path(str(prefix) + "-events.jsonl")
metrics_path = Path(str(prefix) + "-metrics.json")
err_path = Path(str(prefix) + "-stderr.log")
env = os.environ.copy()
env.update(DSH_PERMISSION_MODE="read-only", HARNESS_BENCH_OUTPUT=str(metrics_path),
           TEMP=r"F:\STRATA\tmp", TMP=r"F:\STRATA\tmp")
task = ("这是本地模型长输出上限的自动化验证。请直接输出从001到700的700行，不要调用工具，"
        "不要代码块，不要摘要或省略，不要说后续相同。每行格式严格如下，仅递增开头的三位编号：\n"
        "001 | Reliable local generation preserves the full conversation, streams each answer progressively, "
        "and completes every requested section without early truncation.\n"
        "完成第700行之后，在最后一行单独写 LONG_OUTPUT_COMPLETE。")
started = time.perf_counter()
with events_path.open("w", encoding="utf-8") as events, err_path.open("w", encoding="utf-8") as errors:
    process = subprocess.run([r"F:\STRATA\toolchains\node-24.14.0\node.exe", str(root / "bench-fast-profile.cjs"), "--profile", "headless",
                              "--patch", str(root / "xolotl-harness-overlay.yml"), "--json", task],
                             cwd=workspace, env=env, stdout=events, stderr=errors,
                             timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
elapsed = time.perf_counter() - started
events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
requests = metrics.get("requests", [])
usage = [(e.get("usage") or {}).get("outputTokens", 0) for e in events
         if e.get("type") == "status" and e.get("phase") == "step_end"]
finals = [e.get("text", "") for e in events if e.get("type") == "final"]
text = finals[-1] if finals else ""
numbers = [int(x) for x in re.findall(r"(?m)^(\d{3})\s*\|", text)]
turn_end_reasons = [e.get("reason") for e in events if e.get("type") == "status" and e.get("phase") == "turn_end"]
# Harness exits nonzero when the requested limit stops a turn. That is the
# expected outcome for this deliberately overlong prompt, not a runtime crash.
passed = (bool(requests) and requests[0].get("maxTokens") == 16384
          and bool(usage) and usage[0] == 16384 and requests[0].get("stopReason") == "max_tokens"
          and any(reason.get("kind") == "max-tokens" for reason in turn_end_reasons if isinstance(reason, dict)))
result = {"passed": passed, "return_code": process.returncode, "elapsed_seconds": round(elapsed, 3),
          "requested_max_tokens": requests[0].get("maxTokens") if requests else None,
          "output_tokens_per_step": usage, "requests": requests, "numbered_lines": len(numbers),
          "numbers_contiguous_from_one": numbers == list(range(1, len(numbers) + 1)),
          "has_end_marker": "LONG_OUTPUT_COMPLETE" in text,
          "tool_calls": sum(e.get("type") == "tool_call" for e in events),
          "turn_end_reasons": turn_end_reasons}
Path(str(prefix) + "-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"result_file": str(prefix) + "-check.json", **result}, ensure_ascii=False), flush=True)
raise SystemExit(0 if passed else 1)
