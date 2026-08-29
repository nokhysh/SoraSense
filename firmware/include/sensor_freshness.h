#pragma once

#include <cstdint>

namespace sorasense {

constexpr std::uint32_t maximum_sensor_reading_age_ms = 5'000U;

/** 初期化後または最終読取後の経過時間から、センサー読取停止を判定する。 */
[[nodiscard]] bool has_sensor_reading_expired(
    std::uint32_t now_ms,
    std::uint32_t initialized_at_ms,
    bool has_reading,
    std::uint32_t reading_at_ms
);

/** 読み取り鮮度を追跡し、停止したセンサーを再初期化可能な状態へ戻す。 */
class SensorFreshnessTracker {
public:
    void mark_initialized(std::uint32_t now_ms);
    void mark_reading(std::uint32_t now_ms);
    void mark_unavailable();

    /** 読み取りが失効した場合は準備済み状態を解除し、trueを返す。 */
    bool invalidate_if_expired(std::uint32_t now_ms);

    [[nodiscard]] bool is_ready() const;
    [[nodiscard]] bool has_reading() const;
    [[nodiscard]] bool is_expired(std::uint32_t now_ms) const;

private:
    bool ready_ = false;
    bool has_reading_ = false;
    std::uint32_t initialized_at_ms_ = 0U;
    std::uint32_t reading_at_ms_ = 0U;
};

}  // namespace sorasense
