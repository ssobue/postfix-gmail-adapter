# postfix-gmail-importer

Postfix `pipe(8)` で受け取った RFC 5322 生メールを、Gmail API `users.messages.import` で Gmail メールボックスへ直接取り込むツールです。

## セットアップ

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
chmod +x postfix_to_gmail.py
```

## 環境変数

```bash
export GMAIL_USER=me
export GMAIL_LABELS=INBOX,UNREAD
# または BASE_DIR=/opt/postfix_to_gmail
```

- `GMAIL_USER`: 既定値は `me`
- `GMAIL_LABELS`: 既定値は `INBOX,UNREAD`
- `BASE_DIR`: `credentials.json` と `token.json` を置くディレクトリ。個別指定より後順位です

## 認証

初回は手動で OAuth 認証を実行して token file を作成してください。Postfix 実行中に初回認証を始めるのは想定していません。

```bash
./postfix_to_gmail.py --init-auth
```

- ローカルサーバーを起動し、表示された URL をブラウザで開いて認証します
- 認証が完了すると token file を保存します
- 以後は保存済み token file を使い、必要に応じて refresh token で自動更新します

## 実行

```bash
cat sample.eml | ./postfix_to_gmail.py
```

- stdin から生メールをバイナリで読み込みます
- `Message-ID` があれば Gmail 検索で重複を確認し、既存なら import をスキップします
- token file が未作成または無効な場合は、先に `--init-auth` を実行する必要があります
- 成功または重複スキップ時は `exit 0`、失敗時は非 0 です
- ログは stderr のみを使用します

## テスト

```bash
python3 -m py_compile postfix_to_gmail.py
python3 -m unittest discover -s tests -v
```

GitHub Actions でも同じ構成でテストします。workflow は `.github/workflows/ci.yml` にあります。

## Postfix 例

`master.cf`

```text
gmailapi unix - n n - - pipe
  flags=Rq user=gmailimport argv=/usr/bin/env
    GMAIL_USER=me
    GMAIL_LABELS=INBOX,UNREAD
    /usr/local/bin/postfix_to_gmail.py
```

`pipe(8)` の `argv` は shell を経由せず直接実行されるため、環境変数を渡すときは `/usr/bin/env` を先頭に置く形にします。

`BASE_DIR` を使う場合は、個別指定の代わりに次のようにも書けます。

```text
gmailapi unix - n n - - pipe
  flags=Rq user=gmailapi argv=/usr/bin/env
    BASE_DIR=/path/to/postfix-to-gmail
    /usr/local/bin/postfix_to_gmail.py
```

`user=` には `postfix` は使えません。`pipe(8)` は mail system owner 権限での実行を拒否するため、`gmailapi` のような専用ユーザーを作成し、そのユーザーに token file と client secrets を読めるようにしてください。

```bash
sudo useradd --system --home /opt/postfix-to-gmail --shell /usr/sbin/nologin gmailapi
sudo install -d -o gmailapi -g gmailapi /opt/postfix-to-gmail
sudo chown gmailapi:gmailapi /opt/postfix-to-gmail/credentials.json
sudo chmod 600 /opt/postfix-to-gmail/credentials.json
```

`transport_maps`

```text
example.com gmailapi:
```
