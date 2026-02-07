# Hebrew Wikipedia Pipeline Benchmark

**Date:** 20260207T115954Z

## Sample Benchmark Results

### NLP Processing
- Sample size: 99 documents
- Duration: 1.3min
- Throughput: 1.27 docs/sec
- Success: 99
- Errors: 0

### Term Extraction
- Sample size: 100 documents
- Duration: 4.0s
- Throughput: 25.28 docs/sec
- N-grams extracted: 806
- Clusters created: 760

## Extrapolated Estimates (Full Corpus: 387,639 documents)

### NLP Processing
- **Estimated duration:** 84.7h
- Throughput: 1.27 docs/sec

### Term Extraction
- **Estimated duration:** 4.3h
- Throughput: 25.28 docs/sec

### Total Pipeline
- **Estimated total duration:** 89.0h

## Notes

- Estimates based on 99 sample documents
- Actual performance may vary based on document size, complexity, and system load
- GPU acceleration: False
