#pragma once

#include <cstdint>

#include "api_client.h"
#include "clock_service.h"
#include "device_config.h"
#include "esp_uuid_generator.h"
#include "measurement_factory.h"
#include "retry_controller.h"
#include "sensor_reader.h"
#include "status_display.h"

namespace sorasense {

/** 初期化と非ブロッキングな計測・再送スケジュールを統括する。 */
class AppController {
public:
    AppController();

    void begin();
    void update();

private:
    void start_wifi(std::uint32_t now_ms);
    void update_sensor(std::uint32_t now_ms);
    void update_wifi(std::uint32_t now_ms);
    void update_clock(std::uint32_t now_ms);
    void update_measurement(std::uint32_t now_ms);
    void send_pending(std::uint32_t now_ms);
    void update_display(std::uint32_t now_ms, bool force = false);
    void record_send_result(const SendResult& result, RetryUpdate update);

    DeviceConfig config_;
    SensorReader sensor_;
    ClockService clock_;
    EspUuidGenerator uuid_generator_;
    MeasurementFactory measurement_factory_;
    ApiClient api_client_;
    RetryController retry_controller_;
    StatusDisplay display_;
    DeviceStatus status_;

    bool running_ = false;
    bool wifi_connecting_ = false;
    std::uint32_t wifi_started_at_ms_ = 0U;
    std::uint32_t next_wifi_attempt_ms_ = 0U;
    std::uint32_t next_sensor_attempt_ms_ = 0U;
    std::uint32_t next_clock_attempt_ms_ = 0U;
    std::uint32_t next_measurement_ms_ = 0U;
    std::uint32_t next_display_ms_ = 0U;
};

}  // namespace sorasense
