from asx_bulk.models import Issuer
from asx_bulk.util import safe_name

def test_safe_filename():
    assert safe_name('ACME: HOLDINGS / LTD*') == 'ACME_ HOLDINGS _ LTD_'

def test_issuer_model():
    i = Issuer("BHP", "BHP GROUP LIMITED", "Materials")
    assert i.ticker == "BHP"
