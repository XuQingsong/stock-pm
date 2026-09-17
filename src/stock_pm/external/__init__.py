"""External Intelligence Layer. Discovery providers are not publishers."""

from .types import ExternalDocument, ProviderAudit

__all__ = ["gather_external_intelligence", "ExternalDocument", "ProviderAudit"]


def __getattr__(name: str):
    if name == "gather_external_intelligence":
        from .layer import gather_external_intelligence

        return gather_external_intelligence
    raise AttributeError(name)
