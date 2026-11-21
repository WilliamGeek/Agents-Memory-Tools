"""检索延迟基准：分段耗时 + 端到端 + 并发吞吐。
用法：python tools\\bench_search.py
前提：无需起服务，直接调用 web_app 的 GLOBAL_FTS_MGR。
"""
import os
import statistics
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import web_app as w  # noqa: E402

QUERIES = ["会话", "错误", "Bio-Panorama", "PowerShell", "记忆"]


def main():
    db = str(w.FTS_DB_PATH)
    size = os.path.getsize(db)
    st = w.GLOBAL_FTS_MGR.get_stats()
    print("FTS 库 %.1f MB | 行 %s | 文件 %s" % (size / 1024 / 1024, format(st["indexed_turns"], ","), st["indexed_files"]))

    print("\n=== 端到端（SessionFTSManager.search，20 次中位数）===")
    for q in QUERIES:
        lat = [w.GLOBAL_FTS_MGR.search(q, 50)["latency_ms"] for _ in range(20)]
        print("%-14s 中位 %5.2f ms  最慢 %5.2f ms" % (q, statistics.median(lat), max(lat)))

    print("\n=== 并发吞吐（4 线程 × 25 次）===")
    errs = []

    def worker():
        try:
            for i in range(25):
                w.GLOBAL_FTS_MGR.search(QUERIES[i % len(QUERIES)], 50)
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))

    t0 = time.time()
    th = [threading.Thread(target=worker) for _ in range(4)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    el = time.time() - t0
    print("100 次查询 %.2fs → %.1f QPS，错误 %d" % (el, 100 / el, len(errs)))


if __name__ == "__main__":
    main()
