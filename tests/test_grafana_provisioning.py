"""Grafana Provisioningが再構築可能な固定構成であることを検証する。"""

import json
from pathlib import Path


def test_dashboard_uses_only_reporting_views_and_has_required_panels() -> None:
    """全パネルが参照VIEWを使い、必須表示を備える。"""

    dashboard = json.loads(Path("grafana/dashboards/sorasense-overview.json").read_text())
    titles = {panel["title"] for panel in dashboard["panels"]}
    sql_statements = [
        target["rawSql"]
        for panel in dashboard["panels"]
        for target in panel["targets"]
    ]

    assert titles == {
        "デバイス状態",
        "最新温度",
        "最新湿度",
        "最終受信日時",
        "温湿度履歴",
        "温湿度統計",
        "測定データ欠損",
        "アラート履歴",
    }
    assert all("reporting.v_" in sql for sql in sql_statements)
    assert all("app." not in sql for sql in sql_statements)
    assert all("${device_id:sqlstring}" in sql for sql in sql_statements)
    assert dashboard["editable"] is False
    assert dashboard["timezone"] == "Asia/Tokyo"


def test_datasource_reads_password_from_environment() -> None:
    """接続SecretをProvisioningファイルへ直書きしない。"""

    datasource = Path("grafana/provisioning/datasources/postgresql.yaml").read_text()
    assert "user: grafana_reader" in datasource
    assert "password: ${GRAFANA_READER_PASSWORD}" in datasource
