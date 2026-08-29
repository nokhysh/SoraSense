#include "api_client.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <limits>

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClient.h>

namespace sorasense {
namespace {

std::uint32_t parse_retry_after(const String& value) {
    if (value.isEmpty()) {
        return 0U;
    }
    std::uint64_t seconds = 0U;
    for (const char character : value) {
        if (!std::isdigit(static_cast<unsigned char>(character))) {
            return 0U;
        }
        seconds = seconds * 10U + static_cast<unsigned int>(character - '0');
        if (seconds > 24U * 60U * 60U) {
            return 24U * 60U * 60U;
        }
    }
    return static_cast<std::uint32_t>(seconds);
}

String measurement_url(const DeviceConfig& config) {
    String base_url(config.api_base_url);
    while (base_url.endsWith("/")) {
        base_url.remove(base_url.length() - 1U);
    }
    return base_url + "/api/v1/devices/" + config.device_id + "/measurements";
}

}  // namespace

ApiClient::ApiClient(const DeviceConfig& config) : config_(config) {}

SendResult ApiClient::send(const Measurement& measurement) const {
    JsonDocument document;
    document["schema_version"] = 1;
    document["message_id"] = measurement.message_id;
    document["device_id"] = measurement.device_id;
    document["measured_at"] = measurement.measured_at;
    document["temperature_c"] = measurement.temperature_celsius;
    document["humidity_percent"] = measurement.humidity_percent;

    String payload;
    serializeJson(document, payload);

    WiFiClient client;

    HTTPClient http;
    http.setConnectTimeout(5'000);
    http.setTimeout(10'000);
    http.setReuse(false);
    const char* response_headers[] = {"Retry-After"};
    http.collectHeaders(response_headers, 1U);

    if (!http.begin(client, measurement_url(config_))) {
        return classify_send_result(false, 0);
    }
    http.addHeader("Authorization", String("Bearer ") + config_.device_api_key);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Request-ID", measurement.message_id.c_str());

    const int status = http.POST(payload);
    const bool transport_succeeded = status > 0;
    const std::uint32_t retry_after = transport_succeeded
        ? parse_retry_after(http.header("Retry-After"))
        : 0U;
    http.end();
    return classify_send_result(transport_succeeded, status, retry_after);
}

}  // namespace sorasense
