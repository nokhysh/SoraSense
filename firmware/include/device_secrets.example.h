#pragma once

// このファイルをdevice_secrets.hとしてコピーし、実値を設定する。
// device_secrets.hは.gitignoreの対象であり、リポジトリへ登録しない。
#define SORASENSE_DEVICE_ID "living-room-01"
#define SORASENSE_DEVICE_API_KEY "replace-with-device-api-key"
// M5StickC Plus2から到達できるMacのプライベートIPv4アドレスを指定する。
#define SORASENSE_API_BASE_URL "http://192.168.1.100:8000"
#define SORASENSE_WIFI_SSID "replace-with-wifi-ssid"
#define SORASENSE_WIFI_PASSWORD "replace-with-wifi-password"
#define SORASENSE_NTP_SERVER_1 "ntp.nict.jp"
#define SORASENSE_NTP_SERVER_2 "time.google.com"
#define SORASENSE_NTP_SERVER_3 "pool.ntp.org"
