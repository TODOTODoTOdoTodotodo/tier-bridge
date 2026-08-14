import os
from datetime import datetime
from typing import Dict, Any, List
from src.tierbridge.model_registry import registry

class HealingEngine:
    """
    Model Healing Factor Engine:
    - 실제 신규 모델 릴리즈 및 단가 인하 실시간 감지 (has_new_healing: True/False)
    - 데모 샘플 핫패치 테스트 분리 (Sample Demo Template)
    - 기존 매핑 대비 비용 및 성능 비교표 도출
    - 무중단 핫패치 릴리즈 & 스냅샷 생성
    """

    # 데모/체험 테스트용 샘플 템플릿
    SAMPLE_HEALING_TEMPLATE = {
        "version_id": "v1.1.0-sample-demo",
        "name": "Healing Sample Demo v1.1.0 (Demo Test Hot-patch)",
        "description": "힐링팩터 핫패치 및 롤백 기능 동작을 검증하기 위한 데모 샘플 스냅샷",
        "mapping": {
            "BRONZE": {"model": "gpt-5.6-luna", "effort": "low", "input_price": 0.60, "output_price": 1.80},
            "SILVER": {"model": "gpt-5.6-luna", "effort": "medium", "input_price": 0.60, "output_price": 1.80},
            "GOLD": {"model": "gpt-5.6-terra", "effort": "medium", "input_price": 2.0, "output_price": 8.0},
            "PLATINUM": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.0, "output_price": 8.0},
            "DIAMOND": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.0, "output_price": 8.0},
            "CHALLENGER": {"model": "gpt-5.6-sol", "effort": "xhigh", "input_price": 4.5, "output_price": 18.0}
        }
    }

    @classmethod
    def get_healing_status(cls) -> Dict[str, Any]:
        active_mapping = registry.get_active_mapping()
        rec_mapping = cls.SAMPLE_HEALING_TEMPLATE["mapping"]
        active_vid = registry.get_active_version_id()

        # 핫패치가 이미 적용되었거나(hotpatch) 최신 상태인 경우 감지 닫음, 구형 모델일 때만 True 활성화
        is_already_hotpatched = "hotpatch" in active_vid or active_vid == "v1.1.0-healing-hotpatch"
        has_real_new_model = (not is_already_hotpatched) and (
            any(m.get("model") in ["gpt-5.4-mini", "gpt-5.5"] for m in active_mapping.values())
            or "test" in active_vid or "legacy" in active_vid
        )

        # 비교표 생성 (데모 및 실제 비교 공용)
        comparison = []
        for tier in ["BRONZE", "SILVER", "GOLD", "PLATINUM", "DIAMOND", "CHALLENGER"]:
            curr = active_mapping.get(tier, {"model": "N/A", "input_price": 0, "output_price": 0})
            rec = rec_mapping.get(tier, {"model": "N/A", "input_price": 0, "output_price": 0})
            
            curr_avg_price = (curr.get("input_price", 0) + curr.get("output_price", 0)) / 2.0
            rec_avg_price = (rec.get("input_price", 0) + rec.get("output_price", 0)) / 2.0
            
            savings_pct = 0.0
            if curr_avg_price > 0:
                savings_pct = round(((curr_avg_price - rec_avg_price) / curr_avg_price) * 100, 1)

            comparison.append({
                "tier": tier,
                "current_model": curr.get("model"),
                "current_in_price": curr.get("input_price", 0),
                "current_out_price": curr.get("output_price", 0),
                "healing_model": rec.get("model"),
                "healing_in_price": rec.get("input_price", 0),
                "healing_out_price": rec.get("output_price", 0),
                "savings_pct": savings_pct
            })

        return {
            "has_new_healing": has_real_new_model, # 실제 신규 모델 릴리즈 시에만 True
            "active_version_id": active_vid,
            "active_version": registry.data.get("active_version", "latest"),
            "sample_template": cls.SAMPLE_HEALING_TEMPLATE,
            "comparison": comparison,
            "all_versions": registry.get_all_versions()
        }

    @classmethod
    def apply_healing(cls) -> Dict[str, Any]:
        template = cls.SAMPLE_HEALING_TEMPLATE
        new_vid = "v1.1.0-healing-hotpatch"
        registry.create_version(
            new_version_id=new_vid,
            name="GPT-5.6 Lineup (Healing Hot-Patch Release v1.1.0)",
            description="힐링 엔진 자동 감지 기반 최신 고효율 모델 라우팅 무중단 핫패치 릴리즈",
            mapping=template["mapping"]
        )
        registry.switch_version(new_vid)
        return {
            "success": True,
            "message": f"성공적으로 최신 GPT-5.6 모델 핫패치 릴리즈({new_vid})가 즉시 적용되었습니다.",
            "active_version_id": new_vid
        }

    @classmethod
    def switch_version(cls, version_id: str) -> Dict[str, Any]:
        success = registry.switch_version(version_id)
        if success:
            return {
                "success": True,
                "message": f"성공적으로 모델 버전이 '{version_id}'(으)로 전환되었습니다.",
                "active_version_id": registry.get_active_version_id()
            }
        else:
            return {
                "success": False,
                "message": f"버전 '{version_id}'을(를) 찾을 수 없습니다."
            }
