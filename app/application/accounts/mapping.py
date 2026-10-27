"""Reexporta mapeamentos do Model de conta para compatibilidade."""
from app.models.account import AccountIdentity, UserAccountModel, build_account_identity, build_user_account, map_identity, map_user

__all__ = [
    "AccountIdentity",
    "UserAccountModel",
    "build_account_identity",
    "build_user_account",
    "map_identity",
    "map_user",
]
