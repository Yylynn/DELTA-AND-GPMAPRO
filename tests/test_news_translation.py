import json

from app.services.news_translation import HeadlineTranslator


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"responseStatus": 200, "responseData": {"translatedText": "高盛警告：不应让人工智能取代银行家的推理能力"}}


def test_headline_translation_is_cached_and_reused(tmp_path, monkeypatch):
    calls = []

    def get(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("app.services.news_translation.httpx.get", get)
    cache = tmp_path / "headline_translations_zh.json"
    translator = HeadlineTranslator(cache)
    title = "Goldman Sachs warns about replacing reasoning with AI"

    assert translator.translate(title).startswith("高盛警告")
    assert translator.translate(title).startswith("高盛警告")
    assert len(calls) == 1
    assert json.loads(cache.read_text(encoding="utf-8"))[title].startswith("高盛警告")


def test_existing_chinese_title_does_not_call_remote_service(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.news_translation.httpx.get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call")))
    translator = HeadlineTranslator(tmp_path / "cache.json")
    assert translator.translate("人工智能投资风险上升") == "人工智能投资风险上升"
