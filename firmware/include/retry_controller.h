#pragma once

#include <cstdint>
#include <optional>
#include <string>

#include "measurement.h"
#include "send_result.h"

namespace sorasense {

enum class RetryUpdate {
    ignored,
    accepted,
    discarded,
    authentication_error,
    retry_scheduled,
    retries_exhausted,
};

/** 最新の未送信データ1件と、上限付き指数バックオフを管理する。 */
class RetryController {
public:
    static constexpr std::uint8_t maximum_retry_count = 6U;
    static constexpr std::uint32_t initial_interval_ms = 5'000U;
    static constexpr std::uint32_t maximum_interval_ms = 300'000U;

    void replace(Measurement measurement, std::uint32_t now_ms);

    [[nodiscard]] bool has_pending() const;
    [[nodiscard]] bool is_due(std::uint32_t now_ms) const;
    [[nodiscard]] const Measurement* pending() const;
    [[nodiscard]] std::uint8_t retry_count() const;
    [[nodiscard]] std::uint32_t next_attempt_ms() const;

    RetryUpdate apply_result(
        const std::string& sent_message_id,
        const SendResult& result,
        std::uint32_t now_ms,
        std::uint32_t random_value
    );

private:
    std::optional<Measurement> pending_;
    std::uint8_t retry_count_ = 0U;
    std::uint32_t next_attempt_ms_ = 0U;
};

}  // namespace sorasense
