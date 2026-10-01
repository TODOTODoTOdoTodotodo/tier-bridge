import os
import json
import time
import urllib.request
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

class OfficialPricingCrawler:
    """
    OpenAI 공식 모델 단가 주기적 크롤러 및 동기화 관리자:
    - OpenAI 공식 개발자 가격 피드를 동적으로 조회하여 실시간 단가 수집
    - 로컬 영구 설정(config/official_prices.json) 듀얼 싱크 저장
    - 6시간 주기 백그라운드 갱신 및 Fallback 안전 장치
    """

    PRICING_FEED_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
    TTL_SECONDS = 21600.0  # 6시간 (초 단위)

    DEFAULT_OFFICIAL_PRICES = {
        "gpt-6.1-sol": {"input_price": 2.00, "output_price": 10.00},
        "gpt-6-luna": {"input_price": 0.10, "output_price": 0.50},
        "gpt-6-sol": {"input_price": 2.00, "output_price": 10.00},
        "gpt-6-astra": {"input_price": 10.00, "output_price": 50.00},
        "gpt-5.6-luna": {"input_price": 1.00, "output_price": 3.00},
        "gpt-5.6-terra": {"input_price": 2.50, "output_price": 10.00},
        "gpt-5.6-sol": {"input_price": 5.00, "output_price": 20.00},
        "gpt-5.5": {"input_price": 3.00, "output_price": 12.00},
        "gpt-5.4-mini": {"input_price": 0.15, "output_price": 0.60}
    }

    _cache_data: Optional[Dict[str, Any]] = None

    @classmethod
    def get_config_paths(cls) -> list:
        paths = []
        live_path = os.path.expanduser("~/.tierbridge/live/config/official_prices.json")
        dev_dir = os.environ.get("TIERBRIDGE_DEV_DIR", os.getcwd())
        dev_path = os.path.join(dev_dir, "config", "official_prices.json")
        
        # 1순위: 라이브 런타임, 2순위: 개발 디렉토리
        paths.append(live_path)
        if dev_path not in paths:
            paths.append(dev_path)
        return paths

    @classmethod
    def load_prices(cls) -> Dict[str, Any]:
        if cls._cache_data:
            return cls._cache_data

        for path in cls.get_config_paths():
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data and "prices" in data:
                        cls._cache_data = data
                        return data
                except Exception:
                    pass

        # 파일이 없을 경우 기본값으로 초기화
        initial_data = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "default_fallback",
            "prices": cls.DEFAULT_OFFICIAL_PRICES.copy()
        }
        cls._cache_data = initial_data
        cls.save_prices(initial_data)
        return initial_data

    @classmethod
    def save_prices(cls, data: Dict[str, Any]):
        cls._cache_data = data
        for path in cls.get_config_paths():
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    @classmethod
    def sync_prices(cls, force: bool = False) -> Dict[str, Any]:
        """
        원격 공식 가격 피드를 크롤링하여 최신 단가표를 갱신합니다.
        force가 False일 때 마지막 갱신 시각으로부터 TTL(6시간)이 지나지 않았으면 캐시를 반환합니다.
        """
        current_data = cls.load_prices()
        
        if not force:
            last_updated_str = current_data.get("updated_at")
            if last_updated_str:
                try:
                    dt = datetime.strptime(last_updated_str, "%Y-%m-%d %H:%M:%S")
                    if (datetime.now() - dt).total_seconds() < cls.TTL_SECONDS:
                        return {
                            "success": True,
                            "cached": True,
                            "updated_at": last_updated_str,
                            "prices": current_data.get("prices", {})
                        }
                except Exception:
                    pass

        try:
            req = urllib.request.Request(cls.PRICING_FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    
                    target_models = [
                        "gpt-6.1-sol", "gpt-6-luna", "gpt-6-sol", "gpt-6-astra", 
                        "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", 
                        "gpt-5.5", "gpt-5.4-mini"
                    ]
                    updated_prices = current_data.get("prices", cls.DEFAULT_OFFICIAL_PRICES.copy())

                    for m in target_models:
                        candidates = [m, f"openai/{m}", f"azure_ai/{m}", f"azure/{m}"]
                        found = None
                        for c in candidates:
                            if c in raw_data and (raw_data[c].get("input_cost_per_token") is not None or raw_data[c].get("output_cost_per_token") is not None):
                                found = raw_data[c]
                                break
                        if found:
                            in_cost = round((found.get("input_cost_per_token") or 0.0) * 1_000_000, 4)
                            out_cost = round((found.get("output_cost_per_token") or 0.0) * 1_000_000, 4)
                            updated_prices[m] = {
                                "input_price": in_cost,
                                "output_price": out_cost
                            }

                    new_data = {
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "source": cls.PRICING_FEED_URL,
                        "prices": updated_prices
                    }
                    cls.save_prices(new_data)
                    return {
                        "success": True,
                        "cached": False,
                        "updated_at": new_data["updated_at"],
                        "prices": updated_prices
                    }
        except Exception as e:
            # 원격 통신 실패 시 기존 로컬 캐시 유지
            return {
                "success": False,
                "error": str(e),
                "cached": True,
                "updated_at": current_data.get("updated_at"),
                "prices": current_data.get("prices", {})
            }

        return {
            "success": True,
            "cached": True,
            "updated_at": current_data.get("updated_at"),
            "prices": current_data.get("prices", {})
        }

    @classmethod
    def get_price(cls, model_name: str, fallback_in: float = 1.0, fallback_out: float = 3.0) -> Tuple[float, float]:
        """
        특정 모델의 공식 1M 토큰당 입력/출력 단가를 반환합니다.
        """
        data = cls.load_prices()
        prices = data.get("prices", {})
        
        # 1. 완전 일치 탐색
        if model_name in prices:
            p = prices[model_name]
            return float(p.get("input_price", fallback_in)), float(p.get("output_price", fallback_out))

        # 2. 모델 슬러그 부분 일치 탐색 (e.g. gpt-6-sol-pro -> gpt-6-sol)
        for k, p in prices.items():
            if k in model_name or model_name in k:
                return float(p.get("input_price", fallback_in)), float(p.get("output_price", fallback_out))

        return fallback_in, fallback_out
