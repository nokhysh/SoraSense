#pragma once

#include "device_config.h"
#include "measurement.h"
#include "send_result.h"

namespace sorasense {

/** CA検証付きHTTPSで測定データAPIを呼び出す。 */
class ApiClient {
public:
    explicit ApiClient(const DeviceConfig& config);
    [[nodiscard]] SendResult send(const Measurement& measurement) const;

private:
    const DeviceConfig& config_;
};

}  // namespace sorasense
