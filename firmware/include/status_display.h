#pragma once

#include <cstdint>
#include <optional>
#include <string>

#include "sensor_reader.h"

namespace sorasense {

enum class DeviceState {
    initializing,
    ready,
    measuring,
    pending_send,
    retry_wait,
    authentication_error,
    configuration_error,
};

struct DeviceStatus {
    DeviceState state = DeviceState::initializing;
    bool sensor_ready = false;
    bool wifi_connected = false;
    bool clock_valid = false;
    std::optional<SensorReading> latest_reading;
    std::string last_send_result = "WAIT";
    std::uint32_t invalid_reading_count = 0U;
};

/** 端末画面へ、秘密情報を含まない稼働状態を表示する。 */
class StatusDisplay {
public:
    void begin();
    void render(const DeviceStatus& status);
};

}  // namespace sorasense
