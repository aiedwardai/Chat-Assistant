"""Jev 协议适配器 —— Intel Mac / 无 TypeSafe key 时的判断层传输层替身。

背景
----
原版判断层走 TypeSafe 的结构化决策端点 `/v1/systemone`：送入 state + questions，
拿回带校准概率的 `answers`。本机是 Intel Mac，本地 decider-2b 依赖的 torch>=2.14
没有 x86_64 wheel（官方硬限制），而内置中转只提供普通 chat/completions
（实测 `/v1/systemone`、`/alpha/decisions`、`/v1/evaluate` 均 404）。

本模块把同一份 payload 翻译成一个 chat 请求，让生成模型输出**等价的 answers JSON**，
再交回原版 judge_jev.py 的解析逻辑。因此：

    · 题目集（INTENTS / RISK_LEVELS）、答案解析、概率处理、排序 —— 全是原版代码，未改
    · 只替换「怎么把 questions 送出去、怎么拿回 answers」这一层传输
    · 有真正的 TypeSafe key 时 judge_jev 仍走原生端点，本模块不介入

安全：key 只从内置凭据/环境变量读，绝不打印；只发判断题内容，与生成层同源同端点。
"""

from __future__ import annotations

import json
import re

import builtin
from generate import http_post_json


def available() -> bool:
    """内置 chat 凭据是否可用（无需用户配置即可判断）。"""
    return bool(builtin.API_KEY and builtin.BASE_URL)


def _model() -> str:
    return builtin.MODEL or "glm-4-flash"


_SYSTEM = """你是一个结构化决策引擎，只输出 JSON，不输出任何解释文字。

你会收到一段对话状态 state 和一组判断题 questions。请逐题作答，最后只输出一个 JSON 对象：
{"answers": {"<题目key>": {<该题答案字段>}, ...}}

各题型的答案字段：
- choice 题：{"choice": "<从 criteria 的键里选一个>", "confidence": 0到1的小数,
             "probabilities": {"<每个键>": 0到1的概率}}
- score 题：{"score": 0到9的整数, "confidence": 0到1的小数}
- noul 题：{"choice": true或false, "confidence": 0到1的小数}

硬性要求：
- choice 的取值必须原样等于 criteria 里的某个键，不要自创标签、不要翻译
- score 必须是 0 到 9 之间的整数
- probabilities 的键必须覆盖 criteria 的全部键，总和约等于 1
- 只输出 JSON 本身，不要 markdown 代码块、不要前后缀"""


def _q_desc(q: dict) -> dict:
    """把一道题压成喂给模型的紧凑描述。"""
    out = {"type": q.get("type", "choice"),
           "instructions": q.get("instructions", "")}
    crit = q.get("criteria")
    if isinstance(crit, dict):
        out["criteria"] = {str(k): (v if v is not None else "") for k, v in crit.items()}
    elif isinstance(crit, list):
        out["criteria"] = {str(i): str(v) for i, v in enumerate(crit)}
    return out


def _extract_json(text: str) -> dict:
    """从模型输出里稳健取出 JSON（容忍 ```json 包裹、前后噪声）。"""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except Exception:
        pass
    # 退而求其次：截取最外层花括号
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except Exception:
            pass
    return {}


def _fill_probabilities(ans: dict, q: dict) -> None:
    """模型漏给 probabilities 时，按 confidence 构造一个合法分布。"""
    if ans.get("probabilities"):
        return
    crit = q.get("criteria")
    keys = (list(crit.keys()) if isinstance(crit, dict)
            else [str(i) for i in range(len(crit))] if isinstance(crit, list) else [])
    if not keys:
        return
    conf = max(0.0, min(1.0, float(ans.get("confidence") or 0.0) or 1.0 / len(keys)))
    chosen = str(ans.get("choice", ""))
    others = [k for k in keys if k != chosen]
    probs = {k: 0.0 for k in keys}
    if chosen in probs:
        probs[chosen] = conf
        rest = 1.0 - conf
    else:
        rest = 1.0
    if others:
        each = rest / len(others)
        for k in others:
            probs[k] = round(each, 4)
    ans["probabilities"] = {k: round(v, 4) for k, v in probs.items()}


def simulate_jev(payload: dict, timeout: int = 30) -> dict:
    """把 Jev payload 用 chat 接口跑一遍，返回等价的 {'answers': {...}}。"""
    state = payload.get("state", "")
    questions = payload.get("questions") or {}
    user = ("对话状态：\n" + state + "\n\n判断题：\n"
            + json.dumps({k: _q_desc(v) for k, v in questions.items()},
                         ensure_ascii=False, indent=1)
            + "\n\n只输出 answers JSON。")

    extra = {}
    try:
        extra = json.loads(builtin.EXTRA_BODY) if builtin.EXTRA_BODY else {}
    except Exception:
        pass
    body = {
        "model": _model(),
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 700,
    }
    body.update(extra)

    url = builtin.BASE_URL.rstrip("/") + "/chat/completions"
    data = http_post_json(
        url,
        {"content-type": "application/json",
         "authorization": f"Bearer {builtin.API_KEY}"},
        body, timeout)
    content = ""
    for choice in data.get("choices") or []:
        msg = choice.get("message") or {}
        if msg.get("content"):
            content = msg["content"]
            break
    parsed = _extract_json(content)
    answers = parsed.get("answers") if isinstance(parsed, dict) else None
    if not isinstance(answers, dict):
        answers = {}

    # 归一化：保证每个题目都有答案对象，choice 题补齐概率分布
    out = {}
    for key, q in questions.items():
        ans = answers.get(key) or {}
        if not isinstance(ans, dict):
            ans = {}
        if q.get("type") == "score":
            try:
                ans["score"] = int(float(ans.get("score", 0)))
            except Exception:
                ans["score"] = 0
        else:
            _fill_probabilities(ans, q)
        out[key] = ans
    return {"answers": out, "backend": f"jev-compat/{_model()}"}
