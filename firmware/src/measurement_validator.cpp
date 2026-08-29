#include "measurement_validator.h"

#include <cmath>

namespace sorasense {

bool is_valid_measurement(const float temperature_celsius, const float humidity_percent) {
    if (!std::isfinite(temperature_celsius) || !std::isfinite(humidity_percent)) {
        return false;
    }

    constexpr float minimum_temperature_celsius = -40.0F;
    constexpr float maximum_temperature_celsius = 85.0F;
    constexpr float minimum_humidity_percent = 0.0F;
    constexpr float maximum_humidity_percent = 100.0F;

    return temperature_celsius >= minimum_temperature_celsius
        && temperature_celsius <= maximum_temperature_celsius
        && humidity_percent >= minimum_humidity_percent
        && humidity_percent <= maximum_humidity_percent;
}

}  // namespace sorasense
