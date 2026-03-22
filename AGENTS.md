# Repository Guidelines

## Purpose

- このリポジトリは、Postfix `pipe(8)` で受け取った RFC 5322 生メールを Gmail API `users.messages.import` で Gmail メールボックスへ取り込む単機能ツールです。

## Key Files

- `postfix_to_gmail.py`: OAuth token 管理、stdin 受信、Message-ID 重複確認、Gmail import、stderr ログ、終了コード制御を担当します。
- `requirements.txt`: 実行に必要な Python 依存関係を定義します。
- `README.md`: セットアップ、OAuth 認証、環境変数、Postfix 連携の最小限ドキュメントです。
- `tests/test_postfix_to_gmail.py`: 依存をスタブ化した unit test です。
- `.github/workflows/ci.yml`: GitHub Actions 上で構文確認と unit test を実行します。

## Work Rules

- SMTP 送信はしないこと。`messages.send` は使用禁止です。
- MIME を再構築しないこと。入力メールは生バイト列のまま `raw` に載せます。
- stdout を使わないこと。ログやエラーは必ず stderr に出します。
- 失敗時は Postfix 再試行のため非 0 を返します。
- 動作制御は環境変数 `GMAIL_USER`、`GMAIL_LABELS`、`BASE_DIR` に従います。

## Operational Assumptions

- v1 は OAuth client secrets + saved token file 前提です。サービスアカウント委任は扱いません。
- 重複排除は Message-ID ベースの best-effort です。`Message-ID` がないメールはそのまま import します。
- 既定ラベルは `INBOX,UNREAD` です。
- 初回認証は `--init-auth` を手動実行してから Postfix 連携を有効化します。

## Verification

- 変更後は少なくとも `python3 -m py_compile postfix_to_gmail.py` を実行してください。
- `python3 -m unittest discover -s tests -v` を実行してください。
- 正常系として stdin から `.eml` を流し込む経路を確認してください。
- 異常系として token 不備または API 失敗時に stderr 出力と非 0 終了を確認してください。
