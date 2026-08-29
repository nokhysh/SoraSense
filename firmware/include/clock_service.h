#pragma once

#include <cstdint>
#include <string>

#include "device_config.h"

namespace sorasense {

/** NTP同期結果と単調増加時計を組み合わせ、保証可能なUTCを提供する。 */
class ClockService {
public:
    explicit ClockService(const DeviceConfig& config);

    void request_synchronization(std::uint32_t now_ms);
    void update(std::uint32_t now_ms);

    [[nodiscard]] bool synchronization_in_progress() const;
    [[nodiscard]] bool should_resynchronize(std::uint32_t now_ms) const;
    [[nodiscard]] bool is_time_valid(std::uint32_t now_ms) const;
    [[nodiscard]] std::string utc_now(std::uint32_t now_ms);

private:
    const DeviceConfig& config_;
    bool has_synchronized_ = false;
    bool synchronization_in_progress_ = false;
    std::uint32_t synchronization_requested_at_ms_ = 0U;
    std::uint32_t synchronized_at_ms_ = 0U;
    std::int64_t synchronized_epoch_seconds_ = 0;
    std::int64_t last_emitted_epoch_seconds_ = 0;
};

}  // namespace sorasense
