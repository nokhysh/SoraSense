#pragma once

#include "device_config.h"
#include "measurement.h"
#include "send_result.h"

namespace sorasense {

/** 管理対象LAN内のHTTP測定データAPIを呼び出す。 */
class ApiClient {
public:
    explicit ApiClient(const DeviceConfig& config);
    [[nodiscard]] SendResult send(const Measurement& measurement) const;

private:
    const DeviceConfig& config_;
};

}  // namespace sorasense
