#include "status_display.h"

#include <M5Unified.h>

namespace sorasense {
namespace {

const char* state_name(const DeviceState state) {
    switch (state) {
        case DeviceState::initializing:
            return "INIT";
        case DeviceState::ready:
            return "READY";
        case DeviceState::measuring:
            return "MEASURE";
        case DeviceState::pending_send:
            return "SEND";
        case DeviceState::retry_wait:
            return "RETRY";
        case DeviceState::authentication_error:
            return "AUTH ERROR";
        case DeviceState::configuration_error:
            return "CONFIG ERROR";
    }
    return "UNKNOWN";
}

}  // namespace

void StatusDisplay::begin() {
    if (M5.Display.height() > M5.Display.width()) {
        M5.Display.setRotation(1);
    }
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.fillScreen(TFT_BLACK);
}

void StatusDisplay::render(const DeviceStatus& status) {
    M5.Display.startWrite();
    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setCursor(4, 4);
    M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
    M5.Display.println("SoraSense");
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.printf("State : %s\n", state_name(status.state));
    M5.Display.printf(
        "Sensor: %s  Invalid:%lu\n",
        status.sensor_ready ? "OK" : "WAIT",
        static_cast<unsigned long>(status.invalid_reading_count)
    );
    M5.Display.printf("WiFi  : %s\n", status.wifi_connected ? "OK" : "WAIT");
    M5.Display.printf("Time  : %s\n", status.clock_valid ? "OK" : "WAIT");
    if (status.latest_reading) {
        M5.Display.printf(
            "Temp %.1f C  Hum %.1f %%\n",
            status.latest_reading->temperature_celsius,
            status.latest_reading->humidity_percent
        );
    } else {
        M5.Display.println("Temp --.- C  Hum --.- %");
    }
    M5.Display.printf("Send  : %s\n", status.last_send_result.c_str());
    M5.Display.endWrite();
}

}  // namespace sorasense
