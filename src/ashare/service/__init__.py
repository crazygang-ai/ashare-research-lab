"""Phase 4 local service package for ashare-research-lab."""

__all__ = ["create_app"]


def __getattr__(name: str) -> object:
    if name == "create_app":
        from ashare.service.app import create_app

        return create_app
    raise AttributeError(name)
