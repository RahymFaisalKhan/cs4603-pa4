# Part 3 before/after comparison

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| `correctness/mean` | 0.5833 | 1.0000 | +0.4167 |
| `relevance_to_query/mean` | 1.0000 | 1.0000 | +0.0000 |
| `retrieval_groundedness/mean` | 0.5000 | 0.7500 | +0.2500 |
| `retrieval_relevance/mean` | 0.4444 | 0.4444 | +0.0000 |
| `retrieval_relevance/precision/mean` | 0.5764 | 0.5556 | -0.0208 |

## Lowest-scoring baseline examples

- 0.200 — {'request': 'What net revenue and operating profit did Meridian forecast for FY2024?'}
- 0.200 — {'request': 'Using FY2023 operating cash flow and capital expenditure, calculate free cash flow.'}
- 0.200 — {'request': 'Was North American FY2023 revenue greater than Motorcycle segment revenue? State both values and the difference.'}
