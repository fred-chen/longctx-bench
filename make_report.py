#!/usr/bin/env python3
"""make_report.py — render bench.py results.json into a self-contained report.html"""
import json, sys, datetime

src = sys.argv[1] if len(sys.argv) > 1 else "results.json"
dst = sys.argv[2] if len(sys.argv) > 2 else "report.html"
data = json.load(open(src))

HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>长上下文测试报告 · __MODEL__</title><style>
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--fg:#c9d1d9;--dim:#8b949e;--ok:#3fb950;--bad:#f85149;--warn:#d29922;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:14px;color:var(--acc);margin:26px 0 10px;text-transform:uppercase;letter-spacing:.05em}
.meta{color:var(--dim);font-size:13px}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid var(--border);padding:6px 9px;text-align:left}
th{background:#1c2129;color:var(--dim)}.pass{color:var(--ok);font-weight:700}.fail{color:var(--bad);font-weight:700}.warn{color:var(--warn);font-weight:700}
.hm td{width:70px;height:36px;text-align:center;font-weight:700}.hm .p{background:#12461c;color:#7ee787}.hm .f{background:#5a1e1e;color:#ffa198}.hm .n{color:#30363d}
.badge{display:inline-block;padding:2px 9px;border-radius:10px;font-size:11.5px;font-weight:700;margin:2px 4px 2px 0}
.badge.loop{background:#5a1e1e;color:#ffa198}.badge.caveman{background:#4d3800;color:#e3b341}.badge.rep{background:#3d2b52;color:#d2a8ff}
pre.ans{background:#0a0e14;border:1px solid var(--border);border-radius:6px;padding:10px;font-size:12px;white-space:pre-wrap;max-height:260px;overflow:auto}
.big{font-size:26px;font-weight:800}.kpi{display:flex;gap:26px;flex-wrap:wrap}
.kpi>div{min-width:120px}.kpi .l{color:var(--dim);font-size:12px}
details summary{cursor:pointer;color:var(--dim);font-size:12.5px;margin:6px 0}
</style></head><body><main id="app">加载中…</main>
<script>
const DATA=__DATA__;
const $=(s,p)=>(p||document).querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const K=n=>n>=1024?(n/1024).toFixed(0)+"K":String(n);
const app=$("#app");
const meta=DATA.meta||{},tests=DATA.tests||[];
const deg=tests.filter(t=>t.metrics&&(t.metrics.loop||t.metrics.caveman||t.metrics.repetitive));
const errs=tests.filter(t=>t.error);
const fails=tests.filter(t=>!t.ok&&!t.error);
/* KPI header */
const maxpt=Math.max(0,...tests.map(t=>t.prompt_tokens||0));
app.innerHTML=`<h1>🧵 长上下文测试报告</h1>
<div class="meta">端点 ${esc(meta.base||"")} · 模型 <b>${esc(meta.model||"")}</b> · 开始 ${esc(meta.started||"")} ·
校准 chars/token ${esc(meta.chars_per_token||"?")} · 共 ${tests.length} 用例</div>
<div class="panel kpi">
 <div><div class="big ${fails.length+errs.length?"warn":"pass"}">${tests.length-errs.length-fails.length}/${tests.length}</div><div class="l">通过用例</div></div>
 <div><div class="big">${K(maxpt)}</div><div class="l">实测最大 prompt tokens</div></div>
 <div><div class="big ${deg.length?"fail":"pass"}">${deg.length}</div><div class="l">退化标志响应 (loop/caveman/rep)</div></div>
 <div><div class="big ${errs.length?"fail":"pass"}">${errs.length}</div><div class="l">请求错误 (含超上下文)</div></div>
</div>`;
/* summary by length */
const byL={};tests.forEach(t=>{(byL[t.target_tokens]=byL[t.target_tokens]||[]).push(t);});
let h=`<h2>总览</h2><div class="panel"><table><tr><th>目标长度</th><th>实际 max pt</th><th>T1 单针召回</th><th>T2-T5</th><th>退化</th><th>TTFT 中位</th></tr>`;
for(const L of Object.keys(byL).sort((a,b)=>a-b)){const ts=byL[L];
 const t1=ts.filter(t=>t.task==="T1"),ot=ts.filter(t=>t.task!=="T1");
 const dg=[...new Set(ts.flatMap(t=>["loop","caveman","repetitive"].filter(k=>t.metrics&&t.metrics[k])))];
 const ttfts=t1.map(t=>t.ttft).filter(x=>x!=null).sort((a,b)=>a-b);
 h+=`<tr><td>${K(+L)}t</td><td>${Math.max(...ts.map(t=>t.prompt_tokens||0)).toLocaleString()}</td>
 <td class="${t1.every(t=>t.ok)?"pass":(t1.some(t=>t.ok)?"warn":"fail")}">${t1.filter(t=>t.ok).length}/${t1.length}</td>
 <td class="${ot.every(t=>t.ok)?"pass":(ot.some(t=>t.ok)?"warn":"fail")}">${ot.filter(t=>t.ok).length}/${ot.length}</td>
 <td class="${dg.length?"fail":"pass"}">${dg.join(", ")||"无"}</td>
 <td>${ttfts.length?ttfts[Math.floor(ttfts.length/2)]+"s":"-"}</td></tr>`;}
h+="</table></div>";
/* heatmap */
const lengths=Object.keys(byL).map(Number).sort((a,b)=>a-b);
const ds=[...new Set(tests.filter(t=>t.task==="T1").map(t=>t.depth))].sort((a,b)=>a-b);
h+=`<h2>T1 召回热图（needle 深度 × 上下文长度）</h2><div class="panel"><table class="hm"><tr><th>长度\\\\深度</th>${ds.map(d=>`<th>${d}%</th>`).join("")}</tr>`;
for(const L of lengths){h+=`<tr><td>${K(L)}t</td>`;
 for(const d of ds){const t=tests.find(t=>t.task==="T1"&&t.target_tokens===L&&t.depth===d);
  h+=t?`<td class="${t.ok?"p":"f"}" title="${esc(t.answer||t.error||"")}">${t.ok?"✓":"✗"}</td>`:`<td class="n">·</td>`;}
 h+="</tr>";}
h+="</table><div class='meta'>深度 = needle 在上下文中的相对位置（0% 开头，100% 结尾；中间位置最易漏检 = lost-in-the-middle）</div></div>";
/* degeneration */
h+=`<h2>行为退化检测</h2><div class="panel">`;
h+=deg.length?`<b style="color:var(--bad)">⚠ ${deg.length} 个响应触发标志：</b>`:`<b style="color:var(--ok)">✓ 全部响应未触发 loop / caveman / repetitive 标志</b>`;
h+=`<div style="margin:8px 0">${deg.map(t=>`${t.task}@${K(t.target_tokens)}t d${t.depth} <span class="badge loop">${t.metrics.loop?"LOOP×"+t.metrics.max10gram_repeat:""}</span><span class="badge caveman">${t.metrics.caveman?"CAVEMAN fw="+t.metrics.function_word_ratio:""}</span><span class="badge rep">${t.metrics.repetitive?"REP d2="+t.metrics.distinct2:""}</span>`).filter(Boolean).join("")}</div>`;
h+=`<table><tr><th>用例</th><th>词数</th><th>function-word 比<br><span style="font-weight:400">(&lt;0.30 疑似 caveman)</span></th><th>distinct-2<br><span style="font-weight:400">(&lt;0.60 重复度高)</span></th><th>10-gram 最大重复<br><span style="font-weight:400">(≥3 判 loop)</span></th><th>平均句长</th></tr>`;
tests.filter(t=>t.metrics&&t.metrics.words>40).forEach(t=>{const m=t.metrics;
 h+=`<tr><td>${t.task}@${K(t.target_tokens)} d${t.depth}</td><td>${m.words}</td>
 <td class="${m.caveman?"fail":""}">${m.function_word_ratio??"-"}</td>
 <td class="${m.repetitive?"fail":""}">${m.distinct2??"-"}</td>
 <td class="${m.loop?"fail":""}">${m.max10gram_repeat}</td><td>${m.avg_words_per_sentence??"-"}</td></tr>`;});
h+="</table></div>";
/* details */
h+=`<h2>全部用例明细</h2><div class="panel"><table><tr><th>#</th><th>任务</th><th>长度</th><th>深</th><th>结果</th><th>pt</th><th>ttft</th><th>耗时</th><th>备注/错误</th></tr>`;
tests.forEach((t,i)=>{
 h+=`<tr><td>${i}</td><td>${t.task}</td><td>${K(t.target_tokens)}</td><td>${t.depth}</td>
 <td class="${t.error?"fail":(t.ok?"pass":"fail")}">${t.error?"ERR":(t.ok?"PASS":"FAIL")}</td>
 <td>${t.prompt_tokens??"-"}</td><td>${t.ttft??"-"}</td><td>${t.elapsed}s</td><td>${esc(t.note||"")}${t.error?" "+esc(String(t.error).slice(0,160)):""}</td></tr>
 <tr><td colspan="9"><details><summary>预期 ${esc(String(t.expect||""))} → 模型回答</summary><pre class="ans">${esc(t.answer||"(无正文，可能被思考截断)")}</pre></details></td></tr>`;});
h+="</table></div>";
app.innerHTML+=h;
</script></main></body></html>"""

out = HTML.replace("__MODEL__", data.get("meta", {}).get("model", ""))
out = out.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str))
open(dst, "w", encoding="utf-8").write(out)
print(f"wrote {dst} ({len(out)/1024:.0f} KB, {len(data.get('tests', []))} tests)")
