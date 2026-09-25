import os
import pytest
from asx_bulk.config import require_terms_acknowledgement

def test_terms_gate_blocks_without_ack(monkeypatch):
    monkeypatch.delenv("ASX_ACKNOWLEDGE_TERMS", raising=False)
    with pytest.raises(RuntimeError):
        require_terms_acknowledgement()

def test_terms_gate_allows_explicit_ack(monkeypatch):
    monkeypatch.setenv("ASX_ACKNOWLEDGE_TERMS", "1")
    require_terms_acknowledgement()
