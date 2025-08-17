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


## 推奨セットアップ (Gunicorn + Apache リバースプロキシ, サブディレクトリ `/flexidot`)
FlexiDot 2.x は Python 3.12 以降の構文 (PEP 701 による f-string 拡張) を含むため、Rocky Linux 9 の標準 Python 3.9 + mod_wsgi では実行に失敗します。
そのため、アプリは Python 3.12 の仮想環境上で Gunicorn を用いて起動し、Apache はリバースプロキシとして動作させる方法を推奨します。

以下は root 権限での作業を想定しています。

1) 必要パッケージのインストール

```bash
# 基本ツール（Python はユーザー領域に導入するため dnf では入れません）
sudo dnf -y install epel-release
sudo dnf -y install httpd git mod_proxy mod_proxy_http policycoreutils-python-utils

# 起動と常時起動
sudo systemctl enable --now httpd

# ファイアウォール (80/443)
sudo firewall-cmd --add-service=http --permanent
sudo firewall-cmd --add-service=https --permanent
sudo firewall-cmd --reload
```

2) アプリ配置と Python 3.12（非管理者権限; micromamba 使用）

```bash
# 配置先 (例): /opt/flexidot
sudo mkdir -p /opt/flexidot
sudo chown $USER:$USER /opt/flexidot
cd /opt/flexidot

# 取得
git clone https://github.com/c2997108/flexidot-web.git .
# (このリポジトリをそのままコピーしてもOK)

# Python 3.12 をユーザー領域に導入（micromamba）
# 1) micromamba 本体の配置（ユーザー権限のみ）
mkdir -p "$HOME/bin" "$HOME/micromamba" "$HOME/mamba"
curl -L https://micro.mamba.pm/api/micromamba/linux-64/latest -o "$HOME/micromamba/micromamba.tar.bz2"
tar -xjf "$HOME/micromamba/micromamba.tar.bz2" -C "$HOME/micromamba" --strip-components=1 bin/micromamba
ln -sf "$HOME/micromamba/bin/micromamba" "$HOME/bin/micromamba"
export PATH="$HOME/bin:$PATH"

# 2) 環境を作成（python=3.12）
export MAMBA_ROOT_PREFIX="$HOME/mamba"
micromamba create -y -n flexidot python=3.12 pip
eval "$(micromamba shell hook -s bash)" && micromamba activate flexidot

# 3) 依存関係をインストール
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

4) Gunicorn の systemd サービス設定（自動起動）

`/etc/systemd/system/flexidot.service` を作成:

```ini
[Unit]
Description=FlexiDot Web (Gunicorn)
After=network.target

[Service]
Type=simple
User=flexidot
Group=apache
WorkingDirectory=/opt/flexidot
Environment=FLEXIDOT_URL_PREFIX=/flexidot
Environment=MPLBACKEND=Agg
Environment=MAMBA_ROOT_PREFIX=/home/flexidot/mamba
ExecStart=/home/flexidot/micromamba/bin/micromamba run -n flexidot gunicorn -w 2 -b 127.0.0.1:8000 wsgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

サービスユーザーの作成と権限設定:

```bash
sudo useradd -r -s /sbin/nologin -d /opt/flexidot flexidot || true
sudo chown -R flexidot:apache /opt/flexidot
sudo chmod 750 /opt/flexidot
sudo chown -R flexidot:apache /opt/flexidot/static/plots

# （推奨）Python 環境も flexidot ユーザーで作成:
sudo -u flexidot -H bash -lc '
  mkdir -p "$HOME/bin" "$HOME/micromamba" "$HOME/mamba" && \
  curl -L https://micro.mamba.pm/api/micromamba/linux-64/latest -o "$HOME/micromamba/micromamba.tar.bz2" && \
  tar -xjf "$HOME/micromamba/micromamba.tar.bz2" -C "$HOME/micromamba" --strip-components=1 bin/micromamba && \
  ln -sf "$HOME/micromamba/bin/micromamba" "$HOME/bin/micromamba" && \
  export PATH="$HOME/bin:$PATH" && \
  export MAMBA_ROOT_PREFIX="$HOME/mamba" && \
  "$HOME/bin/micromamba" create -y -n flexidot python=3.12 pip && \
  eval "$("$HOME/bin/micromamba" shell hook -s bash)" && micromamba activate flexidot && \
  pip install --upgrade pip && \
  cd /opt/flexidot && pip install -r requirements.txt 
'

sudo systemctl daemon-reload
sudo systemctl enable --now flexidot.service
```

5) Apache 設定 (リバースプロキシで `/flexidot` に公開)

`/etc/httpd/conf.d/flexidot.conf` を作成:

```apache
# 静的ファイルは Apache が直接配信
Alias /flexidot/static /opt/flexidot/static
<Directory /opt/flexidot/static>
    Require all granted
</Directory>

# アプリ本体は Gunicorn へプロキシ (上流はルートで待受け、Prefix はヘッダで伝達)
ProxyPreserveHost On
RequestHeader set X-Forwarded-Prefix "/flexidot"
ProxyPass /flexidot http://127.0.0.1:8000/ retry=0
ProxyPassReverse /flexidot http://127.0.0.1:8000/
```

SELinux (Apache からローカルポートへのプロキシ許可):

```bash
sudo setsebool -P httpd_can_network_connect 1
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
本アプリは `flexidot.service` (Gunicorn) を systemd で管理し、Apache は単なるリバースプロキシとして動作します。サーバー起動時に両方が自動起動するよう、`httpd` と `flexidot` を enable 済みにしてください。

```bash
sudo systemctl enable httpd flexidot
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
