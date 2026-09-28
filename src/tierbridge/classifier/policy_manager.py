import os
import json
from typing import Dict, Any, Optional

class ClassifierPolicyManager:
    """
    SOLID SRP: 분류기 파라미터 및 정책 설정을 전담 관리하며, 하드코딩 없는 동적 설정을 보장합니다.
    """
    _cached_policy: Optional[Dict[str, Any]] = None

    @classmethod
    def get_policy_paths(cls) -> list:
        paths = []
        live_path = os.path.expanduser("~/.tierbridge/live/config/classifier_policy.json")
        dev_dir = os.environ.get("TIERBRIDGE_DEV_DIR", os.getcwd())
        dev_path = os.path.join(dev_dir, "config", "classifier_policy.json")
        
        # 1순위: 라이브 런타임, 2순위: 개발 디렉토리
        paths.append(live_path)
        if dev_path not in paths:
            paths.append(dev_path)
        return paths

    @classmethod
    def load_policy(cls) -> Dict[str, Any]:
        if cls._cached_policy is not None:
            return cls._cached_policy

        for path in cls.get_policy_paths():
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data and "fast_path" in data:
                        cls._cached_policy = data
                        return data
                except Exception:
                    pass

        # Fallback 기본 정책 규격
        default_policy = {
            "version": "1.0.0",
            "fast_path": {
                "enabled": True,
                "max_token_length": 150,
                "simple_patterns": [
                    r"^\s*(git\s+status|git\s+log|git\s+diff|ls|pwd|whoami|date)\s*$",
                    r"^\s*(안녕|하이|test|ping|어디까지|확인|조회|목록|상태\s*확인)\s*$",
                    r"^\s*(오타\s*수정|단순\s*조회|파일\s*읽기|내용\s*확인)\s*$"
                ],
                "default_tier": "BRONZE"
            },
            "context_metrics": {
                "enabled": True,
                "large_context_tokens": 32000,
                "large_context_min_tier": "GOLD",
                "multi_file_count_threshold": 3,
                "multi_file_min_tier": "PLATINUM"
            },
            "escalation": {
                "enabled": True,
                "error_keywords": [
                    "error", "exception", "failed", "traceback", "syntaxerror",
                    "modulenotfounderror", "fail", "오류", "실패", "컴파일 에러", "테스트 실패"
                ],
                "max_escalation_steps": 2
            },
            "budget_governor": {
                "enabled": True,
                "eco_threshold_percent": 20.0,
                "critical_threshold_percent": 5.0,
                "eco_tier_ceiling": "GOLD",
                "critical_tier_ceiling": "BRONZE"
            }
        }
        cls._cached_policy = default_policy
        cls.save_policy(default_policy)
        return default_policy

    @classmethod
    def save_policy(cls, policy_data: Dict[str, Any]):
        cls._cached_policy = policy_data
        for path in cls.get_policy_paths():
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(policy_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
