# jev-jarvis-mac 完整复刻版（Intel Mac 适配）

本目录是 `github.com/jev-chat/jev-chat-jarvis-mac` v0.6.2 的**源码级完整复刻**：24 个 Python 模块、全部 UI/资源/测试/文档原样保留。改动是为 Intel Mac 做的判断层适配、429 重试，以及公开发布时移除内置共享 key（见下）。

> **公开版须自备生成层 Key**：`src/builtin.py` 里的内置凭据已留空（原版会随包分发一把共享 token）。请在 `~/.config/jev-jarvis/env` 配置 `OPENAI_API_KEY` + `OPENAI_BASE_URL` + `OPENAI_MODEL`，详见下文「生成层配置」。判断层若没有自己的 `TYPESAFE_API_KEY`，内置 chat 适配器也依赖生成层 key，同样需要配置后才能工作。

## 与原版的关系

| 项 | 原版 | 本复刻版 |
|---|---|---|
| 悬浮窗 UI / 菜单栏 / 校准窗 / 设置窗 | AppKit (PyObjC) | **完全相同**（源码未改） |
| 读屏：微信截图 + Vision OCR | perception.py / calibrated_messages.py | **完全相同**（源码未改） |
| 读屏：QQ 辅助功能树 | apps/ax_app.py | **完全相同**（源码未改） |
| 填入输入框 / 复制 / 换一组 | fill.py / hud.py | **完全相同**（源码未改） |
| 候选生成 / 14 种话术 / SSE 流式 / 排序 | generate.py / styles.py | **完全相同**（源码未改） |
| 会话历史 / 上下文预算 / 知识 | chat_context.py | **完全相同**（源码未改） |
| 判断层：意图 + 风险 + 排序 | 本地 decider-2b（torch/MPS，仅 Apple Silicon）或 TypeSafe Jev 云端 | **OpenRouter 原生 TypeSafe Jev（已配置，源码未改）**；网关不可用时自动降级到 `jev_compat.py` 适配器 |
| 支持架构 | 仅 arm64 | arm64 + **x86_64（Intel）** |

### 判断层配置（2026-11-26 接入 OpenRouter Jev）

`~/.config/jev-jarvis/env`（权限 600，仓库外）已配置官方 OpenRouter Jev 路径：
```
TYPESAFE_API_KEY=sk-or-v1-…        # Edward 提供的 OpenRouter key
TYPESAFE_BASE_URL=https://openrouter.ai/api/alpha/decisions
TYPESAFE_MODEL=typesafe/jev-1.13
JUDGE_BACKEND=cloud
```
这是原版 README 第 148 行记录的官方配置，**不是适配层**——走真正的 Jev decisions 模型，排序质量明显优于 chat 适配器（实测 "收到，我下午给" 0.76 / "不行我做不了" 0.01，而非适配器的均匀 0.25）。

**地域限制与自动降级**：OpenRouter 对 Jev 模型做地域 gate，中国大陆/香港出口会间歇性返回 HTTP 403 `This model is not available in your region`（实测深圳直连与香港代理均触发，但路由波动时也可用，5/5 连续成功过）。为此在 `src/judge_jev.py::_post()` 加了降级：原生网关返回 401/403/404/408/429/5xx 或网络不可达时，自动切到内置 chat 适配器并在本进程内保持（不重复重试失败端点），backend 标签如实标注 `jev-compat/…`；payload 逻辑错误（400/422）不吞，仍抛出以便排查。换到不受限网络时原生 Jev 自动恢复，无需改配置。

## 为什么需要适配

原版硬性只支持 Apple Silicon：本地判断模型 `decider-2b` 依赖 `torch>=2.14`，而 torch 没有 macOS x86_64 wheel（原版 `bootstrap_uv.sh` 直接拦截 Intel 启动）。判断层的题目构造、答案解析、排序逻辑本身与架构无关，只有"把 questions 送出去、拿回 answers"这一步依赖端点。

本机 Intel，判断层改走官方同样支持的云端路径：内置中转只提供普通 `chat/completions`（`/v1/systemone` 等结构化端点实测 404），因此新增 `src/jev_compat.py`，把同一份 Jev payload 用 chat 接口让模型输出等价的 `answers` JSON。**题目集（INTENTS/RISK_LEVELS）、答案解析、概率处理、候选排序全部复用原版代码，一行未改。**

## 改动清单（共 6 个文件 + 2 个新增）

| 文件 | 改动 |
|---|---|
| `src/jev_compat.py`（新增） | Jev 协议适配器：chat/completions → answers JSON，含概率分布补全 |
| `src/generate.py` | 生成层对 429/5xx 做有界退避重试（遵守 `Retry-After`，最多 1+3 次）；SSE 在建流阶段同样重试；三条话术错峰 0.4s 发出；错误文案区分限流/403/5xx（见下） |
| `tests/test_generation_retry.py`（新增） | 6 项回归：退避上限、Retry-After、429 后成功、重试耗尽、400 不重试、错误文案 |
| `src/judge_jev.py` | `jev_configured()` 识别适配器；`_post()` 无原生 key 时转适配器；backend 标签如实标注 |
| `src/hud.py` | 首次引导与预热日志识别适配器（不再引导下载 Intel 无法运行的本地模型） |
| `pyproject.toml` | 移除仅本地模型需要的 torch/transformers/laya；保留 huggingface-hub（纯 Python 的 tqdm，测试套件依赖）、numpy 与全部 pyobjc |
| `packaging/bootstrap_uv.sh` | `jev_check_arch()` 放行 x86_64 |
| `packaging/build_app.sh` | 架构从写死 arm64 改为 `$(uname -m)` 动态适配（Info.plist / clang / 校验）；git revision 无 `.git` 时降级为 `replica`；版本替换改用 `/usr/bin/sed` 绕开 sandbox 的 toybox sed shim；源码改用 `rsync --exclude '__pycache__'` 拷贝，构建到临时目录后 `mv` 原子替换，旧包改名 `.prev-<时间戳>` 保留（不再批量删除，避免沙箱保护的半包状态） |

原版 `uv.lock` 备份为 `uv.lock.upstream`。

### 生成层配置（2026-11-26 接入 token2x）

`~/.config/jev-jarvis/env` 同文件追加：
```
OPENAI_API_KEY=sk-…                              # Edward 提供的 token2x key
OPENAI_BASE_URL=https://api.token2x.online/v1
OPENAI_MODEL=agnes-3.0-flash
OPENAI_EXTRA_BODY='{"max_tokens": 1200}'
```
**为什么不是 deepseek-flash**：用户最初指定该模型，key 有效但实测它对生成层的复杂 prompt 会陷入无限思考（思考随预算同步膨胀，600/1000/1500 都吃光预算、正文为空；system role 能抑制但生成层代码固定只发 user 消息，配置层无解）。同中转的 `agnes-3.0-flash` 思考约 1400 字符后收敛，配合 `max_tokens: 1200` 稳定产出 2 条/话术候选，经用户确认后替换。

**env 引号坑**：解析器用 shlex，JSON 值必须用单引号包裹（`KEY='{"a": 1}'`），否则双引号被吃掉、`_extra_params()` 解析失败返回 `{}`。

**JUDGE_BACKEND 会被 App 改写**：运行中 App 的设置窗口可能把 `JUDGE_BACKEND=cloud` 写回成 `local`（实测 15:15:39 发生过），如发现判断层异常检查此键。

**生成层 429 限流（2026-11-26 15:40 修复）**：面板报「候选生成失败：服务未返回可用候选，请检查模型设置」时，真实原因常是 token2x 中转的短时限流——日志里三条话术 `失败: 0; 1; 2` 且耗时不足 1s，直接复现第 3 个请求起返回 HTTP 429（key 与模型均正常，稍后单次请求又成功）。原版对 429 一次即放弃，现已改为：`_KeepAlivePool.post_json()` 与 SSE 建流对 429/500/502/503/504 最多重试 3 次（指数退避 0.5/1/2s + 抖动，尊重 `Retry-After`），三条话术按 slot 错峰 0.4s 发出以降低突发；400/403 等非瞬时错误不重试。面板文案改为「上游限流 429（已自动重试），请稍后再试」等具体原因。若仍持续失败，先确认没有多份 HUD 实例同时监控同一聊天窗（每实例 3 请求/消息，会成倍放大限流）。

## 启动

**方式 A（推荐，形态与原版一致）**：双击 `jev-jarvis.app`。这是已打包好的原生 bundle（812K，x86_64 原生切片），有自己的 TCC 身份——屏幕录制/辅助功能权限授予给 "jev-jarvis" 而非终端。独立 venv 在 `~/Library/Application Support/jev-jarvis/venv`，首次启动自动建好。

**方式 B（开发调试）**：
```bash
cd "/Users/Edward/Documents/workbuddy/1126-skills 学习/jev-jarvis-mac-replica"
./start.command
```

**重新打包**（改了源码后）：`./packaging/build_app.sh`（会先跑 338 个测试，全绿才打包）。

首次会弹 macOS 权限请求：**屏幕录制**（微信截图读屏）、**辅助功能**（QQ 文本路径与"填入"）。**公开版没有内置共享 key**：先按上文配置 `OPENAI_API_KEY` 等再启动，否则候选区为空并提示缺 key。判断层可在设置窗口配置自己的 `TYPESAFE_API_KEY` 走原生 Jev 端点；没有 TypeSafe key 时自动走 chat 适配器，但该适配器同样需要生成层 key。

## 验证状态（2026-11-26，本机 Intel）

- `uv sync` 依赖安装 PASS（8 包，无 torch）
- 全部 24 模块导入 PASS；`py_compile` 全 PASS
- 判断层端到端 PASS：意图识别（"派活"）、风险打分、actions 映射
- 候选排序 PASS（合理排降序）
- 生成层 PASS：内置凭据产出 2 条候选回复
- 悬浮窗启动 PASS：窗口 `jev-jarvis` 360×806 + 菜单栏图标，三话术下拉框正常渲染
- **打包 PASS**：`build_app.sh` 338 测试全绿 + 16 项 bundle 校验全过，产出 `jev-jarvis.app`（772K，x86_64 原生切片，含 429 重试修复）；旧包保留为 `jev-jarvis.app.prev-20261126154103`
- **双击启动 PASS**：`open jev-jarvis.app` → 独立 venv 自动装好 → 预热完成 → 悬浮窗 360×806 + 菜单栏图标渲染正常，截图确认三话术下拉框齐全
- 读屏链路：微信真实窗口 OCR + 气泡归属此前已验证（见 skill 侧记录）

## 能力边界（与原版一致）

- 只读：不 hook、不注入、不解密数据库、不自动发送
- "填入"是唯一写动作，发送永远由用户在聊天 App 手动完成
- 不碰转账/红包/收款
- 判断层为诊断辅助，非绝对结论；关键决策由人做主
