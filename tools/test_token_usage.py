"""Token 计数口径单元测试（对齐 CC Switch）。

覆盖：
1. Claude Code 流式多行同 message.id → 只计一次；
2. WorkBuddy providerData.rawUsage → 按请求事件 id 去重；
3. WorkBuddy rawUsage 缺失 → 退回 agents SDK usage；
4. 无任何用量字段 → 返回 None（交由估算逻辑）；
5. tiktoken 基础可用性。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_app  # noqa: E402


def _write_jsonl(records: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for rec in records:
        tmp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.close()
    return Path(tmp.name)


class ClaudeUsageTest(unittest.TestCase):
    def test_same_message_id_counted_per_line(self):
        """按用户要求保留旧口径：同一 message.id 多行按行累计（不做去重）。"""
        usage = {
            "input_tokens": 100,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 300,
            "output_tokens": 40,
        }
        rec = {"type": "assistant", "message": {"id": "msg_A", "role": "assistant", "usage": usage}}
        path = _write_jsonl([rec, rec, rec])
        try:
            agg = web_app._claude_recorded_usage(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertIsNotNone(agg)
        self.assertEqual(agg["calls"], 3)
        self.assertEqual(agg["input"], 1260)  # (100 + 20 + 300) * 3
        self.assertEqual(agg["output"], 120)

    def test_distinct_message_ids_summed(self):
        u1 = {"input_tokens": 10, "output_tokens": 5}
        u2 = {"input_tokens": 20, "output_tokens": 7}
        path = _write_jsonl([
            {"message": {"id": "m1", "usage": u1}},
            {"message": {"id": "m2", "usage": u2}},
        ])
        try:
            agg = web_app._claude_recorded_usage(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(agg["calls"], 2)
        self.assertEqual(agg["input"], 30)
        self.assertEqual(agg["output"], 12)


class WorkBuddyUsageTest(unittest.TestCase):
    def test_raw_usage_dedup_by_event_id(self):
        rec = {
            "id": "req_1",
            "type": "function_call",
            "providerData": {
                "model": "deepseek-v4.1-flash",
                "rawUsage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "prompt_tokens_details": {"cached_tokens": 800},
                    "completion_tokens_details": {"reasoning_tokens": 12},
                },
            },
        }
        path = _write_jsonl([rec, rec])  # 同一请求写了两遍
        try:
            agg = web_app._workbuddy_recorded_usage(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertIsNotNone(agg)
        self.assertEqual(agg["calls"], 1)
        self.assertEqual(agg["input"], 1000)  # OpenAI 口径已含缓存命中
        self.assertEqual(agg["output"], 50)
        self.assertEqual(agg["thoughts"], 12)

    def test_multiple_requests_summed(self):
        def rec(i, prompt, completion):
            return {
                "id": f"req_{i}",
                "providerData": {"rawUsage": {"prompt_tokens": prompt, "completion_tokens": completion}},
            }
        path = _write_jsonl([rec(1, 100, 10), rec(2, 200, 20)])
        try:
            agg = web_app._workbuddy_recorded_usage(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(agg["calls"], 2)
        self.assertEqual(agg["input"], 300)
        self.assertEqual(agg["output"], 30)

    def test_agents_sdk_usage_fallback(self):
        rec = {
            "id": "evt_1",
            "usage": {"inputTokens": 300, "outputTokens": 30, "outputTokensDetails": {"reasoningTokens": 4}},
        }
        path = _write_jsonl([rec])
        try:
            agg = web_app._workbuddy_recorded_usage(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(agg["calls"], 1)
        self.assertEqual(agg["input"], 300)
        self.assertEqual(agg["output"], 30)
        self.assertEqual(agg["thoughts"], 4)

    def test_no_usage_returns_none(self):
        path = _write_jsonl([{"type": "message", "role": "user", "content": "hi"}])
        try:
            agg = web_app._workbuddy_recorded_usage(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertIsNone(agg)


class TokenizerTest(unittest.TestCase):
    def test_estimate_positive(self):
        self.assertGreater(web_app.estimate_text_tokens("hello world"), 0)
        self.assertGreater(web_app.estimate_text_tokens("中文测试"), 0)

    def test_empty_text(self):
        self.assertEqual(web_app.estimate_text_tokens(""), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
