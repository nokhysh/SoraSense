#include "send_result.h"

namespace sorasense {

SendResult classify_send_result(
    const bool transport_succeeded,
    const int http_status,
    const std::uint32_t retry_after_seconds
) {
    if (!transport_succeeded) {
        return {SendDisposition::retryable, http_status, 0U};
    }
    if (http_status == 200 || http_status == 201) {
        return {SendDisposition::accepted, http_status, 0U};
    }
    if (http_status == 401 || http_status == 403) {
        return {SendDisposition::authentication_error, http_status, 0U};
    }
    if (http_status == 429) {
        return {SendDisposition::retryable, http_status, retry_after_seconds};
    }
    if (http_status >= 500 && http_status <= 599) {
        return {SendDisposition::retryable, http_status, 0U};
    }
    return {SendDisposition::discard, http_status, 0U};
}

}  // namespace sorasense
