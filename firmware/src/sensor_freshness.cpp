#include "sensor_freshness.h"

namespace sorasense {

bool has_sensor_reading_expired(
    const std::uint32_t now_ms,
    const std::uint32_t initialized_at_ms,
    const bool has_reading,
    const std::uint32_t reading_at_ms
) {
    const std::uint32_t freshness_reference_ms = has_reading
        ? reading_at_ms
        : initialized_at_ms;
    return now_ms - freshness_reference_ms > maximum_sensor_reading_age_ms;
}

void SensorFreshnessTracker::mark_initialized(const std::uint32_t now_ms) {
    ready_ = true;
    has_reading_ = false;
    initialized_at_ms_ = now_ms;
    reading_at_ms_ = 0U;
}

void SensorFreshnessTracker::mark_reading(const std::uint32_t now_ms) {
    if (!ready_) {
        return;
    }
    has_reading_ = true;
    reading_at_ms_ = now_ms;
}

void SensorFreshnessTracker::mark_unavailable() {
    ready_ = false;
    has_reading_ = false;
}

bool SensorFreshnessTracker::invalidate_if_expired(const std::uint32_t now_ms) {
    if (!ready_ || !is_expired(now_ms)) {
        return false;
    }
    mark_unavailable();
    return true;
}

bool SensorFreshnessTracker::is_ready() const {
    return ready_;
}

bool SensorFreshnessTracker::has_reading() const {
    return has_reading_;
}

bool SensorFreshnessTracker::is_expired(const std::uint32_t now_ms) const {
    return has_sensor_reading_expired(
        now_ms,
        initialized_at_ms_,
        has_reading_,
        reading_at_ms_
    );
}

}  // namespace sorasense
