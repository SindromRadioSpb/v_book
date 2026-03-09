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
    assert args.reuse_base_copy is False
    assert args.reuse_working_db is False
    assert args.tier is None
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


def test_tier_preset_sets_expected_doc_limit() -> None:
    mod = _load_module()
    parser = mod.build_parser()
    args = parser.parse_args(
        [
            "extract_terms",
            "--db-path",
            r"J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db",
            "--copy-target",
            "--source-db",
            r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db",
            "--tier",
            "large",
        ]
    )

    tier = mod.resolve_tier_preset(args, ["extract_terms", "--tier", "large"])

    assert tier["name"] == "large"
    assert tier["doc_limit"] == 2000
    assert tier["recommended_wall_budget_sec"] == 900
    assert args.doc_limit == 2000


def test_explicit_doc_limit_overrides_tier_default() -> None:
    mod = _load_module()
    parser = mod.build_parser()
    args = parser.parse_args(
        [
            "extract_terms",
            "--db-path",
            r"J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db",
            "--copy-target",
            "--source-db",
            r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db",
            "--tier",
            "medium",
            "--doc-limit",
            "1500",
        ]
    )

    tier = mod.resolve_tier_preset(
        args,
        ["extract_terms", "--tier", "medium", "--doc-limit", "1500"],
    )

    assert tier["name"] == "medium"
    assert tier["doc_limit"] == 1500
    assert tier["recommended_wall_budget_sec"] == 600
    assert args.doc_limit == 1500
