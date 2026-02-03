#!/bin/bash
# CI Test Runner - Bash (Linux/macOS)
# Runs all M7 + P1 tests for gating

set -e

echo "========================================"
echo "CI Test Runner - M7 + P1 Gate"
echo "========================================"

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    echo -e "\nActivating virtual environment..."
    source .venv/bin/activate
else
    echo "ERROR: Virtual environment not found at .venv/"
    echo "Please run: python -m venv .venv"
    exit 1
fi

# Set headless mode for Qt
export QT_QPA_PLATFORM=offscreen

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

run_test() {
    local test_name="$1"
    local test_command="$2"

    echo ""
    echo "----------------------------------------"
    echo "Running: $test_name"
    echo "----------------------------------------"

    if python "$test_command"; then
        echo "✅ PASS: $test_name"
        ((TESTS_PASSED++))
    else
        echo "❌ FAIL: $test_name"
        ((TESTS_FAILED++))
    fi
}

# Run M7 tests
run_test "M7 Core Tests" "test_m7.py"
run_test "M7 UI Integration" "test_m7_ui_integration.py"
run_test "M7 Normalization" "test_m7_normalization.py"

# Run P1 tests
run_test "P1 Unit Tests" "test_p1_verification.py"
run_test "P1 E2E (Term Clusters)" "test_p1_e2e_termclusters.py"

# Summary
echo ""
echo "========================================"
echo "CI Test Summary"
echo "========================================"
echo "Passed: $TESTS_PASSED"
echo "Failed: $TESTS_FAILED"

if [ $TESTS_FAILED -gt 0 ]; then
    echo ""
    echo "❌ CI GATE FAILED"
    exit 1
else
    echo ""
    echo "✅ CI GATE PASSED"
    exit 0
fi
