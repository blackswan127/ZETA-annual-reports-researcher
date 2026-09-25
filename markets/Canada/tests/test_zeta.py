from pathlib import Path
import pytest
from canada_zeta_bulk.models import Issuer
from canada_zeta_bulk.zeta import final_path, filename, identifiers_complete

def issuer(**kw):
    d=dict(issuer_key="XTSE:RY",name="Royal Bank of Canada",ticker="RY",exchange_mic="XTSE",isin="CA7800871021",lei="ES7IP3U3RHIGC71XBU11")
    d.update(kw); return Issuer(**d)

def test_exact_zeta_path():
    p=final_path(Path("ROOT"),issuer(),2024)
    assert str(p).replace('\\','/').endswith("CAN/XTSE/ES7IP3U3RHIGC71XBU11_CA7800871021_RY/FY2024/ES7IP3U3RHIGC71XBU11_CAN_XTSE_RY_CA7800871021_FY2024_AR_EN.pdf")

def test_missing_identifier_cannot_enter_final_tree():
    x=issuer(lei="")
    assert not identifiers_complete(x)
    with pytest.raises(ValueError): filename(x,2024)
