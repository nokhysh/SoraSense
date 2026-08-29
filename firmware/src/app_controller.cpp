#include "app_controller.h"

#include <cstdint>
#include <string>

#include <Arduino.h>
#include <M5Unified.h>
#include <WiFi.h>
#include <esp_system.h>

#include "measurement_validator.h"

namespace sorasense {
namespace {

bool deadline_reached(const std::uint32_t now_ms, const std::uint32_t deadline_ms) {
    return static_cast<std::int32_t>(now_ms - deadline_ms) >= 0;
}

std::string message_prefix(const std::string& message_id) {
    return message_id.substr(0U, 8U);
}

}  // namespace

AppController::AppController()
    : clock_(config_),
      measurement_factory_(config_.device_id, uuid_generator_),
      api_client_(config_) {}

void AppController::begin() {
    Serial.begin(115'200);
    const auto m5_config = M5.config();
    M5.begin(m5_config);
    display_.begin();

    if (!is_valid_device_config(config_)) {
        status_.state = DeviceState::configuration_error;
        status_.last_send_result = "CONFIG REQUIRED";
        display_.render(status_);
        Serial.println("event=startup result=configuration_error");
        return;
    }

    const std::uint32_t now_ms = millis();
    running_ = true;
    next_measurement_ms_ = now_ms + config_.measurement_interval_ms;
    next_display_ms_ = now_ms;

    status_.sensor_ready = sensor_.initialize(now_ms);
    if (!status_.sensor_ready) {
        next_sensor_attempt_ms_ = now_ms + config_.sensor_retry_interval_ms;
        Serial.println("event=sensor_initialize result=failed");
    } else {
        Serial.println("event=sensor_initialize result=success");
    }
    start_wifi(now_ms);
    update_display(now_ms, true);
}

void AppController::update() {
    M5.update();
    if (!running_) {
        return;
    }

    const std::uint32_t now_ms = millis();
    update_sensor(now_ms);
    update_wifi(now_ms);
    update_clock(now_ms);
    update_measurement(now_ms);
    send_pending(now_ms);
    update_display(now_ms);
}

void AppController::start_wifi(const std::uint32_t now_ms) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(config_.wifi_ssid, config_.wifi_password);
    wifi_connecting_ = true;
    wifi_started_at_ms_ = now_ms;
    Serial.println("event=wifi_connect result=started");
}

void AppController::update_sensor(const std::uint32_t now_ms) {
    const bool was_ready = status_.sensor_ready;
    sensor_.update(now_ms);
    status_.sensor_ready = sensor_.initialized();
    if (was_ready && !status_.sensor_ready) {
        next_sensor_attempt_ms_ = now_ms + config_.sensor_retry_interval_ms;
        status_.last_send_result = "SENSOR WAIT";
        Serial.println("event=sensor_read result=stopped");
    }
    if (status_.sensor_ready || !deadline_reached(now_ms, next_sensor_attempt_ms_)) {
        return;
    }

    status_.sensor_ready = sensor_.initialize(now_ms);
    next_sensor_attempt_ms_ = now_ms + config_.sensor_retry_interval_ms;
    Serial.printf(
        "event=sensor_initialize result=%s\n",
        status_.sensor_ready ? "success" : "failed"
    );
}

void AppController::update_wifi(const std::uint32_t now_ms) {
    const bool connected = WiFi.status() == WL_CONNECTED;
    if (connected) {
        if (!status_.wifi_connected) {
            Serial.println("event=wifi_connect result=success");
            next_clock_attempt_ms_ = now_ms;
        }
        status_.wifi_connected = true;
        wifi_connecting_ = false;
        return;
    }

    if (status_.wifi_connected) {
        Serial.println("event=wifi_connect result=lost");
        next_wifi_attempt_ms_ = now_ms;
    }
    status_.wifi_connected = false;

    if (wifi_connecting_) {
        if (now_ms - wifi_started_at_ms_ < config_.wifi_connection_timeout_ms) {
            return;
        }
        WiFi.disconnect();
        wifi_connecting_ = false;
        next_wifi_attempt_ms_ = now_ms + config_.wifi_retry_interval_ms;
        Serial.println("event=wifi_connect result=timeout");
        return;
    }

    if (deadline_reached(now_ms, next_wifi_attempt_ms_)) {
        start_wifi(now_ms);
    }
}

void AppController::update_clock(const std::uint32_t now_ms) {
    clock_.update(now_ms);
    status_.clock_valid = clock_.is_time_valid(now_ms);
    if (!status_.wifi_connected || !clock_.should_resynchronize(now_ms)
        || clock_.synchronization_in_progress()
        || !deadline_reached(now_ms, next_clock_attempt_ms_)) {
        return;
    }

    clock_.request_synchronization(now_ms);
    next_clock_attempt_ms_ = now_ms + config_.clock_retry_interval_ms;
    Serial.println("event=ntp_sync result=started");
}

void AppController::update_measurement(const std::uint32_t now_ms) {
    if (!deadline_reached(now_ms, next_measurement_ms_)) {
        return;
    }
    do {
        next_measurement_ms_ += config_.measurement_interval_ms;
    } while (deadline_reached(now_ms, next_measurement_ms_));

    const bool transmission_stopped = status_.state == DeviceState::authentication_error;
    if (!transmission_stopped) {
        status_.state = DeviceState::measuring;
    }
    const auto reading = sensor_.latest(now_ms);
    if (!reading || !is_valid_measurement(
            reading->temperature_celsius,
            reading->humidity_percent
        )) {
        ++status_.invalid_reading_count;
        if (!transmission_stopped) {
            status_.state = DeviceState::ready;
        }
        status_.last_send_result = "SENSOR INVALID";
        Serial.println("event=measurement result=invalid");
        return;
    }
    status_.latest_reading = reading;

    if (!clock_.is_time_valid(now_ms)) {
        if (!transmission_stopped) {
            status_.state = DeviceState::ready;
        }
        status_.last_send_result = "TIME INVALID";
        Serial.println("event=measurement result=time_unavailable");
        return;
    }

    const std::string measured_at = clock_.utc_now(now_ms);
    if (measured_at.empty()) {
        if (!transmission_stopped) {
            status_.state = DeviceState::ready;
        }
        status_.last_send_result = "TIME INVALID";
        return;
    }

    if (transmission_stopped) {
        return;
    }
    Measurement measurement = measurement_factory_.create(
        measured_at,
        reading->temperature_celsius,
        reading->humidity_percent
    );
    const std::string prefix = message_prefix(measurement.message_id);
    retry_controller_.replace(std::move(measurement), now_ms);
    status_.state = DeviceState::pending_send;
    status_.last_send_result = "PENDING";
    Serial.printf("event=measurement result=queued message_id=%s\n", prefix.c_str());
}

void AppController::send_pending(const std::uint32_t now_ms) {
    if (status_.state == DeviceState::authentication_error
        || !status_.wifi_connected || !clock_.is_time_valid(now_ms)
        || !retry_controller_.is_due(now_ms)) {
        return;
    }

    const Measurement* pending = retry_controller_.pending();
    if (pending == nullptr) {
        return;
    }
    const Measurement sent = *pending;
    status_.state = DeviceState::pending_send;
    const SendResult result = api_client_.send(sent);
    const std::uint32_t result_at_ms = millis();
    const RetryUpdate update = retry_controller_.apply_result(
        sent.message_id,
        result,
        result_at_ms,
        esp_random()
    );
    Serial.printf(
        "event=measurement_send status=%d attempt=%u message_id=%s\n",
        result.http_status,
        static_cast<unsigned int>(retry_controller_.retry_count()),
        message_prefix(sent.message_id).c_str()
    );
    record_send_result(result, update);
}

void AppController::record_send_result(const SendResult& result, const RetryUpdate update) {
    switch (update) {
        case RetryUpdate::accepted:
            status_.state = DeviceState::ready;
            status_.last_send_result = result.http_status == 201 ? "CREATED" : "DUPLICATE";
            break;
        case RetryUpdate::discarded:
            status_.state = DeviceState::ready;
            status_.last_send_result = "DISCARDED";
            break;
        case RetryUpdate::authentication_error:
            status_.state = DeviceState::authentication_error;
            status_.last_send_result = "AUTH ERROR";
            break;
        case RetryUpdate::retry_scheduled:
            status_.state = DeviceState::retry_wait;
            status_.last_send_result = "RETRY WAIT";
            break;
        case RetryUpdate::retries_exhausted:
            status_.state = DeviceState::ready;
            status_.last_send_result = "RETRY EXHAUSTED";
            break;
        case RetryUpdate::ignored:
            break;
    }
}

void AppController::update_display(const std::uint32_t now_ms, const bool force) {
    constexpr std::uint32_t display_interval_ms = 1'000U;
    if (!force && !deadline_reached(now_ms, next_display_ms_)) {
        return;
    }
    next_display_ms_ = now_ms + display_interval_ms;
    status_.sensor_ready = sensor_.initialized();
    status_.wifi_connected = WiFi.status() == WL_CONNECTED;
    status_.clock_valid = clock_.is_time_valid(now_ms);
    if (status_.state == DeviceState::initializing
        && status_.sensor_ready && status_.wifi_connected && status_.clock_valid) {
        status_.state = DeviceState::ready;
    }
    display_.render(status_);
}

}  // namespace sorasense
