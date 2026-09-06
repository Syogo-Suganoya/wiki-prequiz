"""1分間予習クイズ アーキテクチャ図の生成スクリプト。

技術スタックが一目で分かることを目的にした簡潔な図に留める。
権限境界やフェーズ遷移の詳細は DESIGN.md の本文と表で説明する。

使い方:
    brew install graphviz && pip install diagrams
    python docs/architecture.py

生成物:
    docs/architecture_production.png   本番構成
    docs/architecture_local.png        ローカル開発環境 (Docker Compose)
"""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.firebase.develop import Firestore
from diagrams.gcp.compute import Run
from diagrams.gcp.ml import AIPlatform
from diagrams.onprem.client import Users
from diagrams.onprem.container import Docker
from diagrams.onprem.network import Internet
from diagrams.programming.framework import FastAPI, React

OUT_DIR = Path(__file__).resolve().parent

# 日本語ラベルを描画するためフォントを明示する（macOS 標準のヒラギノ）。
# Linux/CI では "Noto Sans CJK JP" 等に読み替える。
FONT = "Hiragino Sans"

GRAPH_ATTR = {
    "fontname": FONT,
    "fontsize": "13",
    "bgcolor": "white",
    "pad": "0.5",
    "splines": "spline",
    "nodesep": "0.5",
    "ranksep": "1.3",
}
NODE_ATTR = {"fontname": FONT, "fontsize": "11"}
EDGE_ATTR = {"fontname": FONT, "fontsize": "10", "color": "#6B6B78"}
CLUSTER_ATTR = {"fontname": FONT, "bgcolor": "white", "pencolor": "#B8B8C0"}


def production() -> None:
    with Diagram(
        "本番構成",
        filename=str(OUT_DIR / "architecture_production"),
        outformat="png",
        show=False,
        direction="LR",
        graph_attr=GRAPH_ATTR,
        node_attr=NODE_ATTR,
        edge_attr=EDGE_ATTR,
    ):
        # クラスタは縦積みを強制して図を読みにくくするため使わない。
        # 実行基盤はノードのラベル側（Vercel / Cloud Run）で示す。
        players = Users("プレイヤー")
        spa = React("React + Vite\nVercel")
        api = Run("FastAPI + Python\nCloud Run")
        db = Firestore("Firestore")
        gemini = AIPlatform("Gemini 3.8 Flash")
        wiki = Internet("Wikipedia REST")

        players >> spa
        spa >> Edge(label="操作 (REST)") >> api
        api >> Edge(label="書き込み") >> db
        db >> Edge(label="購読（読み取りのみ）", style="dashed") >> spa
        api >> Edge(label="作問・判定") >> gemini
        api >> Edge(label="本文・PV") >> wiki


def local_dev() -> None:
    with Diagram(
        "ローカル開発環境 (Docker Compose)",
        filename=str(OUT_DIR / "architecture_local"),
        outformat="png",
        show=False,
        direction="LR",
        graph_attr=GRAPH_ATTR,
        node_attr=NODE_ATTR,
        edge_attr=EDGE_ATTR,
    ):
        dev = Users("開発者")

        with Cluster("docker compose", graph_attr=CLUSTER_ATTR):
            web = React("web\nVite :5173")
            api = FastAPI("api\nuvicorn :8000")
            emu = Docker("emulator\nFirestore :8080\nAuth :9099")

        gemini = AIPlatform("Gemini")
        wiki = Internet("Wikimedia")

        dev >> web
        web >> Edge(label="/api/*") >> api
        web >> Edge(style="dashed") >> emu
        api >> Edge(label="EMULATOR_HOST") >> emu
        api >> Edge(label="実 API") >> gemini
        api >> wiki


if __name__ == "__main__":
    production()
    local_dev()
    print(f"生成しました: {OUT_DIR}")
