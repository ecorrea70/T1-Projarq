"""Corpos das requisições HTTP."""
from pydantic import BaseModel


class SyncRequest(BaseModel):
    dry_run: bool = True
