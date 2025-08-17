import os
import uuid
import subprocess
from pathlib import Path
from typing import Optional
import shutil

from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
PLOTS_DIR = STATIC_DIR / "plots"


def ensure_dirs():
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)


def allowed_ext(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in {".fa", ".fasta", ".fna", ".ffn", ".faa", ".frn", ".txt"}


def run_flexidot(inp1: Path, inp2: Path, outdir: Path, prefix: str, k: int, seq_type: str):
    exe = shutil.which("flexidot") or "flexidot"
    cmd = [
        exe,
        "-i",
        str(inp1),
        str(inp2),
        "-m",
        "1",  # paired mode
        "-f",
        "png",
        "--outdir",
        str(outdir),
        "-o",
        prefix,
        "-t",
        seq_type,
        "-k",
        str(k),
    ]
    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("LC_ALL", env.get("LC_ALL", "C"))
    env.setdefault("LANG", env.get("LANG", "C"))
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def find_png(outdir: Path) -> Optional[Path]:
    pngs = sorted(outdir.glob("*.png"))
    return pngs[0] if pngs else None


class PrefixMiddleware:
    def __init__(self, app, prefix: str):
        self.app = app
        self.prefix = prefix.rstrip("/") or ""

    def __call__(self, environ, start_response):
        script_name = environ.get("SCRIPT_NAME", "")
        path_info = environ.get("PATH_INFO", "")
        # If already mounted (e.g., mod_wsgi sets SCRIPT_NAME), just pass through
        if script_name.startswith(self.prefix) or script_name == self.prefix:
            return self.app(environ, start_response)
        # Dev-mode mount at subpath
        if path_info.startswith(self.prefix + "/") or path_info == self.prefix:
            environ["SCRIPT_NAME"] = self.prefix
            environ["PATH_INFO"] = path_info[len(self.prefix):] or "/"
            return self.app(environ, start_response)
        # Not under prefix: 404 to indicate mount path
        start_response('404 NOT FOUND', [('Content-Type', 'text/plain; charset=utf-8')])
        return [f"This app is mounted at {self.prefix}/".encode('utf-8')]


def create_app():
    ensure_dirs()
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "flexidot-secret-key")

    def rewrite_fasta_unique(src: Path, dst: Path, label: str):
        """Rewrite FASTA so each record ID is unique by prefixing with a label.
        Tries Biopython; falls back to a simple header rewrite.
        """
        try:
            from Bio import SeqIO  # type: ignore
            records = []
            for rec in SeqIO.parse(str(src), "fasta"):
                orig_id = rec.id
                new_id = f"{label}|{orig_id}"
                rec.id = new_id
                rec.name = new_id
                # preserve original text in description for clarity
                rec.description = f"{new_id}"
                records.append(rec)
            if not records:
                raise ValueError("No FASTA records found in " + str(src))
            SeqIO.write(records, str(dst), "fasta")
        except Exception:
            # Fallback: simple header line rewrite
            wrote_any = False
            with src.open("r", encoding="utf-8", errors="replace") as fin, dst.open("w", encoding="utf-8") as fout:
                for line in fin:
                    if line.startswith(">"):
                        h = line[1:].strip().split()[0]
                        new_h = f"{label}|{h}"
                        fout.write(">" + new_h + "\n")
                        wrote_any = True
                    else:
                        fout.write(line)
            if not wrote_any:
                raise ValueError("FASTA header not found in " + str(src))

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "POST":
            file1 = request.files.get("fasta1")
            file2 = request.files.get("fasta2")
            seq_type = request.form.get("seq_type", "nuc")
            try:
                k = int(request.form.get("k", 10))
            except Exception:
                k = 10

            if not file1 or not file1.filename:
                flash("1つ目のFASTAファイルを選択してください。", "error")
                return redirect(url_for("index"))
            if not file2 or not file2.filename:
                flash("2つ目のFASTAファイルを選択してください。", "error")
                return redirect(url_for("index"))

            if not allowed_ext(file1.filename) or not allowed_ext(file2.filename):
                flash("許可されていない拡張子です（.fasta, .fa など）。", "error")
                return redirect(url_for("index"))

            session_id = uuid.uuid4().hex
            work_dir = PLOTS_DIR / session_id
            work_dir.mkdir(parents=True, exist_ok=True)

            # Save inputs into the working directory
            in1 = work_dir / secure_filename(Path(file1.filename).name)
            in2 = work_dir / secure_filename(Path(file2.filename).name)
            file1.save(in1)
            file2.save(in2)

            # Ensure unique IDs per file to avoid FlexiDot duplicate key errors
            in1u = work_dir / (in1.stem + ".uniq.fasta")
            in2u = work_dir / (in2.stem + ".uniq.fasta")
            try:
                rewrite_fasta_unique(in1, in1u, label="file1")
                rewrite_fasta_unique(in2, in2u, label="file2")
                in_use_1, in_use_2 = in1u, in2u
            except Exception:
                # If rewrite fails for any reason, fall back to originals
                in_use_1, in_use_2 = in1, in2

            # Run flexidot, output directly into the work directory (served under static/plots)
            rc, out, err = run_flexidot(in_use_1, in_use_2, work_dir, prefix="plot", k=k, seq_type=seq_type)

            # Log captured output to server logs as well
            try:
                app.logger.info("flexidot stdout:\n%s", out)
                app.logger.error("flexidot stderr:\n%s", err)
            except Exception:
                pass

            png_path = find_png(work_dir)

            if rc != 0 or png_path is None:
                # Prepare detailed diagnostics
                listing = "\n".join(sorted(p.name for p in work_dir.glob("*")))
                log_msg = (
                    f"Command exit code: {rc}\n\n"
                    f"[stdout]\n{out or ''}\n\n[stderr]\n{err or ''}\n\n"
                    f"[work_dir]\n{work_dir}\n\n[files]\n{listing or '(no files)'}\n"
                )
                flash("プロット生成に失敗しました。ログを確認してください。", "error")
                return render_template(
                    "index.html",
                    result=None,
                    error_log=log_msg,
                    default_k=k,
                    default_seq_type=seq_type,
                )

            # Build URL to serve static image
            img_rel = f"plots/{session_id}/{png_path.name}"
            img_url = url_for("static", filename=img_rel)
            return render_template(
                "index.html",
                result={
                    "img_url": img_url,
                    "download_name": png_path.name,
                    "session_id": session_id,
                },
                error_log=None,
                default_k=k,
                default_seq_type=seq_type,
            )

        # GET request
        return render_template("index.html", result=None, error_log=None, default_k=10, default_seq_type="nuc")

    # Optional: run under a subpath in dev (Apache/mod_wsgi should set SCRIPT_NAME instead)
    url_prefix = os.environ.get("FLEXIDOT_URL_PREFIX", "").strip()
    if url_prefix:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, url_prefix)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
