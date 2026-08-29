#include <limits>
#include <string>

#include <unity.h>

#include "device_config.h"
#include "measurement_factory.h"
#include "measurement_validator.h"
#include "retry_controller.h"
#include "sensor_freshness.h"
#include "send_result.h"

namespace {

class FakeUuidGenerator final : public sorasense::UuidGenerator {
public:
    std::string generate_v4() override {
        return "550e8400-e29b-41d4-a716-446655440000";
    }
};

sorasense::Measurement measurement(const std::string& message_id) {
    return {
        message_id,
        "living-room-01",
        "2026-08-29T00:00:00Z",
        25.0F,
        50.0F,
    };
}

sorasense::DeviceConfig valid_config() {
    sorasense::DeviceConfig config;
    config.device_id = "living-room-01";
    config.device_api_key = "api-key";
    config.api_base_url = "http://192.168.1.100:8000";
    config.wifi_ssid = "ssid";
    config.wifi_password = "password";
    config.ntp_server_1 = "ntp1.example.com";
    config.ntp_server_2 = "ntp2.example.com";
    return config;
}

}  // namespace

void setUp() {}

void tearDown() {}

void test_accepts_typical_measurement() {
    TEST_ASSERT_TRUE(sorasense::is_valid_measurement(25.0F, 50.0F));
}

void test_accepts_temperature_boundaries() {
    TEST_ASSERT_TRUE(sorasense::is_valid_measurement(-40.0F, 50.0F));
    TEST_ASSERT_TRUE(sorasense::is_valid_measurement(85.0F, 50.0F));
}

void test_rejects_temperature_outside_boundaries() {
    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(-40.01F, 50.0F));
    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(85.01F, 50.0F));
}

void test_accepts_humidity_boundaries() {
    TEST_ASSERT_TRUE(sorasense::is_valid_measurement(25.0F, 0.0F));
    TEST_ASSERT_TRUE(sorasense::is_valid_measurement(25.0F, 100.0F));
}

void test_rejects_humidity_outside_boundaries() {
    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(25.0F, -0.01F));
    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(25.0F, 100.01F));
}

void test_rejects_nan() {
    const float nan = std::numeric_limits<float>::quiet_NaN();

    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(nan, 50.0F));
    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(25.0F, nan));
}

void test_rejects_positive_infinity() {
    const float infinity = std::numeric_limits<float>::infinity();

    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(infinity, 50.0F));
    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(25.0F, infinity));
}

void test_rejects_negative_infinity() {
    const float negative_infinity = -std::numeric_limits<float>::infinity();

    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(negative_infinity, 50.0F));
    TEST_ASSERT_FALSE(sorasense::is_valid_measurement(25.0F, negative_infinity));
}

void test_measurement_factory_assigns_new_id_and_payload() {
    FakeUuidGenerator uuid_generator;
    sorasense::MeasurementFactory factory("living-room-01", uuid_generator);

    const auto result = factory.create("2026-08-29T00:00:00Z", 24.5F, 55.5F);

    TEST_ASSERT_EQUAL_STRING("550e8400-e29b-41d4-a716-446655440000", result.message_id.c_str());
    TEST_ASSERT_EQUAL_STRING("living-room-01", result.device_id.c_str());
    TEST_ASSERT_EQUAL_STRING("2026-08-29T00:00:00Z", result.measured_at.c_str());
    TEST_ASSERT_FLOAT_WITHIN(0.001F, 24.5F, result.temperature_celsius);
    TEST_ASSERT_FLOAT_WITHIN(0.001F, 55.5F, result.humidity_percent);
}

void test_classifies_send_results() {
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::retryable),
        static_cast<int>(sorasense::classify_send_result(false, -1).disposition)
    );
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::accepted),
        static_cast<int>(sorasense::classify_send_result(true, 201).disposition)
    );
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::accepted),
        static_cast<int>(sorasense::classify_send_result(true, 200).disposition)
    );
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::authentication_error),
        static_cast<int>(sorasense::classify_send_result(true, 401).disposition)
    );
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::authentication_error),
        static_cast<int>(sorasense::classify_send_result(true, 403).disposition)
    );
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::discard),
        static_cast<int>(sorasense::classify_send_result(true, 400).disposition)
    );
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::discard),
        static_cast<int>(sorasense::classify_send_result(true, 404).disposition)
    );
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::retryable),
        static_cast<int>(sorasense::classify_send_result(true, 429, 30U).disposition)
    );
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::SendDisposition::retryable),
        static_cast<int>(sorasense::classify_send_result(true, 502).disposition)
    );
}

void test_retry_preserves_message_id_and_uses_backoff() {
    sorasense::RetryController controller;
    controller.replace(measurement("message-1"), 1'000U);

    TEST_ASSERT_TRUE(controller.is_due(1'000U));
    const auto update = controller.apply_result(
        "message-1",
        sorasense::classify_send_result(false, -1),
        1'000U,
        0U
    );

    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::RetryUpdate::retry_scheduled),
        static_cast<int>(update)
    );
    TEST_ASSERT_EQUAL_UINT8(1U, controller.retry_count());
    TEST_ASSERT_EQUAL_UINT32(6'000U, controller.next_attempt_ms());
    TEST_ASSERT_FALSE(controller.is_due(5'999U));
    TEST_ASSERT_TRUE(controller.is_due(6'000U));
    TEST_ASSERT_NOT_NULL(controller.pending());
    TEST_ASSERT_EQUAL_STRING("message-1", controller.pending()->message_id.c_str());
}

void test_retry_after_takes_larger_interval() {
    sorasense::RetryController controller;
    controller.replace(measurement("message-1"), 1'000U);

    controller.apply_result(
        "message-1",
        sorasense::classify_send_result(true, 429, 30U),
        1'000U,
        0U
    );

    TEST_ASSERT_EQUAL_UINT32(31'000U, controller.next_attempt_ms());
}

void test_retry_stops_after_six_retries() {
    sorasense::RetryController controller;
    controller.replace(measurement("message-1"), 0U);
    const auto retryable = sorasense::classify_send_result(true, 503);

    for (std::uint8_t retry = 0U; retry < 6U; ++retry) {
        TEST_ASSERT_EQUAL_INT(
            static_cast<int>(sorasense::RetryUpdate::retry_scheduled),
            static_cast<int>(controller.apply_result("message-1", retryable, 0U, 0U))
        );
    }
    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::RetryUpdate::retries_exhausted),
        static_cast<int>(controller.apply_result("message-1", retryable, 0U, 0U))
    );
    TEST_ASSERT_FALSE(controller.has_pending());
}

void test_new_measurement_replaces_pending_and_ignores_old_result() {
    sorasense::RetryController controller;
    controller.replace(measurement("old-message"), 0U);
    controller.replace(measurement("new-message"), 60'000U);

    const auto update = controller.apply_result(
        "old-message",
        sorasense::classify_send_result(true, 201),
        60'000U,
        0U
    );

    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::RetryUpdate::ignored),
        static_cast<int>(update)
    );
    TEST_ASSERT_EQUAL_UINT8(0U, controller.retry_count());
    TEST_ASSERT_EQUAL_STRING("new-message", controller.pending()->message_id.c_str());
}

void test_authentication_error_discards_pending() {
    sorasense::RetryController controller;
    controller.replace(measurement("message-1"), 0U);

    const auto update = controller.apply_result(
        "message-1",
        sorasense::classify_send_result(true, 401),
        0U,
        0U
    );

    TEST_ASSERT_EQUAL_INT(
        static_cast<int>(sorasense::RetryUpdate::authentication_error),
        static_cast<int>(update)
    );
    TEST_ASSERT_FALSE(controller.has_pending());
}

void test_validates_required_device_configuration_without_secret_output() {
    auto config = valid_config();
    TEST_ASSERT_TRUE(sorasense::is_valid_device_config(config));
    config.api_base_url = "http://10.0.0.1:8000";
    TEST_ASSERT_TRUE(sorasense::is_valid_device_config(config));
    config.api_base_url = "http://172.31.255.254:8000/";
    TEST_ASSERT_TRUE(sorasense::is_valid_device_config(config));

    config.device_id = "Invalid_Device";
    TEST_ASSERT_FALSE(sorasense::is_valid_device_config(config));
    config = valid_config();
    config.api_base_url = "https://192.168.1.100:8000";
    TEST_ASSERT_FALSE(sorasense::is_valid_device_config(config));
    config = valid_config();
    config.api_base_url = "http://127.0.0.1:8000";
    TEST_ASSERT_FALSE(sorasense::is_valid_device_config(config));
    config = valid_config();
    config.api_base_url = "http://8.8.8.8:8000";
    TEST_ASSERT_FALSE(sorasense::is_valid_device_config(config));
    config = valid_config();
    config.api_base_url = "http://192.168.1.100";
    TEST_ASSERT_FALSE(sorasense::is_valid_device_config(config));
    config = valid_config();
    config.api_base_url = "http://192.168.1.100:8080";
    TEST_ASSERT_FALSE(sorasense::is_valid_device_config(config));
    config = valid_config();
    config.wifi_password = "";
    TEST_ASSERT_FALSE(sorasense::is_valid_device_config(config));
    config = valid_config();
    config.ntp_server_2 = "";
    TEST_ASSERT_FALSE(sorasense::is_valid_device_config(config));
}

void test_sensor_reading_expires_only_after_five_seconds() {
    TEST_ASSERT_FALSE(sorasense::has_sensor_reading_expired(5'000U, 0U, false, 0U));
    TEST_ASSERT_TRUE(sorasense::has_sensor_reading_expired(5'001U, 0U, false, 0U));

    TEST_ASSERT_FALSE(sorasense::has_sensor_reading_expired(9'000U, 0U, true, 4'000U));
    TEST_ASSERT_TRUE(sorasense::has_sensor_reading_expired(9'001U, 0U, true, 4'000U));
}

void test_stopped_sensor_becomes_unready_after_reading_expires() {
    sorasense::SensorFreshnessTracker freshness;
    freshness.mark_initialized(1'000U);
    freshness.mark_reading(2'000U);

    TEST_ASSERT_TRUE(freshness.is_ready());
    TEST_ASSERT_FALSE(freshness.invalidate_if_expired(7'000U));
    TEST_ASSERT_TRUE(freshness.is_ready());

    TEST_ASSERT_TRUE(freshness.invalidate_if_expired(7'001U));
    TEST_ASSERT_FALSE(freshness.is_ready());
    TEST_ASSERT_FALSE(freshness.has_reading());
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_accepts_typical_measurement);
    RUN_TEST(test_accepts_temperature_boundaries);
    RUN_TEST(test_rejects_temperature_outside_boundaries);
    RUN_TEST(test_accepts_humidity_boundaries);
    RUN_TEST(test_rejects_humidity_outside_boundaries);
    RUN_TEST(test_rejects_nan);
    RUN_TEST(test_rejects_positive_infinity);
    RUN_TEST(test_rejects_negative_infinity);
    RUN_TEST(test_measurement_factory_assigns_new_id_and_payload);
    RUN_TEST(test_classifies_send_results);
    RUN_TEST(test_retry_preserves_message_id_and_uses_backoff);
    RUN_TEST(test_retry_after_takes_larger_interval);
    RUN_TEST(test_retry_stops_after_six_retries);
    RUN_TEST(test_new_measurement_replaces_pending_and_ignores_old_result);
    RUN_TEST(test_authentication_error_discards_pending);
    RUN_TEST(test_validates_required_device_configuration_without_secret_output);
    RUN_TEST(test_sensor_reading_expires_only_after_five_seconds);
    RUN_TEST(test_stopped_sensor_becomes_unready_after_reading_expires);
    return UNITY_END();
}
