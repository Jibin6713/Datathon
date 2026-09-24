"""Open an English-only dashboard for the baseline and XGBoost results.

Run from the repository root:

    python ml/xgboost_survival_pipeline/05_visualize_results.py

The script reads existing pipeline artifacts and opens a native dashboard window.
It does not retrain a model, modify artifacts, or create output files.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPARISON = REPOSITORY_ROOT / "ml" / "artifacts" / "model_comparison"
DEFAULT_XGBOOST = REPOSITORY_ROOT / "ml" / "artifacts" / "xgboost_survival"

BASELINE_COLOR = "#64748B"
XGBOOST_COLOR = "#2563EB"
DRIVER_COLOR = "#0F766E"
GRID_COLOR = "#D7DEE8"
TEXT_COLOR = "#172033"
MUTED_COLOR = "#5D6A7E"


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(value: object) -> float:
    return float(value) if value not in (None, "") else 0.0


def format_percent(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def load_priority_summary(path: Path) -> dict:
    band_counts: Counter[str] = Counter()
    risk_bins = Counter(
        {
            "<0.1%": 0,
            "0.1%-1%": 0,
            "1%-5%": 0,
            "5%-10%": 0,
            "10%-25%": 0,
            ">=25%": 0,
        }
    )
    top_pipes: list[dict[str, str]] = []
    row_count = 0

    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            probability = as_float(row["risk_probability_12m"])
            band_counts[row["priority_band"]] += 1
            if probability < 0.001:
                risk_bins["<0.1%"] += 1
            elif probability < 0.01:
                risk_bins["0.1%-1%"] += 1
            elif probability < 0.05:
                risk_bins["1%-5%"] += 1
            elif probability < 0.10:
                risk_bins["5%-10%"] += 1
            elif probability < 0.25:
                risk_bins["10%-25%"] += 1
            else:
                risk_bins[">=25%"] += 1

            if int(float(row["priority_rank"])) <= 10:
                top_pipes.append(row)

    top_pipes.sort(key=lambda row: int(float(row["priority_rank"])))
    return {
        "row_count": row_count,
        "band_counts": band_counts,
        "risk_bins": risk_bins,
        "top_pipes": top_pipes,
    }


def load_dashboard_data(comparison_dir: Path, xgboost_dir: Path) -> dict:
    paths = {
        "comparison": comparison_dir / "comparison_summary.json",
        "metrics": xgboost_dir / "metrics.json",
        "drivers": xgboost_dir / "current_global_driver_importance.csv",
        "priority": xgboost_dir / "pipe_repair_priority.csv",
    }
    for name, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"Required {name} artifact is missing: {path}")

    drivers = read_csv(paths["drivers"])
    drivers.sort(
        key=lambda row: as_float(row["mean_absolute_risk_contribution"]),
        reverse=True,
    )
    return {
        "summary": read_json(paths["comparison"]),
        "metrics": read_json(paths["metrics"]),
        "drivers": drivers,
        "priority": load_priority_summary(paths["priority"]),
    }


def draw_grouped_bars(
    canvas,
    categories: list[str],
    baseline_values: list[float],
    xgboost_values: list[float],
    *,
    percent: bool = True,
) -> None:
    canvas.delete("all")
    width = int(canvas.cget("width"))
    height = int(canvas.cget("height"))
    left, right, top, bottom = 62, 18, 30, 54
    plot_w = width - left - right
    plot_h = height - top - bottom
    maximum = max(baseline_values + xgboost_values + [0.01])
    ceiling = min(1.0, maximum * 1.18) if percent else maximum * 1.18

    for tick in range(6):
        value = ceiling * tick / 5
        y = top + plot_h - plot_h * tick / 5
        label = format_percent(value, 0) if percent else f"{value:.0f}"
        canvas.create_line(left, y, left + plot_w, y, fill=GRID_COLOR)
        canvas.create_text(left - 8, y, text=label, anchor="e", fill=MUTED_COLOR)

    group_w = plot_w / max(len(categories), 1)
    bar_w = min(40, group_w * 0.28)
    for index, (category, baseline, xgboost) in enumerate(
        zip(categories, baseline_values, xgboost_values)
    ):
        center = left + group_w * (index + 0.5)
        for value, x, color in (
            (baseline, center - bar_w - 3, BASELINE_COLOR),
            (xgboost, center + 3, XGBOOST_COLOR),
        ):
            bar_h = plot_h * value / ceiling if ceiling else 0
            y = top + plot_h - bar_h
            canvas.create_rectangle(
                x, y, x + bar_w, top + plot_h, fill=color, outline=""
            )
            shown = format_percent(value, 1) if percent else f"{value:.0f}"
            canvas.create_text(x + bar_w / 2, max(top + 8, y - 9), text=shown)
        canvas.create_text(center, top + plot_h + 23, text=category)

    legend_y = 11
    canvas.create_rectangle(
        width - 230,
        legend_y - 6,
        width - 218,
        legend_y + 6,
        fill=BASELINE_COLOR,
        outline="",
    )
    canvas.create_text(
        width - 212, legend_y, text="Logistic baseline", anchor="w"
    )
    canvas.create_rectangle(
        width - 105,
        legend_y - 6,
        width - 93,
        legend_y + 6,
        fill=XGBOOST_COLOR,
        outline="",
    )
    canvas.create_text(width - 87, legend_y, text="XGBoost", anchor="w")


def draw_horizontal_bars(canvas, labels: list[str], values: list[float]) -> None:
    canvas.delete("all")
    width = int(canvas.cget("width"))
    height = int(canvas.cget("height"))
    left, right, top, bottom = 185, 70, 16, 16
    plot_w = width - left - right
    row_h = (height - top - bottom) / max(len(labels), 1)
    maximum = max(values + [1e-9])

    for index, (label, value) in enumerate(zip(labels, values)):
        y = top + index * row_h
        center_y = y + row_h / 2
        bar_w = plot_w * value / maximum
        canvas.create_text(
            left - 10, center_y, text=label, anchor="e", fill=TEXT_COLOR
        )
        canvas.create_rectangle(
            left,
            center_y - 9,
            left + plot_w,
            center_y + 9,
            fill="#EEF2F6",
            outline="",
        )
        canvas.create_rectangle(
            left,
            center_y - 9,
            left + bar_w,
            center_y + 9,
            fill=DRIVER_COLOR,
            outline="",
        )
        canvas.create_text(
            min(width - 2, left + bar_w + 8),
            center_y,
            text=f"{value:.4f}",
            anchor="w",
        )


def draw_single_bars(canvas, labels: list[str], values: list[int]) -> None:
    canvas.delete("all")
    width = int(canvas.cget("width"))
    height = int(canvas.cget("height"))
    left, right, top, bottom = 58, 16, 25, 54
    plot_w = width - left - right
    plot_h = height - top - bottom
    maximum = max(values + [1])
    group_w = plot_w / max(len(labels), 1)
    bar_w = min(58, group_w * 0.58)

    canvas.create_line(
        left, top + plot_h, left + plot_w, top + plot_h, fill=GRID_COLOR
    )
    for index, (label, value) in enumerate(zip(labels, values)):
        center = left + group_w * (index + 0.5)
        bar_h = plot_h * value / maximum
        y = top + plot_h - bar_h
        canvas.create_rectangle(
            center - bar_w / 2,
            y,
            center + bar_w / 2,
            top + plot_h,
            fill=XGBOOST_COLOR,
            outline="",
        )
        canvas.create_text(center, max(top + 8, y - 9), text=f"{value:,}")
        canvas.create_text(center, top + plot_h + 23, text=label)


def add_kpi(parent, column: int, label: str, value: str) -> None:
    from tkinter import ttk

    frame = ttk.Frame(parent, padding=(14, 10))
    frame.grid(row=0, column=column, sticky="nsew", padx=6, pady=6)
    ttk.Label(frame, text=label, style="Muted.TLabel").pack(anchor="w")
    ttk.Label(frame, text=value, style="KPI.TLabel").pack(
        anchor="w", pady=(2, 0)
    )
    frame.configure(relief="solid", borderwidth=1)


def add_tree(parent, columns: list[tuple[str, str, int]], rows: list[list[object]]):
    from tkinter import ttk

    names = [item[0] for item in columns]
    tree = ttk.Treeview(
        parent,
        columns=names,
        show="headings",
        height=max(3, min(10, len(rows))),
    )
    for name, label, width in columns:
        tree.heading(name, text=label)
        tree.column(name, width=width, anchor="center", stretch=True)
    for row in rows:
        tree.insert("", "end", values=row)
    tree.pack(fill="both", expand=True)
    return tree


def create_overview_tab(notebook, data: dict) -> None:
    from tkinter import ttk

    summary = data["summary"]
    test = data["metrics"]["test"]
    horizon = test["horizons"]["12m"]
    priority = data["priority"]

    tab = ttk.Frame(notebook, padding=18)
    notebook.add(tab, text="Overview")
    for column in range(4):
        tab.columnconfigure(column, weight=1)

    add_kpi(tab, 0, "Test C-index", f"{test['harrell_c_index']:.3f}")
    add_kpi(tab, 1, "12m PR-AUC", f"{horizon['pr_auc']:.3f}")
    add_kpi(tab, 2, "12m Brier Score", f"{horizon['brier_score']:.4f}")
    add_kpi(tab, 3, "Prioritised pipes", f"{priority['row_count']:,}")

    message = (
        f"Fair comparison scope: {summary['sample_count']:,} identical 2024-2025 "
        f"test rows, with {summary['positive_count']:,} breaks in the next 12 months "
        f"({format_percent(summary['positive_rate'], 3)} event rate)."
    )
    ttk.Label(tab, text=message, wraplength=1120, justify="left").grid(
        row=1,
        column=0,
        columnspan=4,
        sticky="w",
        padx=6,
        pady=(16, 8),
    )

    base = summary["baseline"]
    xgb = summary["xgboost_aft"]
    metrics = [
        ("PR-AUC", base["pr_auc"], xgb["pr_auc"], "Higher is better"),
        ("ROC-AUC", base["roc_auc"], xgb["roc_auc"], "Higher is better"),
        (
            "Brier Score",
            base["brier_score"],
            xgb["brier_score"],
            "Lower is better",
        ),
        ("Log Loss", base["log_loss"], xgb["log_loss"], "Lower is better"),
        (
            "Mean predicted probability",
            base["mean_predicted_probability"],
            xgb["mean_predicted_probability"],
            f"Actual rate: {format_percent(summary['positive_rate'], 3)}",
        ),
    ]
    metric_frame = ttk.LabelFrame(tab, text="Model metric comparison", padding=10)
    metric_frame.grid(
        row=2, column=0, columnspan=4, sticky="nsew", padx=6, pady=10
    )
    add_tree(
        metric_frame,
        [
            ("metric", "Metric", 235),
            ("baseline", "Logistic baseline", 170),
            ("xgboost", "XGBoost AFT", 170),
            ("meaning", "Interpretation", 260),
        ],
        [
            [name, f"{baseline:.6f}", f"{boosted:.6f}", meaning]
            for name, baseline, boosted, meaning in metrics
        ],
    )

    top_five = summary["inspection_budgets"]["top_5pct"]
    conclusion = (
        "Decision result: at the same Top 5% inspection budget, XGBoost found "
        f"{top_five['xgboost']['hits']} actual breaks versus "
        f"{top_five['baseline']['hits']} for the baseline. This is "
        f"{top_five['xgboost_minus_baseline_hits']} additional breaks, with "
        f"{format_percent(top_five['xgboost']['recall'])} recall."
    )
    ttk.Label(
        tab,
        text=conclusion,
        style="Conclusion.TLabel",
        wraplength=1120,
        justify="left",
    ).grid(row=3, column=0, columnspan=4, sticky="ew", padx=6, pady=10)

    limitation = (
        f"Limit: event-only median-time MAE is "
        f"{test['event_only_median_time_mae_months']:.1f} months. Use predicted "
        "median months as relative urgency, not as an exact failure date. "
        "The 36-month test window is incomplete."
    )
    ttk.Label(
        tab,
        text=limitation,
        style="Warning.TLabel",
        wraplength=1120,
        justify="left",
    ).grid(row=4, column=0, columnspan=4, sticky="ew", padx=6, pady=(4, 0))


def create_comparison_tab(notebook, data: dict) -> None:
    import tkinter as tk
    from tkinter import ttk

    summary = data["summary"]
    tab = ttk.Frame(notebook, padding=14)
    notebook.add(tab, text="Model comparison")
    tab.columnconfigure(0, weight=1)
    tab.columnconfigure(1, weight=1)

    left = ttk.LabelFrame(tab, text="Test-set discrimination", padding=8)
    right = ttk.LabelFrame(
        tab, text="Recall at fixed inspection budgets", padding=8
    )
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 12))
    right.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=(0, 12))

    metric_canvas = tk.Canvas(
        left, width=560, height=320, bg="white", highlightthickness=0
    )
    metric_canvas.pack(fill="both", expand=True)
    draw_grouped_bars(
        metric_canvas,
        ["PR-AUC", "ROC-AUC"],
        [summary["baseline"]["pr_auc"], summary["baseline"]["roc_auc"]],
        [summary["xgboost_aft"]["pr_auc"], summary["xgboost_aft"]["roc_auc"]],
    )

    budget_items = [
        summary["inspection_budgets"][key]
        for key in ("top_1pct", "top_2pct", "top_5pct")
    ]
    recall_canvas = tk.Canvas(
        right, width=560, height=320, bg="white", highlightthickness=0
    )
    recall_canvas.pack(fill="both", expand=True)
    draw_grouped_bars(
        recall_canvas,
        ["Top 1%", "Top 2%", "Top 5%"],
        [item["baseline"]["recall"] for item in budget_items],
        [item["xgboost"]["recall"] for item in budget_items],
    )

    table_frame = ttk.LabelFrame(tab, text="Operational impact", padding=8)
    table_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
    budget_rows = []
    for item in budget_items:
        budget_rows.append(
            [
                f"Top {item['fraction'] * 100:g}%",
                f"{item['xgboost']['inspected']:,}",
                item["baseline"]["hits"],
                item["xgboost"]["hits"],
                format_percent(item["baseline"]["precision"]),
                format_percent(item["xgboost"]["precision"]),
                format_percent(item["baseline"]["recall"]),
                format_percent(item["xgboost"]["recall"]),
                f"+{item['xgboost_minus_baseline_hits']}",
            ]
        )
    add_tree(
        table_frame,
        [
            ("budget", "Budget", 90),
            ("inspected", "Inspected", 100),
            ("base_hits", "Baseline hits", 105),
            ("xgb_hits", "XGBoost hits", 105),
            ("base_precision", "Baseline precision", 125),
            ("xgb_precision", "XGBoost precision", 125),
            ("base_recall", "Baseline recall", 115),
            ("xgb_recall", "XGBoost recall", 115),
            ("extra", "Extra hits", 85),
        ],
        budget_rows,
    )


def create_drivers_tab(notebook, data: dict) -> None:
    import tkinter as tk
    from tkinter import ttk

    tab = ttk.Frame(notebook, padding=14)
    notebook.add(tab, text="Risk drivers")
    ttk.Label(
        tab,
        text=(
            "Mean absolute risk contribution across the current scoring population. "
            "The values describe model dependence and are not causal effects."
        ),
        style="Muted.TLabel",
        wraplength=1120,
        justify="left",
    ).pack(anchor="w", pady=(0, 10))

    canvas = tk.Canvas(
        tab,
        width=1120,
        height=520,
        bg="white",
        highlightthickness=1,
        highlightbackground=GRID_COLOR,
    )
    canvas.pack(fill="both", expand=True)
    draw_horizontal_bars(
        canvas,
        [row["feature"] for row in data["drivers"]],
        [
            as_float(row["mean_absolute_risk_contribution"])
            for row in data["drivers"]
        ],
    )


def create_priority_tab(notebook, data: dict) -> None:
    import tkinter as tk
    from tkinter import ttk

    priority = data["priority"]
    tab = ttk.Frame(notebook, padding=14)
    notebook.add(tab, text="Current priorities")
    tab.columnconfigure(0, weight=1)
    tab.columnconfigure(1, weight=1)

    band_frame = ttk.LabelFrame(tab, text="Priority bands", padding=10)
    risk_frame = ttk.LabelFrame(tab, text="12-month risk distribution", padding=10)
    band_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 12))
    risk_frame.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=(0, 12))

    order = ["IMMEDIATE", "HIGH", "PLANNED", "MONITOR"]
    colors = {
        "IMMEDIATE": "#B42318",
        "HIGH": "#E76F00",
        "PLANNED": "#D5A000",
        "MONITOR": "#3977B8",
    }
    total = sum(priority["band_counts"].values()) or 1
    band_canvas = tk.Canvas(
        band_frame, width=560, height=300, bg="white", highlightthickness=0
    )
    band_canvas.pack(fill="both", expand=True)
    x0, y0, available = 36, 54, 488
    cursor = x0
    for band in order:
        count = int(priority["band_counts"].get(band, 0))
        share = count / total
        width = max(2, available * share)
        band_canvas.create_rectangle(
            cursor, y0, cursor + width, y0 + 38, fill=colors[band], outline=""
        )
        cursor += width
    for index, band in enumerate(order):
        count = int(priority["band_counts"].get(band, 0))
        share = count / total
        y = 125 + index * 36
        band_canvas.create_rectangle(
            44, y - 7, 58, y + 7, fill=colors[band], outline=""
        )
        band_canvas.create_text(
            68, y, text=band, anchor="w", font=("Arial", 10, "bold")
        )
        band_canvas.create_text(250, y, text=f"{count:,}", anchor="e")
        band_canvas.create_text(
            325, y, text=format_percent(share), anchor="e", fill=MUTED_COLOR
        )

    risk_canvas = tk.Canvas(
        risk_frame, width=560, height=300, bg="white", highlightthickness=0
    )
    risk_canvas.pack(fill="both", expand=True)
    draw_single_bars(
        risk_canvas,
        list(priority["risk_bins"].keys()),
        list(priority["risk_bins"].values()),
    )

    table_frame = ttk.LabelFrame(tab, text="Top 10 repair priorities", padding=8)
    table_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
    top_rows = []
    for row in priority["top_pipes"]:
        drivers = ", ".join(
            value
            for value in (
                row.get("driver_1_feature", ""),
                row.get("driver_2_feature", ""),
                row.get("driver_3_feature", ""),
            )
            if value
        )
        top_rows.append(
            [
                row["priority_rank"],
                row["asset_id"],
                format_percent(as_float(row["risk_probability_12m"])),
                f"{as_float(row['predicted_median_months']):.1f}",
                f"{as_float(row['priority_score']):.1f}",
                row["priority_band"],
                drivers,
            ]
        )
    add_tree(
        table_frame,
        [
            ("rank", "Rank", 65),
            ("asset", "Asset ID", 90),
            ("risk", "12m risk", 90),
            ("months", "Median months", 105),
            ("score", "Priority score", 105),
            ("band", "Band", 105),
            ("drivers", "Top drivers", 330),
        ],
        top_rows,
    )


def show_dashboard(data: dict) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError as exc:
        raise RuntimeError(
            "Tkinter is required for the dashboard. Use a standard Windows Python installation."
        ) from exc

    root = tk.Tk()
    root.title("Water Pipe Risk - XGBoost Results")
    root.geometry("1240x820")
    root.minsize(980, 680)
    root.configure(bg="#F6F8FB")

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure(".", font=("Arial", 10), foreground=TEXT_COLOR)
    style.configure("TFrame", background="#F6F8FB")
    style.configure("TLabel", background="#F6F8FB", foreground=TEXT_COLOR)
    style.configure("Muted.TLabel", foreground=MUTED_COLOR)
    style.configure(
        "KPI.TLabel", font=("Arial", 20, "bold"), foreground=TEXT_COLOR
    )
    style.configure(
        "Conclusion.TLabel",
        background="#EAF7F2",
        foreground="#0A5B45",
        padding=12,
    )
    style.configure(
        "Warning.TLabel",
        background="#FFF7E0",
        foreground="#6E5100",
        padding=12,
    )
    style.configure("TLabelframe", background="#F6F8FB")
    style.configure(
        "TLabelframe.Label",
        background="#F6F8FB",
        font=("Arial", 11, "bold"),
    )
    style.configure(
        "Treeview", rowheight=27, background="white", fieldbackground="white"
    )
    style.configure(
        "Treeview.Heading",
        font=("Arial", 9, "bold"),
        background="#263B5E",
        foreground="white",
    )

    header = ttk.Frame(root, padding=(20, 16, 20, 8))
    header.pack(fill="x")
    ttk.Label(
        header, text="Water Pipe Risk Results", font=("Arial", 22, "bold")
    ).pack(anchor="w")
    ttk.Label(
        header,
        text="Logistic baseline comparison and XGBoost repair prioritisation",
        style="Muted.TLabel",
    ).pack(anchor="w", pady=(2, 0))

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=18, pady=(4, 18))
    create_overview_tab(notebook, data)
    create_comparison_tab(notebook, data)
    create_drivers_tab(notebook, data)
    create_priority_tab(notebook, data)

    def report_callback_exception(exc_type, exc_value, exc_traceback):
        messagebox.showerror(
            "Dashboard error", f"{exc_type.__name__}: {exc_value}"
        )

    root.report_callback_exception = report_callback_exception
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comparison-dir", type=Path, default=DEFAULT_COMPARISON
    )
    parser.add_argument("--xgboost-dir", type=Path, default=DEFAULT_XGBOOST)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate dashboard inputs and exit without opening the window.",
    )
    args = parser.parse_args()
    data = load_dashboard_data(args.comparison_dir, args.xgboost_dir)

    if args.check_only:
        summary = data["summary"]
        print(
            "Dashboard inputs validated: "
            f"{summary['sample_count']:,} test rows and "
            f"{data['priority']['row_count']:,} current pipe priorities."
        )
        return

    show_dashboard(data)


if __name__ == "__main__":
    main()
