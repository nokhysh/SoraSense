"""参照専用の集計SQLをQueryServiceから分離する。"""

from datetime import datetime

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session


class QueryRepository:
    """固定SQLだけを実行し、任意SQLや任意テーブル名を受け付けない。"""

    def latest(self, session: Session, device_id: str) -> RowMapping | None:
        """最新測定値を1件取得する。"""

        return session.execute(
            text("""
                SELECT device_id, temperature_c, humidity_percent, measured_at, received_at
                FROM app.measurements
                WHERE device_id = :device_id
                ORDER BY measured_at DESC, id DESC
                LIMIT 1
            """),
            {"device_id": device_id},
        ).mappings().one_or_none()

    def statistics(
        self, session: Session, device_id: str, period_from: datetime, period_to: datetime
    ) -> RowMapping:
        """同じ行集合から温湿度の統計を取得する。"""

        return session.execute(
            text("""
                SELECT
                    MIN(temperature_c) AS temperature_minimum,
                    MAX(temperature_c) AS temperature_maximum,
                    AVG(temperature_c) AS temperature_average,
                    COUNT(*) AS temperature_count,
                    MIN(humidity_percent) AS humidity_minimum,
                    MAX(humidity_percent) AS humidity_maximum,
                    AVG(humidity_percent) AS humidity_average,
                    COUNT(*) AS humidity_count
                FROM app.measurements
                WHERE device_id = :device_id
                  AND measured_at >= :period_from
                  AND measured_at < :period_to
            """),
            {"device_id": device_id, "period_from": period_from, "period_to": period_to},
        ).mappings().one()

    def series(
        self,
        session: Session,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
        granularity: str,
    ) -> list[RowMapping]:
        """Asia/Tokyoの日・時境界で測定値を集計する。"""

        return list(session.execute(
            text("""
                WITH buckets AS (
                    SELECT
                        date_trunc(:granularity, measured_at AT TIME ZONE 'Asia/Tokyo')
                            AS local_bucket,
                        temperature_c,
                        humidity_percent
                    FROM app.measurements
                    WHERE device_id = :device_id
                      AND measured_at >= :period_from
                      AND measured_at < :period_to
                )
                SELECT
                    local_bucket AT TIME ZONE 'Asia/Tokyo' AS bucket_from,
                    (local_bucket + CASE
                        WHEN :granularity = 'hour' THEN INTERVAL '1 hour'
                        ELSE INTERVAL '1 day'
                    END) AT TIME ZONE 'Asia/Tokyo' AS bucket_to,
                    MIN(temperature_c) AS temperature_minimum,
                    MAX(temperature_c) AS temperature_maximum,
                    AVG(temperature_c) AS temperature_average,
                    COUNT(*) AS temperature_count,
                    MIN(humidity_percent) AS humidity_minimum,
                    MAX(humidity_percent) AS humidity_maximum,
                    AVG(humidity_percent) AS humidity_average,
                    COUNT(*) AS humidity_count
                FROM buckets
                GROUP BY local_bucket
                ORDER BY local_bucket
            """),
            {
                "device_id": device_id,
                "period_from": period_from,
                "period_to": period_to,
                "granularity": granularity,
            },
        ).mappings())

    def alerts(
        self,
        session: Session,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
        status: str | None,
        limit: int,
    ) -> tuple[int, list[RowMapping]]:
        """期間と状態に一致するアラート総数、および上限内の履歴を返す。"""

        parameters = {
            "device_id": device_id,
            "period_from": period_from,
            "period_to": period_to,
            "limit": limit,
        }
        where = """
            device_id = :device_id
            AND started_at >= :period_from
            AND started_at < :period_to
        """
        if status is not None:
            # psycopgはNULLだけのパラメータ型を推論できないため、状態指定時だけ条件を加える。
            where += " AND status = :status"
            parameters["status"] = status
        total = session.execute(
            text(f"SELECT COUNT(*) FROM app.alerts WHERE {where}"),
            parameters,
        ).scalar_one()
        rows = session.execute(
            text(f"""
                SELECT id, metric, direction, status, threshold_value, trigger_value,
                       hysteresis, started_at, last_detected_at, resolved_at
                FROM app.alerts
                WHERE {where}
                ORDER BY started_at DESC, id DESC
                LIMIT :limit
            """),
            parameters,
        ).mappings()
        return int(total), list(rows)
