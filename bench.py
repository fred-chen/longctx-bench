#!/usr/bin/env python3
"""
longctx-bench — long-context recall / retrieval / behaviour-degeneration harness
================================================================================
Methodology: Needle-In-A-Haystack (gkamradt/LLMTest_NeedleInAHaystack style),
extended with multi-needle retrieval, multi-hop tracing, counting, and a
long-generation task instrumented for degeneration detection:

  T1 NIAH single-needle grid   -> recall heatmap over (context_length x depth)
  T2 MULTI   5 needles         -> multi-retrieval recall / precision
  T3 MULTIHOP 3-hop fact chain -> reasoning over dispersed facts
  T4 COUNT   phrase repeated N -> counting / aggregation
  T5 REPORT  force 350-500w    -> loop detection (repeated 10-grams, distinct-2)
                                  caveman-speak detection (function-word ratio)
Every response's text is also analysed with the same degeneration detectors.

Stdlib only. OpenAI-compatible endpoint.   Python 3.8+

Usage:
  python3 bench.py --base http://ai4090:8080/v1 --model Qwen3.8-Flash-Next \
      --lengths 131072,262144,327680 --out results.json [--quick]
"""
import argparse, json, re, sys, time, uuid, random
from collections import Counter
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------- corpus
def load_corpus(corpus_dir, maxlen_chars):
    import os, glob
    parts = []
    total = 0
    files = sorted(glob.glob(os.path.join(corpus_dir, "*.txt")))
    if not files:
        raise SystemExit(f"no corpus .txt files in {corpus_dir}")
    while total < maxlen_chars:          # cycle if not enough material
        for f in files:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                t = fh.read()
            t = re.sub(r"\s+", " ", t)   # flatten to prose so depth% is uniform
            parts.append(t); total += len(t)
            if total >= maxlen_chars:
                break
    return "\n\n".join(parts)[:maxlen_chars]

# ---------------------------------------------------------------- api client
class API:
    def __init__(self, base, model, key=None, timeout=300, think=None):
        self.base = base.rstrip("/"); self.model = model
        self.key = key; self.timeout = timeout; self.think = think
        self.n_calls = 0

    def chat(self, messages, max_tokens=512, stream=True):
        res = None
        for attempt in range(3):
            try:
                res = self._chat_once(messages, max_tokens, stream)
            except Exception as e:
                res = {"error": f"{type(e).__name__}: {e}", "content": "", "reasoning": "",
                       "elapsed": 0, "ttft": None, "usage": None, "finish": None}
            err = str(res.get("error") or "").lower()
            if (not res["error"] or attempt == 2 or any(
                    s in err for s in ("maximum context", "exceeds", "too long",
                                       "context length", "out of range"))):
                return res
            sys.stderr.write(f"[retry] call#{self.n_calls} attempt {attempt+1} failed: {err[:140]}\n")
            sys.stderr.flush(); time.sleep(4 * (attempt + 1))
        return res

    def _chat_once(self, messages, max_tokens, stream):
        payload = {
            "model": self.model, "messages": messages,
            "temperature": 0.0, "max_tokens": max_tokens, "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if self.think is False:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        elif self.think is True:
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        req = urlreq.Request(self.base + "/chat/completions",
                             data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json",
                                      **({"Authorization": f"Bearer {self.key}"} if self.key else {})})
        self.n_calls += 1
        t0 = time.time(); ttft = None
        content, reasoning, usage, finish = [], [], None, None
        try:
            resp = urlreq.urlopen(req, timeout=self.timeout)
        except HTTPError as e:
            body = e.read().decode(errors="ignore")[:400]
            return {"error": f"HTTP {e.code}: {body}", "content": "", "reasoning": "",
                    "elapsed": time.time() - t0, "ttft": None, "usage": None, "finish": None}
        except URLError as e:
            return {"error": f"URLError: {e.reason}", "content": "", "reasoning": "",
                    "elapsed": time.time() - t0, "ttft": None, "usage": None, "finish": None}
        with resp:
            if not stream:
                d = json.loads(resp.read().decode())
                ch = d["choices"][0]; usage = d.get("usage")
                return {"content": ch["message"].get("content") or "",
                        "reasoning": ch["message"].get("reasoning_content") or "",
                        "elapsed": time.time() - t0, "ttft": None, "usage": usage,
                        "finish": ch.get("finish_reason"), "error": None}
            buf = b""
            for raw in resp:
                buf += raw
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        # non-SSE error body (some servers answer 200 + json error)
                        if line.startswith(b"{") and b'"error"' in line:
                            try: return {"error": json.loads(line)["error"], "content": "",
                                         "reasoning": "", "elapsed": time.time()-t0, "ttft": None,
                                         "usage": None, "finish": None}
                            except Exception: pass
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        break
                    try: d = json.loads(data)
                    except Exception: continue
                    if d.get("error"):
                        return {"error": d["error"], "content": "", "reasoning": "",
                                "elapsed": time.time()-t0, "ttft": None, "usage": None, "finish": None}
                    if d.get("usage"): usage = d["usage"]
                    for ch in d.get("choices") or []:
                        if ch.get("finish_reason"): finish = ch["finish_reason"]
                        dl = ch.get("delta") or {}
                        c = dl.get("content"); r = dl.get("reasoning_content")
                        if c:
                            if ttft is None: ttft = time.time() - t0
                            content.append(c)
                        if r:
                            if ttft is None: ttft = time.time() - t0
                            reasoning.append(r)
        return {"content": "".join(content), "reasoning": "".join(reasoning),
                "elapsed": time.time() - t0, "ttft": ttft, "usage": usage,
                "finish": finish, "error": None}

# ---------------------------------------------------------------- degeneration metrics
FUNC_WORDS = set("""a an the and or but if then than that this these those of in on at to for from by with
without within into onto about above below under over between during while as is are was were be been being am
do does did done have has had having will would shall should can could may might must not no nor so yet both
either each every all any some few more most other another such own same it its he she they him her them his
hers theirs our your my me we us you i who whom which what when where how why all's there here too very just
also than once upon per via one two three""".split())

def analyze_text(text):
    """Degeneration metrics + heuristic flags for one response."""
    words = re.findall(r"[A-Za-z'’]+", text.lower())
    n = len(words)
    out = {"words": n}
    if n < 5:
        out.update(distinct2=None, max10gram_repeat=0, function_word_ratio=None,
                   avg_words_per_sentence=None, loop=False, caveman=False, repetitive=False)
        return out
    bigrams = zip(words, words[1:])
    out["distinct2"] = round(len(set(bigrams)) / max(1, n - 1), 3)
    c = Counter(tuple(words[i:i+10]) for i in range(max(0, n - 9)))
    out["max10gram_repeat"] = max(c.values()) if c else 0
    out["function_word_ratio"] = round(sum(1 for w in words if w in FUNC_WORDS) / n, 3)
    sents = [s for s in re.split(r"[.!?\n]+", text) if s.strip()]
    out["avg_words_per_sentence"] = round(n / max(1, len(sents)), 1)
    out["loop"] = out["max10gram_repeat"] >= 3
    out["repetitive"] = out["distinct2"] < 0.60 and n > 150
    out["caveman"] = n > 80 and out["function_word_ratio"] < 0.30 \
        and out["avg_words_per_sentence"] < 10
    return out

# ---------------------------------------------------------------- context builder
def build_context(corpus, chars, inserts):
    """inserts: list of (depth_pct 0..100, needle_text). Returns context string."""
    base = corpus[:chars]
    marks = []
    for depth, text in inserts:
        pos = int(len(base) * depth / 100.0)
        # snap to a paragraph/sentence boundary near pos
        cut = base.rfind(". ", max(0, pos - 2000), min(len(base), pos + 2000))
        if cut < 0: cut = pos
        marks.append((min(cut + 2, len(base)), text))
    marks.sort()
    parts, prev = [], 0
    for pos, text in marks:
        parts.append(base[prev:pos]); parts.append(f"\n\n>>> {text} <<<\n\n"); prev = pos
    parts.append(base[prev:])
    return "".join(parts)

QBOX = ("\n\n--- END OF DOCUMENT ---\n"
        "Answer the following question using ONLY the document above. "
        "Be concise and give the exact answer.\nQuestion: {q}\nAnswer:")

# ---------------------------------------------------------------- tasks
def task_niah(corpus, tokens, cpc, depth, rng):
    code = uuid.uuid4().hex[:8].upper()
    proj = rng.choice(["ARGONAUT", "HOLLOWAY", "LANTERN", "MERIDIAN", "NIGHTJAR", "OBSIDIAN"])
    needle = (f"The lighthouse keeper recorded in his log that the launch code "
              f"for Project {proj} was {code}.")
    ctx = build_context(corpus, int(tokens * cpc), [(depth, needle)])
    q = (f"According to the lighthouse keeper's log, what was the launch code "
         f"for Project {proj}? Reply with only the 8-character code.")
    return ctx, q, {"expect": code, "check": lambda a: code in a.upper()}

def task_multi(corpus, tokens, cpc, rng, n=5):
    rng_ = [10, 30, 50, 70, 90][:n]
    projs = rng.sample(["ARGONAUT", "HOLLOWAY", "LANTERN", "MERIDIAN", "NIGHTJAR",
                        "OBSIDIAN", "PYXIS", "QUARRY"], n)
    codes = [uuid.uuid4().hex[:8].upper() for _ in range(n)]
    inserts = [(d, f"The lighthouse keeper recorded in his log that the launch code "
               f"for Project {p} was {c}.")
               for d, p, c in zip(rng_, projs, codes)]
    ctx = build_context(corpus, int(tokens * cpc), inserts)
    q = ("List the launch code of every project mentioned in the document, one per line, "
         "in the format PROJECT: CODE")
    def check(a):
        up = a.upper()
        got = sum(1 for c in codes if c in up)
        return got == n, f"found {got}/{n}"
    return ctx, q, {"expect": dict(zip(projs, codes)), "check_multi": check}

def task_multihop(corpus, tokens, cpc, rng):
    hops = [
        "The Mayor hid the golden key inside the old lighthouse.",
        "The old lighthouse was torn down and its contents moved to the Maritime Museum.",
        "The Maritime Museum later relocated its entire collection to the Rivergate Warehouse.",
    ]
    inserts = [(d, h) for d, h in zip([15, 45, 75], hops)]
    ctx = build_context(corpus, int(tokens * cpc), inserts)
    q = ("According to the document, where is the golden key NOW? "
         "Reply with the name of the current location only.")
    return ctx, q, {"expect": "Rivergate Warehouse",
                    "check": lambda a: "rivergate" in a.lower()}

def task_count(corpus, tokens, cpc, rng, n=7):
    marker = f"zephyr-{uuid.uuid4().hex[:4]}"
    depths = rng.sample(range(5, 96), n)
    inserts = [(d, f"Editor's note: the passphrase token {marker} appears here.")
               for d in depths]
    ctx = build_context(corpus, int(tokens * cpc), inserts)
    q = f"How many times does the exact token '{marker}' appear in the document? Reply with a single number."
    def check(a):
        m = re.findall(r"\b(\d+)\b", a)
        return bool(m) and int(m[-1]) == n, f"answered {m[-1] if m else '?'} expected {n}"
    return ctx, q, {"expect": n, "check_num": check}

def task_report(corpus, tokens, cpc, rng):
    """Force a long generation to amplify degeneration (loops / caveman speech)."""
    codes = [uuid.uuid4().hex[:8].upper() for _ in range(3)]
    projs = ["ALBATROSS", "BEACON", "CINDER"]
    inserts = [(d, f"The lighthouse keeper recorded in his log that the launch code "
               f"for Project {p} was {c}.")
               for d, p, c in zip([20, 50, 80], projs, codes)]
    ctx = build_context(corpus, int(tokens * cpc), inserts)
    q = ("You are a security auditor. First list each Project mentioned in the document "
         "with its launch code. Then, continuing in the same response, write a detailed "
         "analytical essay of at least 350 words on how long documents should be audited "
         "for leaked secrets, covering detection methods, prioritisation, reporting and "
         "remediation. Do not stop early.")
    def check(a):
        up = a.upper()
        got = sum(1 for c in codes if c in up)
        return got >= 2, f"codes {got}/3 in essay"
    return ctx, q, {"expect": dict(zip(projs, codes)), "check_multi": check}

# ---------------------------------------------------------------- scoring
def run_task(api, ctx, q, spec, max_tokens):
    messages = [{"role": "user", "content": ctx + QBOX.format(q=q)}]
    r = api.chat(messages, max_tokens=max_tokens)
    ans = r["content"] or r["reasoning"]
    res = {"ok": False, "note": "", "answer": (r["content"] or "")[:600],
           "elapsed": round(r["elapsed"], 1), "ttft": round(r["ttft"], 1) if r.get("ttft") else None,
           "prompt_tokens": (r.get("usage") or {}).get("prompt_tokens"),
           "completion_tokens": (r.get("usage") or {}).get("completion_tokens"),
           "finish": r.get("finish"), "error": r.get("error"),
           "metrics": analyze_text(r["content"] or "")}
    if r["error"]:
        res["note"] = str(r["error"])[:200]
        return res
    if "check" in spec:
        res["ok"] = bool(spec["check"](ans))
    elif "check_multi" in spec:
        res["ok"], res["note"] = spec["check_multi"](ans)
    elif "check_num" in spec:
        res["ok"], res["note"] = spec["check_num"](ans)
    if r.get("finish") == "length":
        res["note"] = (res["note"] + " | " if res["note"] else "") + "TRUNCATED(max_tokens)"
    return res

# ---------------------------------------------------------------- calibration
def calibrate(api, corpus):
    sample = corpus[:20000]
    r = api.chat([{"role": "user", "content": sample + "\n\nReply OK."}],
                 max_tokens=16, stream=False)
    pt = (r.get("usage") or {}).get("prompt_tokens")
    if pt:
        return len(sample) / pt, pt
    return 3.8, None

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://ai4090:8080/v1")
    ap.add_argument("--model", default="Qwen3.8-Flash-Next")
    ap.add_argument("--key", default=None)
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--lengths", default="131072,262144,327680",
                    help="comma-separated TARGET token counts")
    ap.add_argument("--depths", default="0,25,50,75,100")
    ap.add_argument("--quick", action="store_true", help="fewer depths/tests")
    ap.add_argument("--think-mode", choices=["off", "on", "default"], default="off")
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--report", default="report.html")
    args = ap.parse_args()

    lengths = [int(x) for x in args.lengths.split(",") if x.strip()]
    depths = [int(x) for x in args.depths.split(",") if x.strip()]
    if args.quick:
        depths = [d for d in depths if d in (0, 50, 100)]

    api = API(args.base, args.model, args.key, think={"off": False, "on": True, "default": None}[args.think_mode])
    corpus = load_corpus(args.corpus, int(max(lengths) * 5.0))
    rng = random.Random(42)

    cpc, raw = calibrate(api, corpus)
    print(f"[calib] corpus chars/token = {cpc:.2f} "
          f"(20k chars -> {raw} prompt tokens); server model={args.model}")

    results = {"meta": {"base": args.base, "model": args.model,
                        "chars_per_token": round(cpc, 3),
                        "target_lengths": lengths, "depths": depths,
                        "started": time.strftime("%Y-%m-%d %H:%M:%S")},
               "tests": []}

    def do(name, length, depth, builder, max_tokens):
        nonlocal cpc
        spec = builder(corpus, length, cpc, rng) if name != "T1" else \
               task_niah(corpus, length, cpc, depth, rng)
        ctx, q, checks = spec
        print(f"[run ] {name} len={length} depth={depth} ctx_chars={len(ctx)} ... ",
              end="", flush=True)
        res = run_task(api, ctx, q, checks, max_tokens)
        res.update({"task": name, "target_tokens": length, "depth": depth,
                    "question": q})
        if res.get("prompt_tokens") and res["prompt_tokens"] < 0.985 * length:
            # context came in under target -> recalibrate once and redo
            cpc = cpc * (length / res["prompt_tokens"]) * 1.01
            results["meta"]["chars_per_token"] = round(cpc, 3)
            print(f"short({res['prompt_tokens']}t) recal cpc={cpc:.2f}, retry ",
                  end="", flush=True)
            spec = builder(corpus, length, cpc, rng) if name != "T1" else \
                   task_niah(corpus, length, cpc, depth, rng)
            ctx, q, checks = spec
            res = run_task(api, ctx, q, checks, max_tokens)
            res.update({"task": name, "target_tokens": length, "depth": depth,
                        "question": q})
        flag = "PASS" if res["ok"] else "FAIL"
        deg = [k for k in ("loop", "caveman", "repetitive") if res["metrics"].get(k)]
        print(f"{flag} {res['elapsed']}s pt={res.get('prompt_tokens')} "
              f"{'DEGEN:'+'/'.join(deg) if deg else ''} {res['note']}")
        results["tests"].append(res)
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1, ensure_ascii=False, default=str)
        return res

    def _ctx_err(r):
        e = str(r.get("error") or "").lower()
        return bool(r.get("error")) and any(s in e for s in
            ("maximum context", "exceeds", "too long", "context length", "out of range"))

    for L in lengths:
        skip = False
        for d in depths:
            if skip:
                break
            skip = _ctx_err(do("T1", L, d, None, 768))
        if skip:
            continue
        for nm, bld, mt in (("T2", task_multi, 1024), ("T3", task_multihop, 768),
                            ("T4", task_count, 768), ("T5", task_report, 2600)):
            if _ctx_err(do(nm, L, -1, bld, mt)):
                break

    # summary
    tests = results["tests"]
    by_task = {}
    for t in tests:
        by_task.setdefault((t["target_tokens"], t["task"]), []).append(t)
    summary = {}
    for L in lengths:
        t1 = [t for t in tests if t["task"] == "T1" and t["target_tokens"] == L]
        others = [t for t in tests if t["task"] != "T1" and t["target_tokens"] == L]
        summary[str(L)] = {
            "niah_pass": f"{sum(1 for t in t1 if t['ok'])}/{len(t1)}",
            "tasks_pass": f"{sum(1 for t in others if t['ok'])}/{len(others)}",
            "degen_flags": sorted({k for t in t1 + others
                                   for k in ("loop", "caveman", "repetitive")
                                   if t["metrics"].get(k)}),
            "max_pt": max((t.get("prompt_tokens") or 0) for t in t1 + others) or None,
        }
    results["summary"] = summary
    with open(args.out, "w") as f:
        json.dump(results, f, indent=1, ensure_ascii=False, default=str)
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=1))
    print(f"[done] {api.n_calls} calls -> {args.out}")

if __name__ == "__main__":
    main()
