"""ローカルHTTP運用の公開境界を検証する。"""

from pathlib import Path


def test_compose_uses_configurable_lan_binding_without_global_publish() -> None:
    """appは指定アドレスへ公開し、全インターフェースへ固定公開しない。"""

    compose = Path("compose.yaml").read_text()

    assert '"${APP_BIND_ADDRESS:-127.0.0.1}:8000:8000"' in compose
    assert '"0.0.0.0:8000:8000"' not in compose
    assert '"127.0.0.1:3000:3000"' in compose


def test_environment_example_documents_private_lan_address() -> None:
    """設定例に端末から到達可能なプライベートIPv4の指定を含める。"""

    example = Path(".env.example").read_text()

    assert "APP_BIND_ADDRESS=192.168.1.100" in example
