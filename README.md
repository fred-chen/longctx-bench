# 长上下文测试套件（召回 / 检索 / 推理 / 行为退化）

针对超过 256K token 的长上下文，测量四类能力，并检测 **loop（复读循环）**、
**caveman-speak（电报体退化）** 等行为异常。方法论基于经典
[Needle-In-A-Haystack](https://github.com/gkamradt/LLMTest_NeedleInAHaystack)
扩展（另加多针检索、多跳推理链、计数聚合、强制长文生成探针）。

## 文件

| 文件 | 作用 |
|---|---|
| `bench.py` | 命令行测试 harness（零依赖，stdlib-only） |
| `index.html` + `serve.py` | 浏览器测试控制台：可测**任意 OpenAI 兼容端点/模型**（serve.py 兼做 CORS 代理） |
| `make_report.py` | 把 `results.json` 渲染成自包含静态 `report.html` |
| `corpus/` | Gutenberg 公版书语料（haystack），5.7MB ≈ 1.4M tokens |
| `results.json` / `report.html` | 最近一次 Python 端全量测试结果 / 报告 |

## 测试项

- **T1 单针 NIAH 网格**：不同长度 × 不同深度（needle 位置 %）→ 召回热图，可暴露 lost-in-the-middle
- **T2 五针多路召回**：5 个针分散在 10/30/50/70/90% 深度，要求全部列出（检索广度）
- **T3 三跳事实链**：三个事实分散在上下文不同位置，必须链式推理（A→B→C）
- **T4 计数聚合**：随机短语插入 7 次，问出现次数（聚合类普遍是弱项）
- **T5 强制长文生成（退化探针）**：要求列出针 + 写 350 词以上长文，放大退化信号

所有响应都会计算退化指标并打标：

| 指标 | 判读 |
|---|---|
| `max10gram_repeat ≥ 3` | **loop**：同一 10 词短语重复 ≥3 次 |
| `function_word_ratio < 0.30` 且平均句长 <10（≥80 词时） | **caveman-speak**：虚词丢失、电报体 |
| `distinct2 < 0.60`（≥150 词时） | **repetitive**：整体重复度高 |
| `finish=length` 且正文为空 | 思考模型把 max_tokens 烧光在 reasoning 上（思考 runaway） |

## 快速使用（测其他端点/模型）

### 方式 A：浏览器控制台（推荐）

```bash
python3 serve.py --port 8899        # 启动控制台 + CORS 代理
open http://127.0.0.1:8899/         # 打开测试台
```

页面上改 **Base URL / Model ID / API Key** 即可测任意端点；语料可选本地、
URL 下载或粘贴。token 数自动校准（用服务端返回的 `usage.prompt_tokens`，
无 usage 时按 3.8 chars/token 估算并在线修正）。
`http://127.0.0.1:8899/report` 可查看 Python 端的最新静态报告。

### 方式 B：命令行

```bash
# 冒烟（先小后大，强烈建议）
python3 bench.py --base http://HOST:PORT/v1 --model MODEL_ID --lengths 8192

# 全量（131K/262K/328K × 5 深度 + T2-T5，共 27 例）
python3 bench.py --lengths 131072,262144,327680 --out results.json
python3 make_report.py results.json report.html

# 常用开关
#   --key sk-xxx                Bearer 鉴权
#   --think-mode off|on|default 思考模式（默认 off：防止思考吃光 max_tokens 造成假失败）
#   --lengths 32768,131072      自定义目标 token 长度
#   --depths 0,50,100           自定义针深度
#   --quick                     只跑 0/50/100 三深度
```

## 注意事项

- **思考模型**：reasoning 会占用 `max_tokens`。默认 harness 发
  `chat_template_kwargs:{enable_thinking:false}`；不支持该参数的服务端用
  `--think-mode default`（不发送），此时把 max_tokens 调大。
- **服务端偶发挂起**：大请求可能被推理服务吞掉。harness 有 socket 超时 300s +
  3 次重试 + 超上下文错误自动跳过该长度剩余用例。
- **实际 token 数 ≠ 名义长度**：haystack 按校准系数裁剪，若某次请求实际
  prompt_tokens 低于目标的 98.5%，harness 会自动修正系数并重试一次（日志有
  `recal` 字样），以实测 `prompt_tokens` 为准。
- **语料上限**：默认语料约 1.4M token，超长测试请往 `corpus/` 加 `.txt`
  （删除 `corpus_all.txt` 让 serve.py 重新合并）。
- T4 计数、T2 全召回即使 GPT/Claude 级别也常失败，重点看**随长度增长的衰减趋势**。

## 部署到 nginx（deploy/）

适用于 Rocky/RHEL 等带 SELinux 的机器，把控制台挂在现有 nginx 的 `/longctx/` 路径下：

```bash
# 1) 代码放 /opt/longctx（含 corpus/），语料也可跑 download_corpus.sh 现场下载
rsync -az --exclude .git ./ root@HOST:/opt/longctx/
# 2) (可选) basic auth 护栏：取消 longctx.conf 里两行 auth_* 注释，并运行：
# printf "user:%s\n" "$(openssl passwd -apr1 'PASSWORD')" > /etc/nginx/.htpasswd_longctx
# 3) systemd 服务（serve.py 只绑 127.0.0.1，由 nginx 反代对外）
cp deploy/longctx.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now longctx
# 4) nginx（需 SELinux 允许 httpd 反代）
cp deploy/longctx.conf /etc/nginx/default.d/longctx.conf
setsebool -P httpd_can_network_connect 1; nginx -t && systemctl reload nginx
```

访问 `http://HOST/longctx/`。仓库默认**无认证**；若服务器公网可达，建议按步骤 2 开启 basic auth 护栏。
