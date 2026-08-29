#include <Arduino.h>

#include "app_controller.h"

namespace {
sorasense::AppController application;
}

void setup() {
    application.begin();
}

void loop() {
    application.update();
    delay(10);
}
