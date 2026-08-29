#pragma once

// このファイルをdevice_secrets.hとしてコピーし、実値を設定する。
// device_secrets.hは.gitignoreの対象であり、リポジトリへ登録しない。
#define SORASENSE_DEVICE_ID "living-room-01"
#define SORASENSE_DEVICE_API_KEY "replace-with-device-api-key"
#define SORASENSE_API_BASE_URL "https://sorasense.example.com"
#define SORASENSE_WIFI_SSID "replace-with-wifi-ssid"
#define SORASENSE_WIFI_PASSWORD "replace-with-wifi-password"
#define SORASENSE_NTP_SERVER_1 "ntp.nict.jp"
#define SORASENSE_NTP_SERVER_2 "time.google.com"
#define SORASENSE_NTP_SERVER_3 "pool.ntp.org"

// 接続先サーバー証明書を検証できるPEM形式のCA証明書を設定する。
#define SORASENSE_SERVER_CA_CERT \
    "-----BEGIN CERTIFICATE-----\n" \
    "replace-with-ca-certificate\n" \
    "-----END CERTIFICATE-----\n"
