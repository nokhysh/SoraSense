"""平文を画面やファイルへ残さず、デバイスAPIキーのArgon2idハッシュを生成する。"""

from getpass import getpass

from argon2 import PasswordHasher


def main() -> None:
    """APIキーを画面へ表示せず、確認後にハッシュだけを出力する。"""

    api_key = getpass("Device API key: ")
    confirmation = getpass("Confirm device API key: ")
    if not api_key:
        raise SystemExit("APIキーは空にできません")
    if api_key != confirmation:
        raise SystemExit("APIキーが一致しません")
    print(PasswordHasher().hash(api_key))


if __name__ == "__main__":
    main()
