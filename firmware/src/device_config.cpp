#include "device_config.h"

#include <cstring>

namespace sorasense {
namespace {

bool has_value(const char* value) {
    return value != nullptr && std::strlen(value) > 0U;
}

bool has_prefix(const char* value, const char* prefix) {
    return value != nullptr
        && std::strncmp(value, prefix, std::strlen(prefix)) == 0;
}

bool is_valid_https_url(const char* value) {
    constexpr const char* scheme = "https://";
    return has_prefix(value, scheme) && std::strlen(value) > std::strlen(scheme);
}

bool is_valid_device_id(const char* value) {
    if (!has_value(value)) {
        return false;
    }
    const std::size_t length = std::strlen(value);
    if (length > 64U || value[0] == '-' || value[length - 1U] == '-') {
        return false;
    }
    for (std::size_t index = 0U; index < length; ++index) {
        const char character = value[index];
        const bool lower_alphanumeric = (character >= 'a' && character <= 'z')
            || (character >= '0' && character <= '9');
        if (!lower_alphanumeric && character != '-') {
            return false;
        }
    }
    return true;
}

}  // namespace

bool is_valid_device_config(const DeviceConfig& config) {
    return is_valid_device_id(config.device_id) && has_value(config.device_api_key)
        && is_valid_https_url(config.api_base_url) && has_value(config.wifi_ssid)
        && has_value(config.wifi_password) && has_value(config.ntp_server_1)
        && has_value(config.ntp_server_2)
        && has_prefix(config.server_ca_certificate, "-----BEGIN CERTIFICATE-----");
}

}  // namespace sorasense
