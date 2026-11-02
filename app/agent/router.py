"""意图路由：把用户输入分到四条链路之一（chat / knowledge / task / mixed）。

设计决策：用 LLM 分类而非关键词规则——健身口语里"这周腿练了三次正常吗"
这种混合意图没法用规则穷举；分类一次调用延迟约几百毫秒，可接受。
分类失败时的安全默认是 knowledge：走 RAG，域外问题会被相关度闸门拒答，
不会像落到 chat 那样被基础模型放飞回答。
"""

from app.core.config import get_settings
from app.core.llm import get_llm_client
from app.core.observability import obs

LABELS = ("chat", "knowledge", "task", "mixed")

ROUTER_PROMPT = """你是健身助手 FitPilot 的意图分类器。判断用户输入属于哪一类，只输出一个小写标签，不要输出其他内容。

- chat：问候、寒暄、感谢、对助手本身的询问（你好/谢谢/你能干什么）
- knowledge：健身、训练、营养相关的知识提问，答案不依赖用户个人数据（深蹲怎么练/蛋白质吃多少）
- task：需要记录或查询用户个人数据的操作（帮我记录训练/查练了几次/鸡蛋多少热量/记体重）
- mixed：以下两种之一：①既要查用户个人数据、又要健身知识（我这周练了三次腿正常吗）；
  ②明显依赖时效性/最新信息的健身问题（今年新的训练方法/最近的赛事），知识库无法覆盖，需联网搜索

注意：与健身无关的提问（编程、写作业等）一律归 knowledge，由知识库拒答机制处理，禁止分到 chat，也禁止因为"最新"二字分到 mixed（如"最新的Python版本"不是健身问题）。

示例：
用户：你好呀 → chat
用户：深蹲时膝盖能超过脚尖吗 → knowledge
用户：帮我记录今天卧推80公斤5组5次 → task
用户：一碗牛肉面多少热量 → task
用户：我这周练了三次腿是不是太频繁了 → mixed
用户：2026年增肌领域有什么新的研究进展吗 → mixed"""


@obs(name="classify_intent")
def classify(query: str, history: list[dict] | None = None) -> str:
    """返回四类标签之一。带最近一轮历史辅助指代消解（"再来一组"这类输入）。"""
    messages = [{"role": "system", "content": ROUTER_PROMPT}]
    if history:
        messages += history[-2:]
    messages.append({"role": "user", "content": query})
    resp = get_llm_client().chat.completions.create(
        model=get_settings().chat_model, temperature=0, messages=messages
    )
    label = (resp.choices[0].message.content or "").strip().lower()
    return label if label in LABELS else "knowledge"
