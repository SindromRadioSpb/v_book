"""Argparse contract tests for bench_reference_pipeline runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "benchmarks"
        / "bench_reference_pipeline.py"
    )
    spec = importlib.util.spec_from_file_location("bench_reference_pipeline", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parser_defaults_for_all_scenario() -> None:
    mod = _load_module()
    parser = mod.build_parser()
    args = parser.parse_args(
        [
            "all",
            "--db-path",
            r"J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db",
            "--copy-target",
            "--source-db",
            r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db",
        ]
    )

    assert args.scenario == "all"
    assert args.source_project_id == 1
    assert args.doc_limit == 6000
    assert args.overwrite == 1
    assert args.bench_project_name == "BENCH_PIPELINE"
    assert args.lemma_limit == 1000
    assert args.term_limit == 1000
    assert args.sentence_limit == 1000
    assert args.temp_root == r"J:\Project_Vibe\V_book\build\tmp\pipeline_bench_work"


def test_parser_accepts_each_required_subcommand() -> None:
    mod = _load_module()
    parser = mod.build_parser()
    common = [
        "--db-path",
        r"J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db",
        "--copy-target",
        "--source-db",
        r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db",
    ]

    for scenario in (
        "extract_terms",
        "niqqud_bootstrap",
        "translate_bootstrap",
        "tts_bootstrap",
        "all",
    ):
        args = parser.parse_args([scenario, *common])
        assert args.scenario == scenario
