#pragma once

#include <cstdint>

namespace sorasense {

enum class SendDisposition {
    accepted,
    retryable,
    discard,
    authentication_error,
};

/** HTTP通信結果を再送制御が扱える分類へ変換した値。 */
struct SendResult {
    SendDisposition disposition;
    int http_status;
    std::uint32_t retry_after_seconds;
};

/** 詳細設計8章のHTTP・通信失敗分類を適用する。 */
[[nodiscard]] SendResult classify_send_result(
    bool transport_succeeded,
    int http_status,
    std::uint32_t retry_after_seconds = 0U
);

}  // namespace sorasense
