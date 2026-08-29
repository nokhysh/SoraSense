#pragma once

#include <cstdint>
#include <memory>
#include <optional>

namespace sorasense {

struct SensorReading {
    float temperature_celsius;
    float humidity_percent;
};

/** ENV IV Unitの初期化と、最新のSHT40測定値の取得を担当する。 */
class SensorReader {
public:
    SensorReader();
    ~SensorReader();

    SensorReader(const SensorReader&) = delete;
    SensorReader& operator=(const SensorReader&) = delete;

    bool initialize(std::uint32_t now_ms);
    void update(std::uint32_t now_ms);
    [[nodiscard]] std::optional<SensorReading> latest(std::uint32_t now_ms) const;
    [[nodiscard]] bool initialized() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace sorasense
