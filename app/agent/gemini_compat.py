"""固定したGoogle Gen AI SDKのInteractions固有例外をアプリ境界へ公開する。"""

# Interactions APIは公開errorsモジュールとは別の例外階層を使う。
# 非公開パスへの依存をここへ隔離し、SDK更新時は例外回帰テストと同時に見直す。
from google.genai._gaos.lib.compat_errors import (
    APIConnectionError as GeminiAPIConnectionError,
)
from google.genai._gaos.lib.compat_errors import APIError as GeminiAPIError

__all__ = ["GeminiAPIConnectionError", "GeminiAPIError"]
