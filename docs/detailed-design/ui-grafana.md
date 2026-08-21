# SoraSense 詳細設計書 — UI・Grafana

## 1. 文書情報

| 項目 | 内容 |
|---|---|
| 文書版数 | 0.1.0 |
| 入力文書 | 要件定義書 v0.1.0、基本設計書 v0.3.0 |
| 対象 | AI質問Web画面、利用者認証、Grafanaダッシュボード |

## 2. 画面と経路

| 画面 | Method / Path | 認証 | 内容 |
|---|---|---|---|
| AIログイン | GET/POST `/login` | 不要 | ユーザー名・パスワード認証 |
| AIアシスタント | GET `/agent` | 必須 | 質問フォーム |
| AI質問結果 | POST `/agent/questions` | 必須 | Agent実行と結果表示 |
| ログアウト | POST `/logout` | 必須 | セッション破棄 |
| Grafanaログイン | Grafana標準 | 不要 | Grafanaローカル認証 |
| ダッシュボード | Grafana標準URL | 必須 | 現在値、履歴、統計、アラート、状態 |

AI画面とGrafanaダッシュボードには相互リンクを置く。管理画面、デバイス変更画面、閾値変更画面は作らない。

## 3. AI画面入力

| フィールド | HTML | 制約 |
|---|---|---|
| `username` | `input type=text` | 1～128文字 |
| `password` | `input type=password` | 1～256文字、再表示しない |
| `question` | `textarea` | 必須、前後空白除去後1～2000文字 |
| `csrf_token` | `input type=hidden` | セッションと定時間比較 |

フォームはUTF-8の`application/x-www-form-urlencoded`とする。クライアントサイドJavaScriptは使用しない。二重送信は同一セッション内のワンタイムフォームトークンで抑止し、再送時は新しい質問として明示的に送信させる。

## 4. 認証とセッション

- `WEB_USERNAME`とArgon2idの`WEB_PASSWORD_HASH`を環境変数から取得する。
- 認証失敗ではユーザー名の存在を区別せず、IP・ユーザー名単位で5回／15分を超えた試行を15分間制限する。
- セッションIDは128ビット以上の暗号学的乱数とし、サーバー側セッションストアへ保存する。
- ログイン成功時にセッションIDを再生成する。
- Cookieは`Secure`、`HttpOnly`、`SameSite=Lax`、`Path=/`とする。
- 無操作30分、絶対8時間で失効する。ログアウト時はサーバー側セッションを無効化する。
- 状態変更POSTはすべてセッションに結び付いたCSRFトークンを検証する。

## 5. AI回答表示

成功時は同一画面に、質問フォーム、回答、対象デバイス、対象期間、タイムゾーン、主要根拠値、リクエストIDを表示する。回答はHTMLとして信頼せず、テンプレートの自動エスケープを有効にしてプレーンテキストとして表示する。

| 状態 | 表示 |
|---|---|
| データなし | 指定条件に該当するデータがないことを表示 |
| AI利用不能 | 収集・Grafanaは利用可能であることと再試行案内を表示 |
| 入力不正 | 対象フィールド付近に理由を表示し、秘密情報を含めない |
| セッション失効 | ログイン画面へ遷移し、再認証を案内 |
| 想定外エラー | 一般的な説明とリクエストIDを表示 |

## 6. セキュリティヘッダー

`Content-Security-Policy: default-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`を設定する。HTTPS終端でHSTSを付与する。テンプレートにインラインスクリプトを置かない。

## 7. Grafanaデータソース

PostgreSQLデータソースは`grafana_reader`を使用し、`reporting`スキーマのVIEWだけを参照する。接続情報はProvisioning用Secretから取得し、ダッシュボードJSONへ埋め込まない。匿名アクセス、編集可能な利用者登録、Explore機能は初期リリースで無効化する。

## 8. ダッシュボード構成

| パネル | データ | 可視化 | 更新 |
|---|---|---|---|
| デバイス状態 | `v_device_statuses` | Stat、状態別色 | 30秒 |
| 最新温度 | `v_latest_measurements` | Stat、℃ | 30秒 |
| 最新湿度 | `v_latest_measurements` | Stat、% | 30秒 |
| 最終受信日時 | `v_latest_measurements` | Stat、`Asia/Tokyo` | 30秒 |
| 温湿度履歴 | `v_measurement_series` | Time series、2軸 | 選択期間 |
| 温湿度統計 | `v_measurement_series` | Table、min/max/avg | 選択期間 |
| 測定データ欠損 | `v_measurement_gaps` | Table、欠損区間・推定件数 | 選択期間 |
| アラート履歴 | `v_alert_history` | Table | 選択期間 |

ダッシュボード変数は単一`device_id`だけとし、設定値から固定する。期間指定にはGrafana標準Time Pickerを使用する。SQLの期間条件にはGrafanaの時間マクロを用い、利用者入力を文字列連結しない。

## 9. 表示規則

- 温度は小数第1位と`℃`、湿度は小数第1位と`%`で表示する。
- GrafanaとAI画面の日時は`Asia/Tokyo`で表示し、利用者によるタイムゾーン選択は提供しない。
- データなしを0として表示しない。
- ONLINEは緑、STALEは黄、OFFLINEは赤とし、色だけでなくテキストも表示する。
- アラートは項目、方向、状態、閾値、発生値、発生・解消日時を確認可能にする。

## 10. Provisioning

データソース、ダッシュボード、フォルダー設定をGit管理可能なProvisioningファイルで作成する。GrafanaのDBを永続化前提にせず、環境再構築後も同一表示を復元できることを結合テストで確認する。
