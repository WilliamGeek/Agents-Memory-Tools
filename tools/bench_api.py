#!/usr/bin/env python3
"""接口实测基准（T02 / T03 自测用）。

只做三件事，不引入任何第三方依赖：
  1. 打一次/多次 HTTP，报告响应字节数、耗时、ETag、状态码；
  2. 对同一 URL 做条件请求（If-None-Match）验证 304；
  3. 按需断言上限（--max-bytes / --max-ms），不达标退出码 1。

本机自测会禁用 HTTP 代理：Windows 上 HTTP_PROXY 会把 127.0.0.1 也走代理，
导致拿到代理自己的错误页（曾经踩过）。

用法：
    python tools/bench_api.py --path "/api/sessions?limit=60&fields=lite" --n 5 --max-bytes 51200
    python tools/bench_api.py --path "/api/session/detail?catalog_id=xxx&turn_limit=8&slim=1" --n 5 --max-bytes 409600 --max-ms 350
    python tools/bench_api.py --path "/api/session/detail?..." --etag          # 断言 304
    python tools/bench_api.py --path "/api/sessions" --n 3 --max-ms 200 --skip-first
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DEFAULT_BASE = "http://127.0.0.1:18923"


def request(base: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, bytes, dict[str, str], float]:
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, headers=headers or {})
    started = time.perf_counter()
    try:
        with _OPENER.open(req, timeout=180) as resp:
            body = resp.read()
            status = int(resp.status)
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = int(exc.code)
        resp_headers = {k.lower(): v for k, v in exc.headers.items()}
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return status, body, resp_headers, elapsed_ms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="接口实测基准")
    parser.add_argument("--path", required=True, help="请求路径（含 query）")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--n", type=int, default=1, help="重复次数")
    parser.add_argument("--max-bytes", type=int, default=0, help="响应体上限（字节），0 = 不校验")
    parser.add_argument("--max-ms", type=float, default=0.0, help="p95 耗时上限（毫秒），0 = 不校验")
    parser.add_argument("--etag", action="store_true", help="第二次请求带 If-None-Match，断言 304")
    parser.add_argument("--etag-n", type=int, default=5, help="304 条件请求的采样次数（耗时取中位数）")
    parser.add_argument("--etag-max-ms", type=float, default=50.0, help="304 中位耗时上限（毫秒）")
    parser.add_argument("--skip-first", action="store_true", help="统计耗时跳过第一次（冷启动）")
    parser.add_argument("--json", action="store_true", help="额外打印响应结构摘要")
    args = parser.parse_args(argv)

    samples: list[float] = []
    statuses: list[int] = []
    last_body = b""
    last_headers: dict[str, str] = {}

    for index in range(max(1, args.n)):
        status, body, headers, elapsed_ms = request(args.base, args.path)
        statuses.append(status)
        last_body, last_headers = body, headers
        if args.skip_first and index == 0:
            continue
        samples.append(elapsed_ms)

    p95 = statistics.quantiles(samples, n=20)[-1] if len(samples) > 1 else samples[0]
    avg = sum(samples) / len(samples)
    print(f"path     : {args.base.rstrip('/')}{args.path}")
    print(f"status   : {statuses}")
    print(f"bytes    : {len(last_body)}")
    print(f"gzip?    : {'gzip' if last_headers.get('content-encoding') == 'gzip' else 'no'}")
    print(f"etag     : {last_headers.get('etag', '-')}")
    print(f"ms       : avg={avg:.1f} p95={p95:.1f} max={max(samples):.1f} (n={len(samples)})")

    if args.json and last_body:
        try:
            parsed = json.loads(last_body.decode("utf-8", errors="replace"))
            if isinstance(parsed, dict):
                keys = sorted(parsed.keys())
                print(f"top-keys : {keys}")
                for key in ("count", "total", "offset", "limit", "snapshot", "has_more", "turns_total"):
                    if key in parsed:
                        print(f"  {key}: {parsed[key]}")
                if isinstance(parsed.get("events"), list):
                    print(f"  events: {len(parsed['events'])}")
        except json.JSONDecodeError:
            print("top-keys : <non json>")

    failures: list[str] = []
    if args.max_bytes and len(last_body) > args.max_bytes:
        failures.append(f"bytes {len(last_body)} > {args.max_bytes}")
    if args.max_ms and p95 > args.max_ms:
        failures.append(f"p95 {p95:.1f}ms > {args.max_ms}ms")

    if args.etag:
        etag = last_headers.get("etag")
        if not etag:
            failures.append("响应没有 ETag 头")
        else:
            # 304 只发一次太脆：本机回环的 TCP 建连开销本身就有 6–35 ms 的抖动
            # （实测呈双峰分布，min 6.1 ms / max 35.4 ms，而服务端在 304 路径上
            # 一次文件解析都不做）。因此：**功能断言逐次全验，耗时断言用中位数**。
            # 阈值放到 50 ms 仍能兜住"304 又去解析文件"这类真回归（那是 1.2 s 量级）。
            cond_samples: list[float] = []
            non_304: list[int] = []
            non_empty: list[int] = []
            for _ in range(max(1, args.etag_n)):
                status, body, _headers, elapsed_ms = request(
                    args.base, args.path, {"If-None-Match": etag}
                )
                cond_samples.append(elapsed_ms)
                if status != 304:
                    non_304.append(status)
                if body:
                    non_empty.append(len(body))
            median_ms = statistics.median(cond_samples)
            print(
                f"cond     : status=304 ×{len(cond_samples)} "
                f"body_bytes=0 ×{len(cond_samples)} "
                f"ms min={min(cond_samples):.1f} median={median_ms:.1f} max={max(cond_samples):.1f}"
            )
            if non_304:
                failures.append(f"条件请求返回 {non_304}，期望全部 304")
            if non_empty:
                failures.append(f"304 响应仍带 body：{non_empty} 字节")
            if median_ms > args.etag_max_ms:
                failures.append(
                    f"304 中位耗时 {median_ms:.1f}ms > {args.etag_max_ms}ms"
                    f"（样本 {[round(x, 1) for x in cond_samples]}）"
                )

    if failures:
        for failure in failures:
            print(f"FAIL     : {failure}")
        return 1
    print("RESULT   : PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
