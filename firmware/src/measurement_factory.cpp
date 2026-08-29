#include "measurement_factory.h"

#include <utility>

namespace sorasense {

MeasurementFactory::MeasurementFactory(std::string device_id, UuidGenerator& uuid_generator)
    : device_id_(std::move(device_id)), uuid_generator_(uuid_generator) {}

Measurement MeasurementFactory::create(
    std::string measured_at,
    const float temperature_celsius,
    const float humidity_percent
) {
    return Measurement{
        uuid_generator_.generate_v4(),
        device_id_,
        std::move(measured_at),
        temperature_celsius,
        humidity_percent,
    };
}

}  // namespace sorasense
