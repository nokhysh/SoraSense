#include "clock_service.h"

#include <algorithm>
#include <array>
#include <ctime>

#include <Arduino.h>
#include <esp_sntp.h>

namespace sorasense {
namespace {

volatile bool time_synchronized = false;

void on_time_synchronized(struct timeval*) {
    time_synchronized = true;
}

}  // namespace

ClockService::ClockService(const DeviceConfig& config) : config_(config) {}

void ClockService::request_synchronization(const std::uint32_t now_ms) {
    time_synchronized = false;
    synchronization_in_progress_ = true;
    synchronization_requested_at_ms_ = now_ms;
    sntp_set_time_sync_notification_cb(on_time_synchronized);
    configTime(
        0,
        0,
        config_.ntp_server_1,
        config_.ntp_server_2,
        config_.ntp_server_3
    );
}

void ClockService::update(const std::uint32_t now_ms) {
    if (!time_synchronized) {
        if (synchronization_in_progress_
            && now_ms - synchronization_requested_at_ms_ >= config_.clock_retry_interval_ms) {
            synchronization_in_progress_ = false;
        }
        return;
    }
    time_synchronized = false;

    const std::time_t current_time = std::time(nullptr);
    constexpr std::time_t minimum_valid_epoch = 1'609'459'200;
    if (current_time < minimum_valid_epoch) {
        synchronization_in_progress_ = false;
        return;
    }

    synchronized_epoch_seconds_ = static_cast<std::int64_t>(current_time);
    synchronized_at_ms_ = now_ms;
    has_synchronized_ = true;
    synchronization_in_progress_ = false;
}

bool ClockService::synchronization_in_progress() const {
    return synchronization_in_progress_;
}

bool ClockService::should_resynchronize(const std::uint32_t now_ms) const {
    return !has_synchronized_
        || now_ms - synchronized_at_ms_ >= config_.clock_resync_interval_ms;
}

bool ClockService::is_time_valid(const std::uint32_t now_ms) const {
    return has_synchronized_ && now_ms - synchronized_at_ms_ <= config_.clock_validity_ms;
}

std::string ClockService::utc_now(const std::uint32_t now_ms) {
    if (!is_time_valid(now_ms)) {
        return {};
    }

    const std::int64_t elapsed_seconds = (now_ms - synchronized_at_ms_) / 1'000U;
    const std::int64_t candidate = synchronized_epoch_seconds_ + elapsed_seconds;
    const std::int64_t epoch_seconds = std::max(candidate, last_emitted_epoch_seconds_);
    last_emitted_epoch_seconds_ = epoch_seconds;

    const std::time_t value = static_cast<std::time_t>(epoch_seconds);
    std::tm utc{};
    gmtime_r(&value, &utc);
    std::array<char, 21> formatted{};
    if (std::strftime(formatted.data(), formatted.size(), "%Y-%m-%dT%H:%M:%SZ", &utc) == 0U) {
        return {};
    }
    return formatted.data();
}

}  // namespace sorasense
