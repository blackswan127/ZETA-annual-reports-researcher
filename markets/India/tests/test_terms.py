import pytest
from india_ar_bulk.config import require_terms_acknowledgement

def test_terms_gate(monkeypatch):
    monkeypatch.delenv('INDIA_AR_ACKNOWLEDGE_TERMS',raising=False)
    with pytest.raises(RuntimeError): require_terms_acknowledgement()
    monkeypatch.setenv('INDIA_AR_ACKNOWLEDGE_TERMS','1'); require_terms_acknowledgement()
