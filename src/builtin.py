"""内置默认凭据槽位（公开版特意留空）。

原版这里随包分发一把专用 token，让应用开箱就能出候选。本仓库是公开的，
任何 key 写进 git 都等于公开——所以这里只保留字段与示例，不放电文：
用户必须自己配 `OPENAI_API_KEY`（或 `ANTHROPIC_API_KEY`），否则候选区为空
并在启动时提示。本机自己的配置放在仓库外的 ~/.config/jev-jarvis/env。

要把本仓库改回「开箱可用」：填入一把专用 token（模型白名单 + 额度封顶 +
过期时间），并同步替换 BASE_URL / MODEL_PREFERENCE。轮换只改这个文件。
"""

# 不随仓库分发真实凭据。示例地址，仅说明格式（OpenAI 兼容 /v1）。
API_KEY = ""
BASE_URL = "https://your-openai-compatible-relay.example.com/v1"

# 中转换渠道时不用改这里：启动会问一次中转「现在提供哪些模型」，按下面顺序挑第一个
# 存在的；都挑不到就取中转返回的第一个，问不到（离线／接口不兼容）才用 MODEL 硬上。
# 写死单个名字的代价是：包一旦分发出去，每个副本都冻结了那个名字，之后换渠道全废。
MODEL = "glm-4-flash"
MODEL_PREFERENCE = ["glm-4-flash", "Qwen/Qwen3-8B"]

# 端点要靠额外字段才能关思考时填这里（格式同 env 的 OPENAI_EXTRA_BODY，用户配了以 env 为准）。
# 统一发 enable_thinking=false：Qwen3 那类默认开思考的模型不关会慢到 85 秒，而 glm-4-flash
# 实测把它当未知字段忽略、不报错——所以这一条同时兼容两种渠道，不必按模型分开处理。
EXTRA_BODY = '{"enable_thinking": false}'
