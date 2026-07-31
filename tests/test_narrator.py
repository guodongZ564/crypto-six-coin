"""Anthropic API 失败时的降级保证：narrator.generate_narrative 不能让
anthropic.APIError(额度超限/网络抖动/服务故障)原样往上抛未捕获的异常——
那样 GitHub Actions 会在叙事这一步整个job停住，后面留痕/仪表盘/数据提交
全部被跳过，白丢一整天已经采集好的数据。这里钉死"API失败必须转换成
NarrationUnavailable，调用方能识别并降级"。
"""

import httpx
import pytest

from narrate import narrator


class _FakeMessagesThatFail:
    def create(self, **kwargs):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise narrator.anthropic.APIStatusError(
            "You have reached your specified workspace API usage limits.",
            response=httpx.Response(400, request=request),
            body={"error": {"type": "invalid_request_error"}},
        )


class _FakeClientThatFails:
    def __init__(self, *args, **kwargs):
        self.messages = _FakeMessagesThatFail()


def test_api_failure_raises_narration_unavailable_not_raw_api_error(monkeypatch):
    monkeypatch.setattr(narrator.anthropic, "Anthropic", _FakeClientThatFails)

    with pytest.raises(narrator.NarrationUnavailable):
        narrator.generate_narrative({"date": "2026-07-31"}, api_key="fake-key")
