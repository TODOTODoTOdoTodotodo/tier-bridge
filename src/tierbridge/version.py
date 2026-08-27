# src/tierbridge/version.py
import os


def _read_version():
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    # Single Source of Truth: 루트 VERSION 파일 탐색
    candidates = [
        os.path.join(cur_dir, "..", "..", "VERSION"),  # dev root
        os.path.join(cur_dir, "..", "VERSION"),
        os.path.join(cur_dir, "VERSION"),
        os.path.expanduser("~/.tierbridge/live/VERSION")
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    v = f.read().strip()
                    if v:
                        return v
            except Exception:
                pass
    return "0.1.1"


__version__ = _read_version()
__release_name__ = "TierBridge Core"
__release_date__ = "2026-08-27"


def get_version_info() -> dict:
    """ TierBridge 애플리케이션 버전 정보를 반환합니다. """
    v = _read_version()
    return {
        "version": v,
        "tag": f"v{v}",
        "name": __release_name__,
        "release_date": __release_date__
    }
