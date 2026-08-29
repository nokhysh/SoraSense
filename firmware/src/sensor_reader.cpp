#include "sensor_reader.h"

#include <M5Unified.h>
#include <M5UnitUnified.h>
#include <M5UnitUnifiedENV.h>
#include <Wire.h>

#include "sensor_freshness.h"

namespace sorasense {

class SensorReader::Impl {
public:
    m5::unit::UnitUnified units;
    m5::unit::UnitENV4 env;
    SensorFreshnessTracker freshness;
    SensorReading reading{};
};

SensorReader::SensorReader() : impl_(std::make_unique<Impl>()) {}

SensorReader::~SensorReader() = default;

bool SensorReader::initialize(const std::uint32_t now_ms) {
    const auto sda = M5.getPin(m5::pin_name_t::port_a_sda);
    const auto scl = M5.getPin(m5::pin_name_t::port_a_scl);
    if (sda < 0 || scl < 0) {
        impl_->freshness.mark_unavailable();
        return false;
    }

    // 切断前のUnit状態を持ち越さず、I2Cとセンサーを一組で初期化し直す。
    impl_.reset();
    Wire.end();
    impl_ = std::make_unique<Impl>();
    if (!Wire.begin(sda, scl, 400'000U)) {
        return false;
    }
    const bool ready = impl_->units.add(impl_->env, Wire) && impl_->units.begin();
    if (ready) {
        impl_->freshness.mark_initialized(now_ms);
    }
    return ready;
}

void SensorReader::update(const std::uint32_t now_ms) {
    if (!impl_->freshness.is_ready()) {
        return;
    }
    impl_->units.update();
    if (impl_->env.sht40.updated()) {
        impl_->reading = {
            impl_->env.sht40.temperature(),
            impl_->env.sht40.humidity(),
        };
        impl_->freshness.mark_reading(now_ms);
        return;
    }

    impl_->freshness.invalidate_if_expired(now_ms);
}

std::optional<SensorReading> SensorReader::latest(const std::uint32_t now_ms) const {
    if (!impl_->freshness.is_ready() || !impl_->freshness.has_reading()
        || impl_->freshness.is_expired(now_ms)) {
        return std::nullopt;
    }
    return impl_->reading;
}

bool SensorReader::initialized() const {
    return impl_->freshness.is_ready();
}

}  // namespace sorasense
