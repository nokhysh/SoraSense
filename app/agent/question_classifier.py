"""利用者の質問を、外部AIへデータを渡す前に決定的に分類する。"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class QuestionKind(StrEnum):
    """質問に必要な処理と公開可能なToolを表す。"""

    LATEST = "LATEST"
    STATISTICS = "STATISTICS"
    SERIES = "SERIES"
    COMPARE = "COMPARE"
    ALERT_HISTORY = "ALERT_HISTORY"
    CLARIFICATION = "CLARIFICATION"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    HELP = "HELP"


TOOL_BY_KIND = {
    QuestionKind.LATEST: "get_latest_measurement",
    QuestionKind.STATISTICS: "get_measurement_statistics",
    QuestionKind.SERIES: "get_measurement_series",
    QuestionKind.COMPARE: "compare_periods",
    QuestionKind.ALERT_HISTORY: "get_alert_history",
}

LOCAL_ANSWERS = {
    QuestionKind.CLARIFICATION: (
        "確認したいデータの種類と対象期間を指定してください。"
        "最新値、期間統計、時系列、期間比較、アラート履歴を確認できます。"
    ),
    QuestionKind.UNSUPPORTED_OPERATION: (
        "データの更新・削除、任意SQL、任意URLへのアクセス、ファイル操作は実行できません。"
    ),
    QuestionKind.OUT_OF_SCOPE: (
        "測定値の原因、健康影響、診断または安全性は判断できません。"
        "保存済みの温度・湿度・アラートは確認できます。"
    ),
    QuestionKind.HELP: (
        "最新値、指定期間の統計・時系列、2期間の比較、アラート履歴を確認できます。"
    ),
}

UNSUPPORTED_PATTERN = re.compile(
    r"(?:削除|消去|更新|変更|登録|追加).{0,6}(?:でき|可能|したい|して|する|しろ|せよ|実行|お願い)|"
    r"書き込|"
    r"(?<![a-z0-9_])(?:select|insert|update|delete|drop|alter|truncate)(?![a-z0-9_])|"
    r"sql.{0,8}実行|https?://|\burl\b|ファイル.{0,8}(?:読|書|操作)"
)
HELP_PATTERN = re.compile(r"何ができ|なにができ|使い方|利用方法|ヘルプ|機能を教")
OUT_OF_SCOPE_PATTERN = re.compile(r"原因|健康|病気|診断|安全性|安全ですか|危険|熱中症|カビ|快適")
DATA_PATTERN = re.compile(r"温度|気温|室温|湿度|温湿度|測定|データ|値")
LATEST_PATTERN = re.compile(r"最新|現在|直近|いま|今の")
STATISTICS_PATTERN = re.compile(
    r"平均|最小|最低|最大|最高|統計|件数|何件|回数|ピーク|"
    r"(?:最も|もっとも|一番|いちばん)(?:高い|低い|暑い|寒い)"
)
SERIES_PATTERN = re.compile(r"推移|時系列|グラフ|変化")
COMPARE_PATTERN = re.compile(r"比較|比べ|差分|増減率")
ALERT_PATTERN = re.compile(r"アラート|警報|異常履歴")
PERIOD_PATTERN = re.compile(
    r"先週末|今日|昨日|一昨日|今週(?!末)|先週(?!末)|"
    r"今月(?!末)|先月(?!末)|今年(?!末)|昨年(?!末)|"
    r"過去\s*\d+\s*(?:時間|日|週間|か月|ヶ月|月|年)|"
    r"\d{4}年\s*\d{1,2}月(?:\s*\d{1,2}日)?|"
    r"\d{1,2}月\s*\d{1,2}日|から|まで"
)
COMPARISON_PERIOD_PATTERN = re.compile(
    r"先週末|今日|昨日|一昨日|今週(?!末)|先週(?!末)|"
    r"今月(?!末)|先月(?!末)|今年(?!末)|昨年(?!末)|"
    r"過去\s*\d+\s*(?:時間|日|週間|か月|ヶ月|月|年)|"
    r"\d{4}年\s*\d{1,2}月(?:\s*\d{1,2}日)?|"
    r"\d{1,2}月\s*\d{1,2}日"
)


@dataclass(frozen=True)
class QuestionRoute:
    """分類結果と、外部AIを使用する場合に公開するToolを保持する。"""

    kind: QuestionKind

    @property
    def tool_name(self) -> str | None:
        """データ照会分類に対応するTool名を返す。"""

        return TOOL_BY_KIND.get(self.kind)

    @property
    def local_answer(self) -> str | None:
        """Tool不要分類に対する固定回答を返す。"""

        return LOCAL_ANSWERS.get(self.kind)


class QuestionClassifier:
    """保守的な規則で質問を分類し、不明な場合は追加条件を求める。"""

    def classify(self, question: str) -> QuestionRoute:
        """質問を分類し、分類不能時はデータ照会へ倒さない。"""

        normalized = unicodedata.normalize("NFKC", question).casefold()
        compact = re.sub(r"\s+", "", normalized)
        if UNSUPPORTED_PATTERN.search(normalized):
            return QuestionRoute(QuestionKind.UNSUPPORTED_OPERATION)
        if HELP_PATTERN.search(compact):
            return QuestionRoute(QuestionKind.HELP)
        if OUT_OF_SCOPE_PATTERN.search(compact):
            return QuestionRoute(QuestionKind.OUT_OF_SCOPE)

        has_data = DATA_PATTERN.search(compact) is not None
        has_period = PERIOD_PATTERN.search(compact) is not None
        if COMPARE_PATTERN.search(compact):
            periods = COMPARISON_PERIOD_PATTERN.findall(compact)
            kind = (
                QuestionKind.COMPARE
                if has_data and len(periods) >= 2
                else QuestionKind.CLARIFICATION
            )
            return QuestionRoute(kind)
        if ALERT_PATTERN.search(compact):
            return QuestionRoute(
                QuestionKind.ALERT_HISTORY if has_period else QuestionKind.CLARIFICATION
            )
        if SERIES_PATTERN.search(compact):
            return QuestionRoute(
                QuestionKind.SERIES if has_data and has_period else QuestionKind.CLARIFICATION
            )
        if STATISTICS_PATTERN.search(compact):
            return QuestionRoute(
                QuestionKind.STATISTICS if has_data and has_period else QuestionKind.CLARIFICATION
            )
        if has_data and LATEST_PATTERN.search(compact):
            return QuestionRoute(QuestionKind.LATEST)
        return QuestionRoute(QuestionKind.CLARIFICATION)
