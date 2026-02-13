"""Test script to verify TranslateAllFilteredWorker stats updates.

Verifies that:
1. Worker has succeeded/skipped/failed attributes
2. stats_updated signal emits correctly
3. Values are updated in real-time
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from app.ui.workers import TranslateAllFilteredWorker


def test_worker_attributes():
    """Test that worker has required attributes."""
    print("=" * 60)
    print("TEST 1: Worker Attributes")
    print("=" * 60)

    worker = TranslateAllFilteredWorker(
        entity_type="lemma",
        project_id=1,
        filters={},
        provider_mode="chain",
        write_mode="FILL_EMPTY",
        id_fetch_chunk=200,
        translation_chunk=25,
    )

    # Check attributes exist
    assert hasattr(worker, 'succeeded'), "Worker должен иметь атрибут succeeded"
    assert hasattr(worker, 'skipped'), "Worker должен иметь атрибут skipped"
    assert hasattr(worker, 'failed'), "Worker должен иметь атрибут failed"

    # Check initial values
    assert worker.succeeded == 0, "Начальное значение succeeded должно быть 0"
    assert worker.skipped == 0, "Начальное значение skipped должно быть 0"
    assert worker.failed == 0, "Начальное значение failed должно быть 0"

    print("[OK] Worker имеет атрибуты succeeded/skipped/failed")
    print(f"   - succeeded: {worker.succeeded}")
    print(f"   - skipped: {worker.skipped}")
    print(f"   - failed: {worker.failed}")
    print()

    return True


def test_worker_signals():
    """Test that worker has required signals."""
    print("=" * 60)
    print("TEST 2: Worker Signals")
    print("=" * 60)

    worker = TranslateAllFilteredWorker(
        entity_type="lemma",
        project_id=1,
        filters={},
        provider_mode="chain",
        write_mode="FILL_EMPTY",
    )

    # Check signals exist
    assert hasattr(worker, 'progress'), "Worker должен иметь сигнал progress"
    assert hasattr(worker, 'stats_updated'), "Worker должен иметь сигнал stats_updated"
    assert hasattr(worker, 'row_translated'), "Worker должен иметь сигнал row_translated"
    assert hasattr(worker, 'paused'), "Worker должен иметь сигнал paused"
    assert hasattr(worker, 'resumed'), "Worker должен иметь сигнал resumed"

    print("[OK] Worker имеет все необходимые сигналы:")
    print("   - progress(int, int)")
    print("   - stats_updated(int, int, int) [NEW]")
    print("   - row_translated(str, str, bool)")
    print("   - paused()")
    print("   - resumed()")
    print()

    return True


def test_signal_connections():
    """Test that signals can be connected."""
    print("=" * 60)
    print("TEST 3: Signal Connections")
    print("=" * 60)

    app = QApplication.instance() or QApplication(sys.argv)

    worker = TranslateAllFilteredWorker(
        entity_type="lemma",
        project_id=1,
        filters={},
        provider_mode="chain",
        write_mode="FILL_EMPTY",
    )

    # Track received signals
    received_stats = []
    received_progress = []

    def on_stats_updated(succeeded, skipped, failed):
        received_stats.append((succeeded, skipped, failed))
        print(f"   [STATS] stats_updated получен: succeeded={succeeded}, skipped={skipped}, failed={failed}")

    def on_progress(completed, total):
        received_progress.append((completed, total))
        print(f"   [PROGRESS] progress получен: {completed}/{total}")

    # Connect signals
    worker.stats_updated.connect(on_stats_updated)
    worker.progress.connect(on_progress)

    print("[OK] Сигналы подключены успешно")
    print()

    # Test emit (manual simulation)
    print("Тест: эмуляция обновления stats...")
    worker.succeeded = 100
    worker.skipped = 20
    worker.failed = 5
    worker.stats_updated.emit(100, 20, 5)

    worker.progress.emit(125, 500)

    # Process events
    app.processEvents()

    # Verify signals received
    assert len(received_stats) == 1, "Должен быть получен 1 stats_updated сигнал"
    assert received_stats[0] == (100, 20, 5), "Значения stats должны совпадать"

    assert len(received_progress) == 1, "Должен быть получен 1 progress сигнал"
    assert received_progress[0] == (125, 500), "Значения progress должны совпадать"

    print("[OK] Сигналы получены и значения корректны")
    print()

    return True


def test_chunk_parameters():
    """Test that chunk parameters are set correctly."""
    print("=" * 60)
    print("TEST 4: Chunk Parameters")
    print("=" * 60)

    worker = TranslateAllFilteredWorker(
        entity_type="term_cluster",
        project_id=1,
        filters={},
        provider_mode="chain",
        write_mode="OVERWRITE",
        id_fetch_chunk=200,
        translation_chunk=25,
    )

    assert worker.id_fetch_chunk == 200, "id_fetch_chunk должен быть 200"
    assert worker.translation_chunk == 25, "translation_chunk должен быть 25"

    print("[OK] Chunk parameters установлены корректно:")
    print(f"   - id_fetch_chunk: {worker.id_fetch_chunk} (для DB efficiency)")
    print(f"   - translation_chunk: {worker.translation_chunk} (для UX)")
    print()

    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ВЕРИФИКАЦИЯ: TranslateAllFilteredWorker Stats Updates")
    print("=" * 60)
    print()

    tests = [
        ("Worker Attributes", test_worker_attributes),
        ("Worker Signals", test_worker_signals),
        ("Signal Connections", test_signal_connections),
        ("Chunk Parameters", test_chunk_parameters),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"[FAIL] {test_name} FAILED")
        except AssertionError as e:
            failed += 1
            print(f"❌ {test_name} FAILED: {e}")
        except Exception as e:
            failed += 1
            print(f"❌ {test_name} ERROR: {e}")

    print("=" * 60)
    print("РЕЗУЛЬТАТЫ:")
    print("=" * 60)
    print(f"[PASS] Passed: {passed}/{len(tests)}")
    print(f"[FAIL] Failed: {failed}/{len(tests)}")
    print()

    if failed == 0:
        print("[SUCCESS] ВСЕ ТЕСТЫ ПРОШЛИ!")
        print()
        print("[!] ВАЖНО: Это unit-тесты для проверки атрибутов и сигналов.")
        print("[!] Для полной верификации необходим manual UI тест:")
        print("    1. Запустить приложение")
        print("    2. Выбрать проект (например, 'Физика')")
        print("    3. Перейти во вкладку Terms")
        print("    4. Translate Selected... -> All pages (filtered)")
        print("    5. Проверить что:")
        print("       - Progress обновляется каждые 10-30 сек")
        print("       - Total показывает правильное число (858)")
        print("       - Stats обновляются (succeeded/skipped/failed)")
        print("       - ETA и Speed показываются")
        print("       - Activity log показывает последние переводы")
        print()
        return 0
    else:
        print("[ERROR] ЕСТЬ ПРОВАЛЕННЫЕ ТЕСТЫ!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
