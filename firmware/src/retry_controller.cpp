#include "retry_controller.h"

#include <algorithm>
#include <cstdint>
#include <limits>
#include <utility>

namespace sorasense {
namespace {

bool deadline_reached(const std::uint32_t now_ms, const std::uint32_t deadline_ms) {
    return static_cast<std::int32_t>(now_ms - deadline_ms) >= 0;
}

std::uint32_t retry_after_milliseconds(const std::uint32_t seconds) {
    constexpr std::uint32_t maximum_retry_after_seconds = 24U * 60U * 60U;
    const std::uint32_t bounded_seconds = std::min(seconds, maximum_retry_after_seconds);
    return bounded_seconds * 1'000U;
}

}  // namespace

void RetryController::replace(Measurement measurement, const std::uint32_t now_ms) {
    pending_ = std::move(measurement);
    retry_count_ = 0U;
    next_attempt_ms_ = now_ms;
}

bool RetryController::has_pending() const {
    return pending_.has_value();
}

bool RetryController::is_due(const std::uint32_t now_ms) const {
    return has_pending() && deadline_reached(now_ms, next_attempt_ms_);
}

const Measurement* RetryController::pending() const {
    return pending_ ? &pending_.value() : nullptr;
}

std::uint8_t RetryController::retry_count() const {
    return retry_count_;
}

std::uint32_t RetryController::next_attempt_ms() const {
    return next_attempt_ms_;
}

RetryUpdate RetryController::apply_result(
    const std::string& sent_message_id,
    const SendResult& result,
    const std::uint32_t now_ms,
    const std::uint32_t random_value
) {
    if (!pending_ || pending_->message_id != sent_message_id) {
        return RetryUpdate::ignored;
    }

    if (result.disposition == SendDisposition::accepted) {
        pending_.reset();
        return RetryUpdate::accepted;
    }
    if (result.disposition == SendDisposition::discard) {
        pending_.reset();
        return RetryUpdate::discarded;
    }
    if (result.disposition == SendDisposition::authentication_error) {
        pending_.reset();
        return RetryUpdate::authentication_error;
    }
    if (retry_count_ >= maximum_retry_count) {
        pending_.reset();
        return RetryUpdate::retries_exhausted;
    }

    ++retry_count_;
    const std::uint32_t multiplier = 1U << (retry_count_ - 1U);
    const std::uint32_t base_interval = std::min(
        initial_interval_ms * multiplier,
        maximum_interval_ms
    );
    const std::uint32_t jitter_limit = std::min(
        base_interval / 5U,
        maximum_interval_ms - base_interval
    );
    const std::uint32_t jitter = jitter_limit == 0U
        ? 0U
        : random_value % (jitter_limit + 1U);
    const std::uint32_t calculated_interval = base_interval + jitter;
    const std::uint32_t server_interval = retry_after_milliseconds(
        result.retry_after_seconds
    );
    next_attempt_ms_ = now_ms + std::max(calculated_interval, server_interval);
    return RetryUpdate::retry_scheduled;
}

}  // namespace sorasense
