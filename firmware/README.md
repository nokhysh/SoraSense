# SoraSense センサーデバイス

M5StickC Plus2とENV IV Unitを使用し、60秒周期で温湿度を測定してSoraSense APIへ送信する。
通信失敗時は最新の未送信データ1件を保持し、計測を止めずに上限付き指数バックオフで再送する。
PlatformIOのボード定義は、M5Stack公式`M5UnitUnified`が提供するM5StickC Plus2定義に合わせている。

## 構成

| モジュール | 責務 |
|---|---|
| `SensorReader` | ENV IVの初期化、SHT40測定値の取得 |
| `ClockService` | NTP同期、UTC生成、時刻保証期限の管理 |
| `MeasurementFactory` | UUID v4と送信データの生成 |
| `ApiClient` | 管理対象LAN内へのHTTP送信、HTTP結果の分類 |
| `RetryController` | 最新未送信データ、再送回数、バックオフの管理 |
| `StatusDisplay` | 測定値と接続・送信状態の端末表示 |
| `AppController` | 初期化、60秒計測、再接続、再送のスケジュール制御 |

## Secret設定

`include/device_secrets.example.h`を`include/device_secrets.h`としてコピーし、次を実値へ変更する。
`device_secrets.h`はGit管理対象外である。

- デバイスIDとAPIキー
- M5StickC Plus2から到達可能なMacのHTTPベースURL
- M5StickC Plus2が対応する2.4GHz Wi-FiのSSIDとパスワード
- 2つ以上のNTPサーバー

API URLは`http://{MacのプライベートIPv4}:8000`形式で指定する。`localhost`と`127.0.0.1`はM5StickC Plus2自身を指すため使用しない。公開インターネットへAPIキーを送らないよう、プライベートIPv4以外の送信先は設定検証で拒否する。
`replace-with-`で始まるサンプル値は起動時に拒否する。実機へ書き込む前に、2.4GHz用SSID、API URLおよびデバイスAPIキーが実値へ置き換わっていることを確認する。

## 検証

ホスト上の単体テストを実行する。

```shell
platformio test --environment native
```

M5StickC Plus2向けにビルドする。

```shell
platformio run --environment m5stick-cplus2
```

実機へ書き込む場合だけ、USB接続後に次を実行する。

```shell
platformio run --environment m5stick-cplus2 --target upload
```

## 安全上の動作

- 時刻同期前または最終同期から24時間超過後は送信しない。
- APIキー、Wi-Fiパスワードおよび測定値全件をシリアルログへ出力しない。
- HTTP 401または403では自動送信を停止し、設定修正後の再起動を要求する。
- HTTP 429、5xx、接続失敗およびタイムアウトだけを再送する。
- 同じ測定の再送では同じ`message_id`を使用する。
- 新しい測定が発生した場合、古い未送信データを新しい測定で置き換える。
- センサー読取が5秒を超えて途絶えた場合は異常状態へ戻し、30秒後から再初期化する。
