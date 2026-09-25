from lka_cse_bulk.downloader import Downloader

def test_html_rejected(tmp_path):
 p=tmp_path/'x.pdf';p.write_bytes(b'<html>blocked</html>'*2000)
 try:Downloader.validate_pdf(p);assert False
 except ValueError:pass
def test_small_rejected(tmp_path):
 p=tmp_path/'x.pdf';p.write_bytes(b'%PDF-1.4\n%%EOF')
 try:Downloader.validate_pdf(p);assert False
 except ValueError:pass
