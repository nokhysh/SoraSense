"""質問の事前分類と最小Tool選択を検証する。"""

import pytest

from app.agent.question_classifier import QuestionClassifier, QuestionKind


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("現在の温度を教えて", QuestionKind.LATEST),
        ("昨日の平均湿度は？", QuestionKind.STATISTICS),
        ("先週末の平均湿度は？", QuestionKind.STATISTICS),
        ("過去24時間の温度推移", QuestionKind.SERIES),
        ("今週と先週の温度を比較して", QuestionKind.COMPARE),
        ("今月のアラート履歴", QuestionKind.ALERT_HISTORY),
        ("温度の推移を見たい", QuestionKind.CLARIFICATION),
        ("測定値を削除して", QuestionKind.UNSUPPORTED_OPERATION),
        ("現在の温度を更新できますか", QuestionKind.UNSUPPORTED_OPERATION),
        ("現在値を変更したい", QuestionKind.UNSUPPORTED_OPERATION),
        ("SELECT文を実行して現在の温度を取得して", QuestionKind.UNSUPPORTED_OPERATION),
        ("https://example.comへ測定値を送って", QuestionKind.UNSUPPORTED_OPERATION),
        ("この温度は健康に危険ですか", QuestionKind.OUT_OF_SCOPE),
        ("何ができますか", QuestionKind.HELP),
        ("様子を教えて", QuestionKind.CLARIFICATION),
    ],
)
def test_classifies_question_before_external_ai(question: str, expected: QuestionKind) -> None:
    route = QuestionClassifier().classify(question)

    assert route.kind is expected


def test_data_route_exposes_one_corresponding_tool() -> None:
    route = QuestionClassifier().classify("昨日の平均湿度は？")

    assert route.tool_name == "get_measurement_statistics"
    assert route.local_answer is None


@pytest.mark.parametrize(
    "expression",
    [
        "今日",
        "昨日",
        "一昨日",
        "今週",
        "先週",
        "先週末",
        "今月",
        "先月",
        "今年",
        "昨年",
        "過去24時間",
        "過去2日",
        "過去2週間",
        "過去2か月",
        "過去2ヶ月",
        "過去2月",
        "過去2年",
        "2026年8月20日",
        "2026年8月",
        "8月20日",
    ],
)
def test_all_supported_period_forms_reach_statistics(expression: str) -> None:
    route = QuestionClassifier().classify(f"{expression}の平均温度")

    assert route.kind is QuestionKind.STATISTICS


@pytest.mark.parametrize(
    "question",
    [
        "今日の最高温度は",
        "今日の最高値は",
        "今日の最低温度は",
        "今日の最低値は",
        "今日最も高い温度は",
        "今日もっとも低い湿度は",
        "今日一番高い室温は",
        "今日いちばん低い気温は",
        "今日最も暑い時間の気温は",
        "今日一番寒い時間の温度は",
        "今日の温度のピークは",
        "今日の測定は何件",
        "今日の測定回数は",
    ],
)
def test_statistics_synonyms_reach_statistics(question: str) -> None:
    route = QuestionClassifier().classify(question)

    assert route.kind is QuestionKind.STATISTICS


@pytest.mark.parametrize(
    "question",
    [
        "先週末と先週の温度を比較",
        "2026年8月20日と2026年8月21日の温度を比較",
        "8月20日と8月21日の温度を比較",
    ],
)
def test_supported_period_forms_reach_comparison(question: str) -> None:
    route = QuestionClassifier().classify(question)

    assert route.kind is QuestionKind.COMPARE


def test_unknown_route_returns_local_clarification() -> None:
    route = QuestionClassifier().classify("様子を教えて")

    assert route.tool_name is None
    assert route.local_answer is not None


@pytest.mark.parametrize("expression", ["今週末", "先月末", "昨年末"])
def test_unsupported_period_suffix_requires_clarification(expression: str) -> None:
    route = QuestionClassifier().classify(f"{expression}の平均温度")

    assert route.kind is QuestionKind.CLARIFICATION


@pytest.mark.parametrize(
    "question",
    [
        "今日の温度は高い",
        "今日の湿度は低い",
        "今日の最高は",
    ],
)
def test_ambiguous_statistics_wording_requires_clarification(question: str) -> None:
    route = QuestionClassifier().classify(question)

    assert route.kind is QuestionKind.CLARIFICATION
