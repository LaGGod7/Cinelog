import threading

from app.dsa.aho_corasick import AhoCorasick
from app.dsa.feed import cosine, merge_feeds
from app.dsa.inverted_index import InvertedIndex
from app.dsa.lru import LRUCache
from app.dsa.trie import Trie
from app.scheduler.pool import BATCH, USER, BoundedPriorityQueue, Job, QueueFull, WorkerPool


def test_trie_prefix_and_word_boundary():
    t = Trie(k=3)
    t.insert("The Dark Knight", 1, 90)
    t.insert("Dark City", 2, 50)
    t.insert("Darkest Hour", 3, 70)
    t.insert("Dark Waters", 4, 10)
    assert t.search("da") == [1, 3, 2]  # best popularity first, capped at k
    assert t.search("dark kn") == [1]
    assert t.search("zzz") == []
    assert t.search("The Dark")[0] == 1


def test_inverted_index_and_filters():
    ix = InvertedIndex()
    ix.add(1, {"title": "Inception", "overview": "dream heist"}, year=2010, genres=["Sci-Fi"], cast=["Leonardo DiCaprio"], popularity=90)
    ix.add(2, {"title": "Heat", "overview": "heist crew detective"}, year=1995, genres=["Crime"], cast=["Al Pacino"], popularity=70)
    ix.add(3, {"title": "Dream House", "overview": "family"}, year=2011, genres=["Thriller"], cast=["Daniel Craig"], popularity=5)
    assert set(ix.search("heist")) == {1, 2}
    assert ix.search("heist", genre="crime") == [2]
    assert ix.search("", cast="pacino") == [2]
    assert ix.search("dream heist") == [1]
    assert ix.search("heist", year=2010) == [1]
    assert ix.search("nothing") == []


def test_aho_corasick_one_pass_whole_words():
    ac = AhoCorasick.from_terms([("he", "a"), ("she", "b"), ("his", "c"), ("hers", "d"), ("rosebud", "plot")])
    found = {(h[2]) for h in ac.search("ushers: she said rosebud", whole_words=True)}
    assert found == {"she", "rosebud"}
    found_sub = {h[2] for h in ac.search("ushers", whole_words=False)}
    assert {"she", "he", "hers"} <= found_sub
    hit = ac.search("The twist: Rosebud!")[0]
    assert hit[:3] == (11, 18, "rosebud")


def test_lru_eviction_order():
    c = LRUCache(2)
    c.put("a", 1); c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)  # evicts b
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3
    assert c.keys_mru_first() == ["c", "a"]


def test_feed_merge_and_cosine():
    f1 = [{"at": 9, "u": 1}, {"at": 3, "u": 1}]
    f2 = [{"at": 8, "u": 2}, {"at": 7, "u": 2}, {"at": 1, "u": 2}]
    assert [x["at"] for x in merge_feeds([f1, f2], 4)] == [9, 8, 7, 3]
    sim, n = cosine({1: 5, 2: 4, 3: 1}, {1: 5, 2: 4, 3: 1})
    assert abs(sim - 1) < 1e-9 and n == 3


def test_queue_priority_and_bounds():
    q = BoundedPriorityQueue(2)
    q.put(Job("batch", lambda: 0, BATCH)); q.put(Job("user", lambda: 0, USER))
    try:
        q.put(Job("x", lambda: 0), timeout=0.05)
        raise AssertionError("expected QueueFull")
    except QueueFull:
        pass
    assert q.get().name == "user" and q.get().name == "batch"


def test_pool_runs_all_jobs_retries_and_no_loss():
    pool = WorkerPool(workers=4, capacity=32, backoff_base=0.01).start()
    done, lock = [], threading.Lock()
    flaky = {"n": 0}

    def ok(i):
        def f():
            with lock:
                done.append(i)
        return f

    def flaky_fn():
        flaky["n"] += 1
        if flaky["n"] < 3:
            raise RuntimeError("boom")

    for i in range(200):
        pool.submit(Job(f"j{i}", ok(i), USER if i % 2 else BATCH))
    pool.submit(Job("flaky", flaky_fn, USER, max_retries=3))
    pool.submit(Job("dead", lambda: 1 / 0, USER, max_retries=1))
    assert pool.wait_idle(15)
    pool.shutdown()
    assert sorted(done) == list(range(200))  # no lost jobs
    assert flaky["n"] == 3
    assert pool.failed_jobs == ["dead"]
    assert pool.stats["done"] == 201 and pool.stats["failed"] == 1


def test_user_jobs_run_before_batch_jobs():
    pool = WorkerPool(workers=1, capacity=64)
    order = []
    for i in range(5):
        pool.submit(Job(f"b{i}", lambda i=i: order.append(("b", i)), BATCH))
    for i in range(3):
        pool.submit(Job(f"u{i}", lambda i=i: order.append(("u", i)), USER))
    pool.start()
    assert pool.wait_idle(10)
    pool.shutdown()
    assert [k for k, _ in order[:3]] == ["u", "u", "u"]
