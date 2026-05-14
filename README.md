# vm-play-server

`vm-play-server` は、AI を使った実験的な仮想コード実行サーバーです。ローカル HTTP API で自然言語の指示を受け取り、OpenAI API で自己完結した Python スクリプトを生成し、そのスクリプトを隔離された Docker コンテナ内で実行します。実行ログはローカルのログビューアーで確認でき、ngrok を使って外部共有用の URL も発行できます。

現在の Python パッケージ名と CLI コマンド名は `aivenv` です。

## 主な機能

- 実行開始・停止用のローカル FastAPI サーバー
- 自然言語の指示から Python コードを生成する OpenAI 連携
- CPU・メモリ制限つきの Docker コンテナ実行
- ストリーミング表示できるローカルログビューアー
- 実行ログ共有用の ngrok トンネル
- Pytest によるユニットテスト・統合テスト

## 必要なもの

- Python 3.11 以上
- Docker Desktop、または接続可能な Docker デーモン
- OpenAI API キー
- ngrok authtoken

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

`.env` を編集するか、次のように必要なシークレットを環境変数へ設定します。

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:NGROK_AUTHTOKEN = "..."
```

## 起動方法

API サーバーとログサーバーを起動します。

```powershell
aivenv start
```

デフォルトでは、API は `http://127.0.0.1:8080`、ログビューアーは `http://127.0.0.1:8081` で起動します。

ポートやモデルは次のように変更できます。

```powershell
aivenv start --port 8090 --log-port 8091 --model gpt-4o
```

## API

実行を開始します。

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8080/run `
  -ContentType "application/json" `
  -Body '{"instruction":"Create and run a small Python hello-world script."}'
```

実行中の処理を停止します。

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8080/stop `
  -ContentType "application/json" `
  -Body '{"execution_id":"default"}'
```

ローカルログは次の URL で確認できます。

```text
http://127.0.0.1:8081
```

## 設定

設定は CLI オプションと環境変数から読み込まれます。よく使う値は `.env.example` にまとまっています。

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | なし | コード生成に使う OpenAI API キー。 |
| `NGROK_AUTHTOKEN` | なし | 公開ログ URL を作成するための ngrok トークン。 |
| `AIVENV_API_HOST` | `127.0.0.1` | API のバインド先ホスト。 |
| `AIVENV_API_PORT` | `8080` | API のバインド先ポート。 |
| `AIVENV_LOG_HOST` | `127.0.0.1` | ログビューアーのバインド先ホスト。 |
| `AIVENV_LOG_PORT` | `8081` | ログビューアーのバインド先ポート。 |
| `AIVENV_OPENAI_MODEL` | `gpt-4o` | コード生成に使う OpenAI モデル。 |
| `AIVENV_CONTAINER_IMAGE` | `python:3.11-slim` | 生成スクリプトを実行する Docker イメージ。 |
| `AIVENV_CONTAINER_CPU_LIMIT` | `1` | コンテナの CPU 制限。 |
| `AIVENV_CONTAINER_MEMORY_LIMIT` | `512m` | コンテナのメモリ制限。 |
| `AIVENV_OUTPUT_DIR` | `.aivenv/output` | 実行結果の出力先ディレクトリ。 |

## 開発

```powershell
pytest
ruff check src tests
ruff format src tests
mypy
```

## セキュリティ上の注意

生成されたコードは必ず Docker コンテナ内だけで実行してください。ホストマシン上で直接実行しないでください。API キーやトークンなどのシークレットは環境変数またはローカルの `.env` に置き、ログへ出力しないようにしてください。

## 現在の状態

このリポジトリは開発初期段階に見えます。一部の実装ファイルには未完成と思われる箇所があるため、実際の用途で使う前にテストを実行して状態を確認してください。
