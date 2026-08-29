#pragma once

#include "measurement_factory.h"

namespace sorasense {

/** ESP32の暗号学的乱数源からRFC 4122 UUID v4を生成する。 */
class EspUuidGenerator final : public UuidGenerator {
public:
    [[nodiscard]] std::string generate_v4() override;
};

}  // namespace sorasense
