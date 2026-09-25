from india_ar_bulk.util import normalize_isin,safe_name,shard_match,infer_kind

def test_utils():
    assert normalize_isin('INE002A01018')=='INE002A01018'; assert normalize_isin('bad')==''
    assert '/' not in safe_name('A/B:C*'); assert infer_kind('https://x/a.zip?x=1')=='ZIP'; assert infer_kind('https://x/a.pdf')=='PDF'

def test_shards_partition():
    hits=[i for i in range(4) if shard_match('INE002A01018',4,i)]; assert len(hits)==1
