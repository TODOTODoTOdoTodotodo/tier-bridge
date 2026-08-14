import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

def get_config_path() -> str:
    env_path = os.getenv("MODEL_VERSIONS_CONFIG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    
    # 개발 레포 / 런타임 디렉토리 상위 탐색
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dev_path = os.path.join(base_dir, "config", "model_versions.json")
    if os.path.exists(dev_path):
        return dev_path

    live_path = os.path.expanduser("~/.tierbridge/live/config/model_versions.json")
    if os.path.exists(live_path):
        return live_path

    return dev_path

class ModelRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelRegistry, cls).__new__(cls)
            cls._instance._init_registry()
        return cls._instance

    def _init_registry(self):
        self.config_path = get_config_path()
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        if not os.path.exists(self.config_path):
            self._write_default_config()
        self.data = self._load_config()

    def _write_default_config(self):
        default_data = {
            "active_version": "latest",
            "latest_version_id": "v1.0.0",
            "versions": {
                "v1.0.0": {
                    "version_id": "v1.0.0",
                    "name": "Standard Baseline v1.0.0 (GPT-5.6 Lineup)",
                    "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "description": "초기 기본 표준 모델 라우팅 스냅샷",
                    "mapping": {
                        "LUNA:LOW": {"model": "gpt-5.6-luna", "effort": "low", "input_price": 1.0, "output_price": 3.0},
                        "LUNA:MEDIUM": {"model": "gpt-5.6-luna", "effort": "medium", "input_price": 1.0, "output_price": 3.0},
                        "TERRA:MEDIUM": {"model": "gpt-5.6-terra", "effort": "medium", "input_price": 2.5, "output_price": 10.0},
                        "TERRA:HIGH": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.5, "output_price": 10.0},
                        "SOL:EXTRA_HIGH": {"model": "gpt-5.6-sol", "effort": "xhigh", "input_price": 5.0, "output_price": 20.0}
                    }
                }
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(default_data, f, indent=2, ensure_ascii=False)

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to load model_versions.json: {e}")
            self._write_default_config()
            return self._load_config()

    def _save_config(self):
        # 1. Primary config_path 저장
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Error] Failed to save model_versions.json: {e}")

        # 2. 배포 시 설정 유지(Deployment Preservation)를 위한 개발 저장소 <-> 런타임 저장소 양방향 영구 저장
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        dev_target = os.path.join(base_dir, "config", "model_versions.json")
        live_target = os.path.expanduser("~/.tierbridge/live/config/model_versions.json")
        
        for target in [dev_target, live_target]:
            if os.path.abspath(target) != os.path.abspath(self.config_path):
                try:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "w", encoding="utf-8") as f:
                        json.dump(self.data, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass

    def get_active_version_id(self) -> str:
        self.data = self._load_config()
        active = self.data.get("active_version", "latest")
        if active == "latest":
            return self.data.get("latest_version_id", "v1.0.0")
        return active

    def get_active_mapping(self) -> Dict[str, Any]:
        self.data = self._load_config()
        version_id = self.get_active_version_id()
        versions = self.data.get("versions", {})
        if version_id in versions:
            return versions[version_id].get("mapping", {})
        # fallback to first version
        first_key = list(versions.keys())[0] if versions else "v1.0.0"
        return versions.get(first_key, {}).get("mapping", {})

    def get_all_versions(self) -> List[Dict[str, Any]]:
        self.data = self._load_config()
        versions_dict = self.data.get("versions", {})
        active = self.data.get("active_version", "latest")
        latest_id = self.data.get("latest_version_id", "v1.0.0")
        
        result = []
        for vid, vdata in versions_dict.items():
            is_active = (active == "latest" and vid == latest_id) or (active == vid)
            result.append({
                "version_id": vid,
                "name": vdata.get("name"),
                "updated_at": vdata.get("updated_at"),
                "description": vdata.get("description"),
                "is_active": is_active,
                "is_latest": (vid == latest_id),
                "mapping": vdata.get("mapping")
            })
        return sorted(result, key=lambda x: x["version_id"], reverse=True)

    def switch_version(self, version_id: str) -> bool:
        versions = self.data.get("versions", {})
        if version_id == "latest":
            self.data["active_version"] = "latest"
            self._save_config()
            return True
        if version_id in versions:
            self.data["active_version"] = version_id
            self._save_config()
            return True
        return False

    def create_version(self, new_version_id: str, name: str, description: str, mapping: Dict[str, Any]) -> str:
        self.data["versions"][new_version_id] = {
            "version_id": new_version_id,
            "name": name,
            "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "description": description,
            "mapping": mapping
        }
        self.data["latest_version_id"] = new_version_id
        self.data["active_version"] = "latest"
        self._save_config()
        return new_version_id

# Global Registry Instance
registry = ModelRegistry()
