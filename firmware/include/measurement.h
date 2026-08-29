#pragma once

#include <string>

namespace sorasense {

/** APIへ送信する1件の測定データ。 */
struct Measurement {
    std::string message_id;
    std::string device_id;
    std::string measured_at;
    float temperature_celsius;
    float humidity_percent;
};

}  // namespace sorasense
