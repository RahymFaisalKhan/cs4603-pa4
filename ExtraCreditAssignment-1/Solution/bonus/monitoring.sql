-- Challenge D: aggregate production request volume, latency, and failures.
-- This workspace rejected inference-table enablement for its agent endpoint
-- type, so this query is submission-ready but has no fabricated result rows.
SELECT date_trunc('minute', request_time) AS minute,
       count(*) AS n_requests,
       round(avg(execution_duration_ms), 2) AS avg_latency_ms,
       sum(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors
FROM cs4603.pa4.pa4_document_analyst_inference_payload
GROUP BY 1
ORDER BY 1;
