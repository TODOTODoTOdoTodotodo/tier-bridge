import os
from datetime import datetime
from typing import Dict, Any, List
from src.tierbridge.model_registry import registry

class HealingEngine:
    """
    Model Healing Factor Engine:
    - 신규 저비용/고성능 업스트림 모델 단가 감지
    - 기존 매핑 대비 비용 및 성능 비교표 도출
    - 원클릭 핫패치 릴리즈 (신규 스냅샷 생성)
    """

    # 업스트림에서 새로 감지된 차세대 저비용/고출력 추천 힐링 라우팅 템플릿
    RECOMMENDED_HEALING_TEMPLATE = {
        "version_id": "v1.1.0-healing",
        "name": "Healing Update v1.1.0 (GPT-5.6 Luna-v2 & Terra Cost Optimization)",
        "description": "LUNA 저비용 모델 단가 40% 인하 패치 및 TERRA 최적화 스냅샷 적용",
        "mapping": {
            "LUNA:LOW": {"model": "gpt-5.6-luna-v2", "effort": "low", "input_price": 0.60, "output_price": 1.80},
            "LUNA:MEDIUM": {"model": "gpt-5.6-luna-v2", "effort": "medium", "input_price": 0.60, "output_price": 1.80},
            "TERRA:MEDIUM": {"model": "gpt-5.6-terra", "effort": "medium", "input_price": 2.0, "output_price": 8.0},
            "TERRA:HIGH": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.0, "output_price": 8.0},
            "SOL:EXTRA_HIGH": {"model": "gpt-5.6-sol", "effort": "xhigh", "input_price": 4.5, "output_price": 18.0}
        }
    }

    @classmethod
    def get_healing_status(cls) -> Dict[str, Any]:
        active_mapping = registry.get_active_mapping()
        rec_mapping = cls.RECOMMENDED_HEALING_TEMPLATE["mapping"]
        active_vid = registry.get_active_version_id()

        # 힐링 가능 여부 판단 (추천 템플릿 모델이 현재 활성 버전에 적용되지 않은 경우)
        has_new_healing = False
        if active_mapping.get("LUNA:LOW", {}).get("model") != rec_mapping["LUNA:LOW"]["model"]:
            has_new_healing = True

        # 비교표 생성
        comparison = []
        for tier in ["LUNA:LOW", "LUNA:MEDIUM", "TERRA:MEDIUM", "TERRA:HIGH", "SOL:EXTRA_HIGH"]:
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
            "has_new_healing": has_new_healing,
            "active_version_id": active_vid,
            "active_version": registry.data.get("active_version", "latest"),
            "healing_template": cls.RECOMMENDED_HEALING_TEMPLATE,
            "comparison": comparison,
            "all_versions": registry.get_all_versions()
        }

    @classmethod
    def apply_healing(cls) -> Dict[str, Any]:
        template = cls.RECOMMENDED_HEALING_TEMPLATE
        new_vid = registry.create_version(
            new_version_id=template["version_id"],
            name=template["name"],
            description=template["description"],
            mapping=template["mapping"]
        )
        return {
            "success": True,
            "message": f"성공적으로 신규 힐링 스냅샷 ({new_vid})이 핫패치 되었습니다.",
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
