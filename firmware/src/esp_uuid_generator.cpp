#include "esp_uuid_generator.h"

#include <array>
#include <cstdio>

#include <esp_system.h>

namespace sorasense {

std::string EspUuidGenerator::generate_v4() {
    std::array<std::uint8_t, 16> bytes{};
    esp_fill_random(bytes.data(), bytes.size());
    bytes[6] = static_cast<std::uint8_t>((bytes[6] & 0x0FU) | 0x40U);
    bytes[8] = static_cast<std::uint8_t>((bytes[8] & 0x3FU) | 0x80U);

    std::array<char, 37> uuid{};
    std::snprintf(
        uuid.data(),
        uuid.size(),
        "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        static_cast<unsigned int>(bytes[0]),
        static_cast<unsigned int>(bytes[1]),
        static_cast<unsigned int>(bytes[2]),
        static_cast<unsigned int>(bytes[3]),
        static_cast<unsigned int>(bytes[4]),
        static_cast<unsigned int>(bytes[5]),
        static_cast<unsigned int>(bytes[6]),
        static_cast<unsigned int>(bytes[7]),
        static_cast<unsigned int>(bytes[8]),
        static_cast<unsigned int>(bytes[9]),
        static_cast<unsigned int>(bytes[10]),
        static_cast<unsigned int>(bytes[11]),
        static_cast<unsigned int>(bytes[12]),
        static_cast<unsigned int>(bytes[13]),
        static_cast<unsigned int>(bytes[14]),
        static_cast<unsigned int>(bytes[15])
    );
    return uuid.data();
}

}  // namespace sorasense
