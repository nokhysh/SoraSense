#pragma once

#include <cstdint>

#if __has_include("device_secrets.h")
#include "device_secrets.h"
#endif

#ifndef SORASENSE_DEVICE_ID
#define SORASENSE_DEVICE_ID ""
#endif

#ifndef SORASENSE_DEVICE_API_KEY
#define SORASENSE_DEVICE_API_KEY ""
#endif

#ifndef SORASENSE_API_BASE_URL
#define SORASENSE_API_BASE_URL ""
#endif

#ifndef SORASENSE_WIFI_SSID
#define SORASENSE_WIFI_SSID ""
#endif

#ifndef SORASENSE_WIFI_PASSWORD
#define SORASENSE_WIFI_PASSWORD ""
#endif

#ifndef SORASENSE_NTP_SERVER_1
#define SORASENSE_NTP_SERVER_1 ""
#endif

#ifndef SORASENSE_NTP_SERVER_2
#define SORASENSE_NTP_SERVER_2 ""
#endif

#ifndef SORASENSE_NTP_SERVER_3
#define SORASENSE_NTP_SERVER_3 ""
#endif

#ifndef SORASENSE_SERVER_CA_CERT
#define SORASENSE_SERVER_CA_CERT ""
#endif

namespace sorasense {

/** 実機設定と、設計で定めた固定の制御値を保持する。 */
struct DeviceConfig {
    const char* device_id = SORASENSE_DEVICE_ID;
    const char* device_api_key = SORASENSE_DEVICE_API_KEY;
    const char* api_base_url = SORASENSE_API_BASE_URL;
    const char* wifi_ssid = SORASENSE_WIFI_SSID;
    const char* wifi_password = SORASENSE_WIFI_PASSWORD;
    const char* ntp_server_1 = SORASENSE_NTP_SERVER_1;
    const char* ntp_server_2 = SORASENSE_NTP_SERVER_2;
    const char* ntp_server_3 = SORASENSE_NTP_SERVER_3;
    const char* server_ca_certificate = SORASENSE_SERVER_CA_CERT;

    std::uint32_t measurement_interval_ms = 60'000U;
    std::uint32_t sensor_retry_interval_ms = 30'000U;
    std::uint32_t wifi_connection_timeout_ms = 30'000U;
    std::uint32_t wifi_retry_interval_ms = 30'000U;
    std::uint32_t clock_retry_interval_ms = 30'000U;
    std::uint32_t clock_resync_interval_ms = 6U * 60U * 60U * 1'000U;
    std::uint32_t clock_validity_ms = 24U * 60U * 60U * 1'000U;
};

/** Secretを表示せず、必須設定が投入済みかだけを検証する。 */
[[nodiscard]] bool is_valid_device_config(const DeviceConfig& config);

}  // namespace sorasense
