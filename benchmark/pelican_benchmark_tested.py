"""Run the original one-prompt Pelican SVG test against the local fast API."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8150"
ORIGINAL = "http://127.0.0.1:8080"
PROMPT = "Generate an SVG of a pelican riding a bicycle"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ROOT = Path(r"F:\STRATA")


def get(base, path):
    with HTTP.open(base + path, timeout=8) as response:
        return json.load(response)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    if output.exists(): raise SystemExit("Output exists; refusing to overwrite.")
    output.parent.mkdir(parents=True, exist_ok=True)
    health = get(BASE, "/health")
    models = get(BASE, "/v1/models")
    status = get(BASE, "/status")
    original_status = get(ORIGINAL, "/status")
    if (not health.get("loaded") or health.get("model") != "deepseek-v4.1-flash"
            or health.get("max_context") != 65536
            or not any(x.get("id") == "deepseek-v4.1-flash" and x.get("status", {}).get("value") == "loaded"
                       for x in models.get("data", []))):
        raise SystemExit("Expected fast model with 64K context is not loaded.")
    if any(s.get("busy") or s.get("queued") for s in (status, original_status)):
        raise SystemExit("An inference is active or queued; benchmark did not start.")
    meta = json.loads((ROOT / "tuning/20tok-goal/fast-mode.json").read_text(encoding="utf-8-sig"))
    state = json.loads(Path(meta["state"]).read_text(encoding="utf-8-sig"))
    if state.get("phase") != "candidate_ready" or not state.get("web_ready"):
        raise SystemExit("Fast service is not in the expected ready state.")
    config_file = Path(state["config"])
    cfg = json.loads(config_file.read_text(encoding="utf-8-sig"))
    cfg_args = cfg.get("args", [])
    rank_file = ROOT / "tuning/20tok-goal/strata-profile-xolotl-rank.bin"
    def arg_value(flag):
        return cfg_args[cfg_args.index(flag) + 1] if flag in cfg_args and cfg_args.index(flag) + 1 < len(cfg_args) else None
    expected_args = {"--ctx": "65536", "--arena-gib": "48", "--route-bias": "0.75",
                     "--route-bias-file": "0.45", "--prompt-batch": "8192"}
    expected_env = {"STRATA_TIER_BATCH_PCIE": "1.0", "STRATA_DSPARK_DEPTH": "4",
                    "STRATA_DSPARK_CONF": "0.6", "STRATA_DSPARK_EXP_TYPE": "q2_K"}
    if (cfg.get("model_name") != "deepseek-v4.1-flash"
            or any(arg_value(k) != v for k, v in expected_args.items())
            or any(cfg.get("env", {}).get(k) != v for k, v in expected_env.items())
            or not arg_value("--rank") or Path(arg_value("--rank")) != rank_file
            or sha(rank_file) != "e99e03a965212259daeb8f3e505381e0b16291acc010db3c49d46a2e27b7fd88"
            or sha(Path(cfg["exe"])) != "47b45084419dbcb8299acf0b13d6f12ea20deb02c7639eb66bddee94be023791"):
        raise SystemExit("The live config does not match the selected default.")
    payload = {"model": "deepseek-v4.1-flash", "messages": [{"role": "user", "content": PROMPT}],
               "temperature": 0, "reasoning_effort": "none", "stream": True, "max_tokens": 16384}
    result = {"benchmark": "Simon Willison pelican SVG, one-shot, unedited", "prompt": PROMPT,
              "source": "https://simonwillison.net/2024/Oct/25/pelicans-on-a-bicycle/",
              "started_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
              "service_health": health, "request": payload,
              "hardware_note": "See the accompanying machine and configuration report.",
              "configuration": {"model_quantization": "ISTA-DASLab 2.25 bpw IQ2_XS", "pcie": "1.0",
                                "engine_sha256": sha(Path(cfg["exe"])), "expert_rank_sha256": sha(rank_file),
                                "context": 65536, "expert_cache_gib": 48, "route_bias": 0.75,
                                "route_bias_file": 0.45, "dspark_depth": 4, "dspark_confidence": 0.6},
              "answer": "", "stream_completed": False}
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    started = time.perf_counter(); first = None; last_check = started; chunks = []
    finish = usage = timings = None; error = None
    print("Pelican request started on the selected local service.", flush=True)
    try:
        with HTTP.open(req, timeout=900) as response:
            for raw in response:
                now = time.perf_counter()
                if now - last_check >= 2:
                    last_check = now
                    if get(BASE, "/status").get("queued", 0):
                        raise InterruptedError("Another request is queued; benchmark stopped to yield.")
                line = raw.decode("utf-8", errors="strict").strip()
                if not line.startswith("data:"): continue
                content = line[5:].strip()
                if content == "[DONE]":
                    result["stream_completed"] = True
                    break
                event = json.loads(content)
                choices = event.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content") or ""
                    if piece and first is None: first = now - started
                    chunks.append(piece)
                    if choices[0].get("finish_reason") is not None: finish = choices[0]["finish_reason"]
                usage = event.get("usage") or usage
                timings = event.get("timings") or timings
    except Exception as exc:
        error = str(exc)
    elapsed = time.perf_counter() - started
    result.update(answer="".join(chunks), finish_reason=finish, usage=usage, timings=timings,
                  elapsed_seconds=round(elapsed, 3), first_text_seconds=round(first, 3) if first is not None else None,
                  finished_at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(), error=error)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(output), "stream_completed": result["stream_completed"],
                      "finish_reason": finish, "usage": usage, "timings": timings,
                      "elapsed_seconds": result["elapsed_seconds"], "first_text_seconds": result["first_text_seconds"],
                      "error": error}, ensure_ascii=False), flush=True)
    return 0 if result["stream_completed"] and result["answer"] and not error else 1


if __name__ == "__main__": sys.exit(main())
