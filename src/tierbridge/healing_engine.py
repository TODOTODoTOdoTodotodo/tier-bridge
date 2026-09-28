import os
import json
import time
import urllib.request
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    from src.tierbridge.model_registry import registry
except ImportError:
    from tierbridge.model_registry import registry

try:
    from src.tierbridge.official_pricing_crawler import OfficialPricingCrawler
except ImportError:
    from tierbridge.official_pricing_crawler import OfficialPricingCrawler

class HealingEngine:
    """
    Model Healing Factor Engine:
    - 실제 OpenAI 업스트림 API(https://chatgpt.com/backend-api/codex/models?client_version=1.0.0) 동적 감지
    - 활성 버전 대비 신규 세대(GPT-6) 모델 릴리즈 실시간 탐지 (has_new_healing: True/False)
    - 데모 샘플 핫패치 테스트 분리 (Sample Demo Template)
    - 최신 업스트림 모델 기반 동적 핫패치 제안 및 단가 비교표 도출
    - 무중단 핫패치 릴리즈 & 스냅샷 생성
    """

    _upstream_cache = {
        "timestamp": 0.0,
        "models": []
    }
    CACHE_TTL_SECONDS = 60.0

    # 데모/체험 테스트용 샘플 템플릿 (모의 테스트 버튼용)
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
    def fetch_upstream_models(cls, force: bool = False) -> List[Dict[str, Any]]:
        """
        OpenAI 업스트림 백엔드 엔드포인트에서 가용 모델 목록을 실시간 동적 조회합니다.
        잦은 폴링으로 인한 지연/부하 방지를 위해 60초 TTL 메모리 캐시를 적용합니다.
        """
        now = time.time()
        if not force and (now - cls._upstream_cache["timestamp"] < cls.CACHE_TTL_SECONDS):
            if cls._upstream_cache["models"]:
                return cls._upstream_cache["models"]

        auth_path = os.path.expanduser("~/.codex/auth.json")
        if not os.path.exists(auth_path):
            return cls._upstream_cache["models"]

        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                auth_data = json.load(f)
            tokens = auth_data.get("tokens", {})
            token = tokens.get("access_token")
            account_id = tokens.get("account_id")

            if not token:
                return cls._upstream_cache["models"]

            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            if account_id:
                headers["chatgpt-account-id"] = account_id

            url = "https://chatgpt.com/backend-api/codex/models?client_version=1.0.0"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = data.get("models", [])
                    if models:
                        cls._upstream_cache = {
                            "timestamp": now,
                            "models": models
                        }
                        return models
        except Exception:
            pass

        return cls._upstream_cache["models"]

    @classmethod
    def get_dynamic_recommendation(
        cls, 
        upstream_models: List[Dict[str, Any]], 
        active_mapping: Dict[str, Any], 
        active_vid: str
    ) -> Dict[str, Any]:
        """
        업스트림 가용 모델 목록과 현재 활성 모델 매핑을 비교 분석하여,
        동적으로 최적 핫패치 추천 매핑 및 릴리즈 버전을 생성합니다.
        """
        upstream_slugs = {m.get("slug"): m for m in upstream_models if m.get("slug")}
        
        # 업스트림 가용 모델 세대 확인
        has_upstream_gpt6 = any("gpt-6" in slug for slug in upstream_slugs)
        has_upstream_gpt56 = any("gpt-5.6" in slug for slug in upstream_slugs)
        
        # 현재 활성 버전 모델 세대 확인
        active_model_names = [m.get("model", "") for m in active_mapping.values()]
        is_active_gpt6 = any("gpt-6" in m for m in active_model_names) or "gpt6" in active_vid.lower()
        is_legacy = (
            any(m in ["gpt-5.4-mini", "gpt-5.5"] for m in active_model_names)
            or "test" in active_vid.lower() 
            or "legacy" in active_vid.lower()
        )

        # 1. 업스트림에 GPT-6가 존재하고, 현재 활성 버전이 GPT-6가 아닌 경우 -> GPT-6 핫패치 제안!
        if has_upstream_gpt6 and not is_active_gpt6:
            has_new_healing = True
            rec_vid = "v2.0.0-gpt6-hotpatch"
            rec_name = "GPT-6 Lineup (Dynamic Upstream Hot-Patch Release v2.0.0)"
            rec_desc = "실제 OpenAI 업스트림 백엔드 감지 및 공식 단가 기반 GPT-6(Sol/Luna) 무중단 핫패치 릴리즈"
            
            luna_model = "gpt-6-luna" if "gpt-6-luna" in upstream_slugs else "gpt-5.6-luna"
            sol_model = "gpt-6-sol" if "gpt-6-sol" in upstream_slugs else "gpt-5.6-sol"

            luna_in, luna_out = OfficialPricingCrawler.get_price(luna_model, 0.10, 0.50)
            sol_in, sol_out = OfficialPricingCrawler.get_price(sol_model, 2.00, 10.00)

            rec_mapping = {
                "BRONZE": {"model": luna_model, "effort": "low", "input_price": luna_in, "output_price": luna_out},
                "SILVER": {"model": luna_model, "effort": "medium", "input_price": luna_in, "output_price": luna_out},
                "GOLD": {"model": sol_model, "effort": "low", "input_price": sol_in, "output_price": sol_out},
                "PLATINUM": {"model": sol_model, "effort": "medium", "input_price": sol_in, "output_price": sol_out},
                "DIAMOND": {"model": sol_model, "effort": "high", "input_price": sol_in, "output_price": sol_out},
                "CHALLENGER": {"model": sol_model, "effort": "xhigh", "input_price": sol_in, "output_price": sol_out}
            }
        # 2. 업스트림에 GPT-5.6이 있고 현재 버전이 구형(Legacy/Test)인 경우 -> GPT-5.6 핫패치 제안
        elif has_upstream_gpt56 and is_legacy:
            has_new_healing = True
            rec_vid = "v1.1.0-healing-hotpatch"
            rec_name = "GPT-5.6 Lineup (Healing Hot-Patch Release v1.1.0)"
            rec_desc = "힐링 엔진 자동 감지 기반 최신 고효율 모델 라우팅 무중단 핫패치 릴리즈"
            rec_mapping = cls.SAMPLE_HEALING_TEMPLATE["mapping"]
        # 3. 그 외 (이미 최신 버전 적용 완료 상태)
        else:
            has_new_healing = False
            rec_vid = active_vid
            rec_name = "Up-to-date"
            rec_desc = "현재 최신 업스트림 모델 매핑이 적용되어 있습니다."
            rec_mapping = active_mapping

        return {
            "has_new_healing": has_new_healing,
            "version_id": rec_vid,
            "name": rec_name,
            "description": rec_desc,
            "mapping": rec_mapping
        }

    @classmethod
    def get_healing_status(cls) -> Dict[str, Any]:
        active_mapping = registry.get_active_mapping()
        active_vid = registry.get_active_version_id()
        
        # 실제 업스트림 모델 목록 동적 조회
        upstream_models = cls.fetch_upstream_models()
        
        # 동적 제안 도출
        rec = cls.get_dynamic_recommendation(upstream_models, active_mapping, active_vid)
        rec_mapping = rec["mapping"]

        # 단가 및 절감율 비교표 동적 생성
        comparison = []
        for tier in ["BRONZE", "SILVER", "GOLD", "PLATINUM", "DIAMOND", "CHALLENGER"]:
            curr = active_mapping.get(tier, {"model": "N/A", "input_price": 0, "output_price": 0})
            target = rec_mapping.get(tier, {"model": "N/A", "input_price": 0, "output_price": 0})
            
            curr_avg_price = (curr.get("input_price", 0) + curr.get("output_price", 0)) / 2.0
            rec_avg_price = (target.get("input_price", 0) + target.get("output_price", 0)) / 2.0
            
            savings_pct = 0.0
            if curr_avg_price > 0:
                savings_pct = round(((curr_avg_price - rec_avg_price) / curr_avg_price) * 100, 1)

            comparison.append({
                "tier": tier,
                "current_model": curr.get("model"),
                "current_in_price": curr.get("input_price", 0),
                "current_out_price": curr.get("output_price", 0),
                "healing_model": target.get("model"),
                "healing_in_price": target.get("input_price", 0),
                "healing_out_price": target.get("output_price", 0),
                "savings_pct": savings_pct
            })

        return {
            "has_new_healing": rec["has_new_healing"],
            "active_version_id": active_vid,
            "active_version": registry.data.get("active_version", "latest"),
            "sample_template": cls.SAMPLE_HEALING_TEMPLATE,
            "dynamic_proposal": rec,
            "upstream_model_count": len(upstream_models),
            "official_pricing": OfficialPricingCrawler.load_prices(),
            "comparison": comparison,
            "all_versions": registry.get_all_versions()
        }

    @classmethod
    def apply_healing(cls) -> Dict[str, Any]:
        active_mapping = registry.get_active_mapping()
        active_vid = registry.get_active_version_id()
        upstream_models = cls.fetch_upstream_models()
        rec = cls.get_dynamic_recommendation(upstream_models, active_mapping, active_vid)

        new_vid = rec["version_id"]
        registry.create_version(
            new_version_id=new_vid,
            name=rec["name"],
            description=rec["description"],
            mapping=rec["mapping"]
        )
        registry.switch_version(new_vid)
        return {
            "success": True,
            "message": f"성공적으로 최신 업스트림 모델 핫패치 릴리즈({new_vid})가 즉시 적용되었습니다.",
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
