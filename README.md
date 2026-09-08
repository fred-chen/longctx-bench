# longctx-bench · standalone

**单文件**长上下文测试控制台：召回（NIAH 热图）/ 多路检索 / 多跳推理 / 计数聚合 / 行为退化（loop · caveman-speak）。
整个项目只有一个 `standalone.html`——无后端、无语料文件，打开即用。

```
项目结构：standalone.html + README.md（就这两个）
```

## 使用

浏览器直接打开 `standalone.html` 即可（`file://` 或任意静态服务器都行）。

1. **Endpoint**：填 OpenAI 兼容地址（含 `/v1`）与模型 ID
2. **语料**：默认"内置完整语料"——534 万字符 Gutenberg 公版书，gzip+base64 内嵌在 HTML 里，
   首次加载在浏览器内用 `DecompressionStream` 解压（1~2 秒）。也可换成
   本地 txt 文件（多选）或粘贴文本，或 40KB 冒烟小语料
3. **测试项**：T1 NIAH 网格（长度 × 深度热图）、T2 五针全召回、T3 三跳事实链、
   T4 计数 ×7、T5 强制长文（退化探针）。建议先用 8192 冒烟一次
4. 结果区：通过概览、召回热图、退化指标、明细（可展开看模型原文）、JSON 导出

### CORS 要求（唯一前置条件）

页面从浏览器**直连**推理端点，端点必须带 CORS 响应头：

| 服务端 | 开启方式 |
|---|---|
| vLLM | `--allow-origins '*'` |
| llama.cpp server | `--origins '*'` |
| OpenAI 官方 API | 本身即支持 |

页面在 CORS 失败时会给出上述提示。若端点在你控制之外无法加头，请退回用
`serve.py` 代理的完整版（见仓库 git 历史 `HEAD~1` 之前，或重新 checkout）。

## 测试项与判定

| 任务 | 方法 | 目的 |
|---|---|---|
| T1 单针网格 | 随机码针插在 长度×深度 各组合，问码 | 基础召回；lost-in-the-middle；有效上下文边界 |
| T2 五针 | 5 针分散 10~90% 深度，要求全列出 | 多目标检索广度 |
| T3 三跳链 | 三句事实分散三处，需串联推理 | 跨距离信息组合（检索之外的推理） |
| T4 计数 | 随机短语插 7 次，问次数 | 全局扫描；验证注意力是否贯穿全文 |
| T5 长文 | 列针 + 强制 ≥350 词长文 | 退化探针：放大 loop/caveman 信号 |

退化指标（对每条响应计算）：

| 指标 | 含义 | 告警线 |
|---|---|---|
| `max10gram_repeat` | 同一 10 词短语重复次数 | ≥3 → **LOOP** |
| `function_word_ratio` | 虚词（the/of/and…）占比，正常英语 0.40~0.55 | <0.30 且句长 <10 → **CAVEMAN** |
| `distinct2` | 二元词组多样性（复读度） | <0.60 且 >150 词 → **REPETITIVE** |

针采用叙事体（"灯塔管理员在日志里记下了 Project X 的码…"），避免安全训练强的模型
把它当成 prompt injection 拒答；语料已剥离 Gutenberg 版权头，避免 0% 深度的针落进
样板文字被当元数据跳过。

## 已知行为说明

- `tok/s` 列 = completion tokens ÷ 总耗时（含 prefill），不是解码速度；ttft 才是首 token 延迟
- 思考模型默认发 `enable_thinking:false`（思考会吃光 max_tokens 造成假失败）；
  不支持该参数的服务端选"不干预"并调大 max_tokens
- 单次结果有随机性（温度/服务端 batching），T3/T4 边界格重跑 2~3 次再下结论
- token 数用服务端 `usage.prompt_tokens` 在线校准；无 usage 时按 3.8 chars/token 估算
- 语料上限：内置 ~1.4M tokens；更长测试用文件选择器载入更大 txt
- T4 计数即使 GPT/Claude 级也常失败，重点看随长度增长的衰减趋势

## NAS 部署（可选）

```bash
scp standalone.html user@host:/usr/share/nginx/html/longctx.html
chmod 644 /usr/share/nginx/html/longctx.html   # 别忘权限，否则 nginx 403
```

完成。浏览器访问 `http://host/longctx.html`。
