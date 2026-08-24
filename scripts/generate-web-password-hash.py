"""平文をファイルへ残さず、Web利用者パスワードのArgon2idハッシュを生成する。"""

from getpass import getpass

from argon2 import PasswordHasher


def main() -> None:
    """パスワードを確認入力し、ハッシュだけを標準出力へ表示する。"""

    password = getpass("Web password: ")
    confirmation = getpass("Confirm web password: ")
    if not password:
        raise SystemExit("パスワードは空にできません")
    if password != confirmation:
        raise SystemExit("パスワードが一致しません")
    print(PasswordHasher().hash(password))


if __name__ == "__main__":
    main()
