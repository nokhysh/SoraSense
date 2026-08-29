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

bool parse_number(
    const char*& cursor,
    const unsigned int maximum,
    unsigned int& result
) {
    if (*cursor < '0' || *cursor > '9') {
        return false;
    }
    unsigned int value = 0U;
    do {
        const unsigned int digit = static_cast<unsigned int>(*cursor - '0');
        if (value > (maximum - digit) / 10U) {
            return false;
        }
        value = value * 10U + digit;
        ++cursor;
    } while (*cursor >= '0' && *cursor <= '9');
    result = value;
    return true;
}

bool is_private_ipv4(const unsigned int octets[4]) {
    return octets[0] == 10U
        || (octets[0] == 172U && octets[1] >= 16U && octets[1] <= 31U)
        || (octets[0] == 192U && octets[1] == 168U);
}

bool is_valid_local_http_url(const char* value) {
    constexpr const char* scheme = "http://";
    if (!has_prefix(value, scheme)) {
        return false;
    }

    const char* cursor = value + std::strlen(scheme);
    unsigned int octets[4] = {};
    for (std::size_t index = 0U; index < 4U; ++index) {
        if (!parse_number(cursor, 255U, octets[index])) {
            return false;
        }
        const char expected_separator = index < 3U ? '.' : ':';
        if (*cursor != expected_separator) {
            return false;
        }
        ++cursor;
    }

    unsigned int port = 0U;
    if (!parse_number(cursor, 65'535U, port) || port != 8'000U) {
        return false;
    }
    while (*cursor == '/') {
        ++cursor;
    }
    return *cursor == '\0' && is_private_ipv4(octets);
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
        && is_valid_local_http_url(config.api_base_url) && has_value(config.wifi_ssid)
        && has_value(config.wifi_password) && has_value(config.ntp_server_1)
        && has_value(config.ntp_server_2);
}

}  // namespace sorasense
