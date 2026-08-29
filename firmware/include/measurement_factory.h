#pragma once

#include <string>

#include "measurement.h"

namespace sorasense {

/** UUID生成を実機乱数源から分離する境界。 */
class UuidGenerator {
public:
    virtual ~UuidGenerator() = default;
    [[nodiscard]] virtual std::string generate_v4() = 0;
};

/** 有効なセンサー値からAPI送信用データを組み立てる。 */
class MeasurementFactory {
public:
    MeasurementFactory(std::string device_id, UuidGenerator& uuid_generator);

    [[nodiscard]] Measurement create(
        std::string measured_at,
        float temperature_celsius,
        float humidity_percent
    );

private:
    std::string device_id_;
    UuidGenerator& uuid_generator_;
};

}  // namespace sorasense
