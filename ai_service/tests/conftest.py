"""
pytest 全局配置 — 测试环境统一取消 IP 限流
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

背景：本地限流器（src/ratelimit.py，滑动窗口 20 次/60s）对所有非 health
请求生效。全量测试用同一 IP（127.0.0.1）高频调用 HTTP 端点会触发 429，
历史表现为 test_rerank_langgraph.py 的 2 项预存失败（assert 429 == 200）。

本文件在测试进程内把 main 模块绑定的 check_rate_limit 替换为恒放行，
生产行为完全不受影响（patch 只存在于 pytest 进程）。IP 注入
（request.state.client_ip / user_id）是中间件独立步骤，不受影响。
"""
import pytest


@pytest.fixture(autouse=True)
def disable_rate_limit(monkeypatch):
    """全量测试取消 IP 限流（仅测试进程内生效）

    main.py 通过 from-import 把 check_rate_limit 绑定到自身命名空间，
    需 patch main 模块属性而非 src.ratelimit 源函数。
    """
    import main as main_module

    monkeypatch.setattr(
        main_module,
        "check_rate_limit",
        lambda client_ip, **kwargs: (True, 0),
    )


@pytest.fixture(autouse=True)
def default_intent_classifier_disabled(monkeypatch):
    """测试环境统一钉住 L4 分类器开关=关闭（module-056）

    生产默认已开启（PW_INTENT_CLASSIFIER_ENABLED 默认 true），但单测需
    hermetic：不依赖真实模型文件 models/intent_clf.joblib（非仓库产物），
    存量 LLM 路径用例不受影响。测试体内显式 setattr True 的用例
    （如 test_intent_dataset.py 的 L4 回退用例）后写覆盖本钉住值。
    """
    from src.config import settings

    monkeypatch.setattr(settings, "intent_classifier_enabled", False)
