from canada_zeta_bulk.util import in_shard

def test_shards_are_disjoint_and_complete():
    keys=[f"XTSE:X{i}" for i in range(100)]
    buckets=[[k for k in keys if in_shard(k,4,j)] for j in range(4)]
    assert sorted(sum(buckets,[]))==sorted(keys)
    assert sum(map(len,buckets))==len(set(sum(buckets,[])))
