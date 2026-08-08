"""
L4 意图分类器训练脚本 — golden 集训练 + 模型落盘（ADR-0003 L4）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    python -m eval.train_intent_classifier          # 默认训练并落盘
    python -m eval.train_intent_classifier --no-save  # 只训练评估，不落盘

训练数据（优先级从高到低）:
  1. eval/golden_intent 评测集（module-043 WP2，若已存在：含闲聊/实时/
     边界易混样本）——数据源就绪后自动优先
  2. eval/golden.json（knowledge 天然标注，30 题）
  3. 脚本内置手工样本（ADR-0003 示例 + 闲聊/实时/边界易混，类别补平衡）

已知边界（写入验收）:
  - 真实飞轮数据（前端 👍/👎）未积累：先以 golden 集训练；飞轮接口已
    预留——样本回流后并入 load_training_samples 的返回列表重训即可，
    intent_classifier.fit() 的接口无需变更
  - golden 集天然 knowledge 多：LogisticRegression(class_weight="balanced")
    抗不平衡，避免学成"永远猜 knowledge"（ADR-0003 L4 警告）
  - 依赖 sklearn / joblib（本地已安装）；模型落盘 ai_service/models/
    intent_clf.joblib（对齐本地模型存放约定，训练产物不进仓库）

L4 上线流程:
  1. 跑本脚本训练出模型 → 2. router 配置开关
  PW_INTENT_CLASSIFIER_ENABLED=true（或注入 IntentClassifier 实例）
  → 3. 加载失败自动回退 LLM 分类（零影响）
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("train_intent_classifier")

# 本文件所在目录（eval/）
EVAL_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = EVAL_DIR / "golden.json"
# 模型落盘路径（与 intent_classifier 默认一致）
DEFAULT_MODEL_PATH = str(
    Path(__file__).resolve().parents[1] / "models" / "intent_clf.joblib"
)

# 内置补充样本：ADR-0003 示例 + 闲聊/实时/边界易混（补类别平衡）
_BUILTIN_SAMPLES: list[tuple[str, str]] = [
    # knowledge（边界易混：看似闲聊实为知识库问题）
    ("你们网站有哪些功能", "knowledge"),
    ("你知道 GC 是什么吗", "knowledge"),
    ("G1 垃圾收集器和 CMS 的区别", "knowledge"),
    ("什么是 Redis 的持久化机制", "knowledge"),
    # casual_chat
    ("你好呀", "casual_chat"),
    ("在吗", "casual_chat"),
    ("谢谢", "casual_chat"),
    ("再见", "casual_chat"),
    ("介绍一下你自己", "casual_chat"),
    # realtime
    ("现在几点了", "realtime"),
    ("今天天气怎么样", "realtime"),
    ("今天是几号", "realtime"),
]


def load_golden_knowledge(path: Path = GOLDEN_PATH) -> list[tuple[str, str]]:
    """从 golden.json 加载 knowledge 样本（天然标注，每题一条）"""
    if not path.exists():
        logger.warning("golden.json 不存在，跳过 knowledge 样本: %s", path)
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = [
        (item["question"], "knowledge")
        for item in data if item.get("question")
    ]
    logger.info("golden.json 加载 knowledge 样本 %d 条", len(samples))
    return samples


def load_golden_intent_samples() -> list[tuple[str, str]]:
    """从 golden_intent 评测集加载样本（WP2 落地后自动优先）

    容错设计：兼容 WP2 golden_intent.py 的多种数据形态——
    INTENT_DATASET（list[dict]，query/intent 键）/ DATASET / 元组列表。
    任一可用即优先返回；不可用返回空 → 调用方回退 golden.json + 内置样本。
    """
    try:
        from eval import golden_intent  # 并行开发中，可能暂不存在
        dataset = (
            getattr(golden_intent, "INTENT_DATASET", None)
            or getattr(golden_intent, "DATASET", None)
        )
        if isinstance(dataset, list) and dataset:
            samples = []
            for item in dataset:
                if isinstance(item, tuple) and len(item) == 2:
                    samples.append((item[0], item[1]))
                elif isinstance(item, dict):
                    query = item.get("query") or item.get("question")
                    if query and item.get("intent"):
                        samples.append((query, item["intent"]))
            if samples:
                logger.info("golden_intent 评测集加载 %d 条", len(samples))
                return samples
    except Exception as e:
        logger.warning("golden_intent 评测集暂不可用（回退 golden.json + 内置样本）: %s", e)
    return []


def load_training_samples() -> list[tuple[str, str]]:
    """组装训练样本：golden_intent 优先 → golden.json + 内置补充

    去重（按 query），保留首见标注（golden_intent > golden.json > 内置）。
    """
    samples: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _append(items: list[tuple[str, str]]) -> None:
        for query, label in items:
            q = query.strip()
            if q and q not in seen:
                samples.append((q, label))
                seen.add(q)

    _append(load_golden_intent_samples())
    _append(load_golden_knowledge())
    _append(_BUILTIN_SAMPLES)

    labels = sorted({lbl for _, lbl in samples})
    logger.info("训练样本组装完成: %d 条, 类别分布: %s",
                len(samples), {lbl: sum(1 for _, l in samples if l == lbl) for lbl in labels})
    return samples


async def train(model_path: str, save: bool) -> None:
    """训练并评估 L4 分类器（样本不足时明确报错退出）"""
    from agent.intent_classifier import IntentClassifier

    samples = load_training_samples()
    if len(samples) < 10:
        logger.error("训练样本不足（%d 条），无法训练——请先补充标注数据", len(samples))
        sys.exit(1)

    clf = IntentClassifier(model_path=model_path)
    metrics = await clf.fit(samples, save=save)

    print("\n" + "=" * 60)
    print("Intent Classifier Training (bge-m3 + LogisticRegression)")
    print("=" * 60)
    print(f"Samples: {metrics['n_samples']} | Classes: {metrics['classes']}")
    print(f"Accuracy: {metrics['accuracy']:.4f}")
    print("-" * 60)
    print("Classification report (test split):")
    print(metrics["report"])
    print("=" * 60)
    if save:
        print(f"Model saved to: {model_path}")
        print("上线：设置 PW_INTENT_CLASSIFIER_ENABLED=true 或向 RouterAgent 注入实例")
    else:
        print("--no-save：未落盘")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="L4 意图分类器训练（golden 集）")
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH,
                        help=f"模型落盘路径（默认 {DEFAULT_MODEL_PATH}）")
    parser.add_argument("--no-save", action="store_true", help="只训练评估，不落盘")
    args = parser.parse_args()
    asyncio.run(train(args.model_path, save=not args.no_save))


if __name__ == "__main__":
    main()
