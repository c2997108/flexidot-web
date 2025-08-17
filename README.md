# FlexiDot Web (Two-FASTA Dotplot)

FlexiDot を使って 2 つの FASTA ファイルからドットプロット画像 (PNG) を生成するシンプルな Web アプリです。Flask 製で、Apache (mod_wsgi) のサブディレクトリ `/flexidot` 配下で公開する想定になっています。

- 入力: 2 つの FASTA
- オプション: 配列タイプ (`nuc`/`aa`)、k-mer 長 (`-k`)
- 出力: PNG 画像 (`static/plots/<UUID>/plot-*.png`)
- 互換: FASTA で同名の ID が衝突する場合は自動で `file1|` / `file2|` を付けて一意化


## 画面イメージ
- トップページで FASTA を 2 つアップロード → 実行
- 生成後に PNG をブラウザに表示、ダウンロード可能


## 構成ファイル
- `app.py`: Flask アプリ本体
- `templates/index.html`: 画面テンプレート
- `wsgi.py`: Apache/mod_wsgi 用エントリポイント
- `requirements.txt`: Python 依存関係 (Flask, flexidot など)


## サーバー要件 (Rocky Linux 9)
- Rocky Linux 9 (x86_64)
- Apache (httpd) + mod_wsgi
- Python 3.9 (システム標準) + venv + pip
- Git (取得用)

注: Matplotlib などは manylinux ホイールが提供されており、追加のビルドツールなしで導入できます。企業ネットワーク等で外部リポジトリへのアクセス制限がある場合は、ホイール取得のためのプロキシ設定が必要です。


## セットアップ手順 (Apache + mod_wsgi, サブディレクトリ `/flexidot`)
以下は root 権限での作業を想定しています。

1) 必要パッケージのインストール

```bash
# 基本ツール
sudo dnf -y install httpd mod_wsgi python3 python3-pip git

# 起動と常時起動
sudo systemctl enable --now httpd

# ファイアウォール (80/443)
sudo firewall-cmd --add-service=http --permanent
sudo firewall-cmd --add-service=https --permanent
sudo firewall-cmd --reload
```

2) アプリ配置と仮想環境

```bash
# 配置先 (例): /opt/flexidot
sudo mkdir -p /opt/flexidot
sudo chown $USER:$USER /opt/flexidot
cd /opt/flexidot

# 取得
git clone https://github.com/c2997108/flexidot-web.git .
# (このリポジトリをそのままコピーしてもOK)

# Python 仮想環境
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

3) 出力ディレクトリの作成と権限

```bash
# 生成画像の保存先
mkdir -p static/plots

# Apache から書き込み可能にする (所有権を apache に変更)
sudo chown -R apache:apache static/plots

# SELinux 有効時は書き込みコンテキストを付与
sudo semanage fcontext -a -t httpd_sys_rw_content_t '/opt/flexidot/static/plots(/.*)?'
sudo restorecon -RFv /opt/flexidot/static
```

4) Apache 設定 (mod_wsgi で `/flexidot` にマウント)

`/etc/httpd/conf.d/flexidot.conf` を作成:

```apache
# アプリ本体を /flexidot にマウント
WSGIScriptAlias /flexidot /opt/flexidot/wsgi.py \
    process-group=flexidot application-group=%{GLOBAL}

# WSGI デーモンプロセス (システム Python 3.9 + 仮想環境)
WSGIDaemonProcess flexidot \
    python-home=/opt/flexidot/venv \
    python-path=/opt/flexidot \
    processes=2 threads=15 \
    display-name=%{GROUP}
WSGIProcessGroup flexidot

# 静的ファイルは Apache で直接配信
Alias /flexidot/static /opt/flexidot/static
<Directory /opt/flexidot/static>
    Require all granted
</Directory>

# WSGI エントリの実行許可
<Directory /opt/flexidot>
    <Files wsgi.py>
        Require all granted
    </Files>
</Directory>
```

設定反映:

```bash
sudo apachectl configtest
sudo systemctl restart httpd
```

5) 動作確認

- ブラウザで `http://<サーバー名またはIP>/flexidot/` にアクセス
- 2つの FASTA を選択して「ドットプロットを作成」
- プロット画像が表示・ダウンロードできればOK


## 自動起動について
本アプリは Apache (httpd) の mod_wsgi として動作するため、サーバー起動時に `httpd` を自動起動にしておけば、アプリも自動で起動・公開されます。

```bash
sudo systemctl enable httpd
```

アプリのコードを更新した場合は Apache を再起動するか、`wsgi.py` のタイムスタンプを更新してください。

```bash
# 再起動
sudo systemctl restart httpd
# もしくは、wsgi.py を touch して再読み込み
sudo touch /opt/flexidot/wsgi.py
```


## トラブルシューティング
- 403 Forbidden が出る
  - SELinux/権限が原因のことが多いです。`static/plots` に `apache` が書き込み可能か確認。
  - `restorecon` 実行後も問題があれば、一時的に SELinux を Permissive にして切り分け (`setenforce 0`)。
- 500 Internal Server Error
  - `/var/log/httpd/error_log` を確認。Python トレースや import エラーが出ていないかを確認。
  - venv が異なる場合、`python-home`/`python-path` の指定を再確認。
- 画像が生成されない/失敗メッセージ
  - 入力 FASTA の ID 重複が原因の場合があります。本アプリは自動で `file1|`/`file2|` を付与しますが、壊れた FASTA では失敗します。
  - k-mer が大きすぎる/タイプ不一致 (`aa` と `nuc`) の場合も調整してください。
- 大容量入力で時間がかかる
  - 処理時間に応じて Apache の `Timeout` を延長、あるいは `processes`/`threads` を調整。


## 開発モード (任意)
ローカルでサブパス `/flexidot` を再現したい場合:

```bash
# 1回目のみ
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# サブパスで起動
FLEXIDOT_URL_PREFIX=/flexidot python3 app.py

# http://127.0.0.1:5000/flexidot/ へアクセス
```


## ライセンス / 謝辞
- Dotplot 生成は FlexiDot を使用しています。論文の引用先は FlexiDot の出力ログに表示されます。
- 本リポジトリのコードはプロジェクト利用者の環境に合わせて自由に改変してください。
