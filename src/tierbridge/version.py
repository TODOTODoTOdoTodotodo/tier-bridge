# src/tierbridge/version.py
__version__ = "0.1.1"
__release_name__ = "TierBridge Core"
__release_date__ = "2026-08-27"


def get_version_info() -> dict:
    """ TierBridge 애플리케이션 버전 정보를 반환합니다. """
    return {
        "version": __version__,
        "tag": f"v{__version__}",
        "name": __release_name__,
        "release_date": __release_date__
    }
