#pragma once

namespace sorasense {

/**
 * 温湿度がセンサーデバイスから送信できる値かを判定する。
 *
 * ENV IV Unitや通信処理に依存しない純粋な判定として分離し、実機がなくても
 * 詳細設計で定めた入力境界を検証できるようにする。
 */
[[nodiscard]] bool is_valid_measurement(float temperature_celsius, float humidity_percent);

}  // namespace sorasense
