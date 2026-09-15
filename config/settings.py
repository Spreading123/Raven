"""全局配置：读取 .env / 环境变量，提供统一配置访问。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from app.utils.paths import APP_ROOT

# 打包后 .env 放在 exe 同级（可写）；源码运行则在项目根
load_dotenv(APP_ROOT / ".env")


@dataclass
class ProviderProfile:
    """一个可选的模型供应商（服务商）预设。"""

    name: str          # 显示名（如“火山方舟”）
    base_url: str      # OpenAI 兼容 API 端点
    models: list[str]  # 可选模型名列表
    # 该供应商的 api_key 环境变量名（.env 中可选配置）；运行时也可通过 UI 输入并持久化。
    api_key_env: str = ""
    # 是否需要 base_url 输入框。OpenAI 兼容协议（如火山方舟）需要；
    # 官方 API（如 DeepSeek）端点由官方决定，无需用户填 base_url，故隐藏输入框。
    needs_base_url: bool = True
    # 该供应商下支持视觉输入（多模态“看图”）的模型 ID 白名单。
    # 不在白名单内的模型一律视为不支持视觉（保守默认），用于 UI 层在
    # 用户附加图片时拦截：避免向纯文本模型发送 image_url 内容块导致 400 或乱答。
    vision_models: list[str] = field(default_factory=list)


# 预设供应商注册表（顺序即下拉菜单展示顺序）。
# 新供应商只需在此追加一项（名称、端点、模型列表）。
PROVIDERS: dict[str, ProviderProfile] = {
    "DeepSeek": ProviderProfile(
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        models=[
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ],
        api_key_env="DEEPSEEK_API_KEY",
        needs_base_url=False,
    ),
    "火山方舟": ProviderProfile(
        name="火山方舟",
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
        models=[
            "doubao-seed-2.0-lite",
            "kimi-k2.7-code",
            "minimax-m3",
            "doubao-seed-evolving",
            "kimi-k3",
            "doubao-seed-2.1-turbo",
            "deepseek-v4-flash",
            "glm-5.3",
            "deepseek-v4-pro",
            "glm-5.3-flash",
            "doubao-1.5-pro-32k",
            "doubao-1.5-lite-32k",
        ],
        api_key_env="ARK_API_KEY",
        # 火山方舟的多模态能力随具体模型/接入方式而异，这里保守地仅标注
        # 确认支持视觉输入的模型（含官方描述明确标注多模态/视觉的）；未标注
        # 的一律视为不支持，避免误发图片。可在新增模型时按需补充。
        vision_models=[
            "doubao-seed-2.0-lite",
            "doubao-1.5-pro-32k",
            # kimi-k2.7-code：官方标注支持文本、图片与视频输入
            "kimi-k2.7-code",
            # kimi-k3：原生支持视觉理解
            "kimi-k3",
            # doubao-seed-2.1-turbo：官方标注多模态能力
            "doubao-seed-2.1-turbo",
            # glm-5.3-flash：GLM-5 系列首个原生多模态模型
            "glm-5.3-flash",
        ],
    ),
    "OpenAI": ProviderProfile(
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        models=[
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4-turbo",
        ],
        api_key_env="OPENAI_API_KEY",
        # OpenAI 的 gpt-4o 系列均原生支持视觉输入
        vision_models=[
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4-turbo",
        ],
    ),
}


@dataclass
class LLMConfig:
    """LLM API 配置（OpenAI 兼容）。"""

    api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
    max_tokens: int = int(os.getenv("OPENAI_MAX_TOKENS", "2048"))
    timeout: int = int(os.getenv("OPENAI_TIMEOUT", "30"))

    def apply_provider(self, base_url: str, model: str, api_key: str) -> None:
        """运行时切换供应商：更新 base_url / model / api_key（不写入 .env）。

        调用方在需要重建 LLM 客户端时触发（LLMAdapter.set_provider 会重置缓存）。

        注意：api_key 必须无条件覆盖（包括空值），否则切换供应商时若新供应商
        未填 key，会残留上一个供应商的 key，导致用错 key 请求而被拒（401）。
        """
        self.base_url = base_url
        self.model = model
        self.api_key = api_key

    def match_provider(self) -> ProviderProfile | None:
        """按当前 base_url / model 推断所属供应商；未命中任何预设则返回 None。

        供应商匹配逻辑在此**收敛一处**，供 UI 下拉匹配（_match_current_provider）、
        视觉能力判定（supports_vision）、API Key 历史回退（llm）等共用，
        避免同一套推断在多处重复而漂移。
        """
        base = (self.base_url or "").rstrip("/")
        model = self.model or ""
        if not base and not model:
            return None
        # 优先按 base_url 精确匹配供应商：端点（base_url）具备唯一性，比模型名
        # 更可靠。否则当同一模型名跨供应商托管时（例如 deepseek-v4-* 既在 DeepSeek
        # 官方、又被火山方舟托管），用火山方舟 base_url + deepseek 模型会被误配到
        # DeepSeek 官方，导致 API Key 回退、视觉判定等跟着错。
        for prof in PROVIDERS.values():
            if base and base.startswith(prof.base_url.rstrip("/")):
                return prof
        # base_url 未命中任何已知端点时，退回按模型名匹配（支持自定义 base_url 场景）
        for prof in PROVIDERS.values():
            if model and model in prof.models:
                return prof
        return None

    def supports_vision(self) -> bool:
        """当前所选模型是否支持视觉（多模态“看图”）。

        判定依据：先按 base_url / model 定位所属供应商，再看 model 是否命中
        该供应商的 ``vision_models`` 白名单。

        不在任何供应商白名单内的一律视为“不支持”（保守默认）——因为向纯文本
        模型发送 image_url 内容块可能 400 或导致模型乱答。第三方自定义模型若
        实际支持视觉，可在对应供应商的 vision_models 中追加模型 ID。
        """
        prof = self.match_provider()
        return bool(prof and self.model in prof.vision_models)


@dataclass
class AppConfig:
    """应用整体配置。"""

    app_name: str = "Raven"
    app_version: str = "0.1.0"
    window_width: int = 1100
    window_height: int = 750
    llm: LLMConfig = field(default_factory=LLMConfig)


config = AppConfig()

