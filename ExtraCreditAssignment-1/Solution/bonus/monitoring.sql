-- Challenge D: aggregate production request volume, latency, and failures.
-- The workspace rejected Databricks-managed inference tables. The source below
-- is the explicitly labeled client-side UC Delta fallback created by
-- bonus/trace_and_monitor.py; it is not claimed as a managed inference table.
SELECT date_trunc('minute', request_time) AS minute,
       count(*) AS n_requests,
       round(avg(execution_duration_ms), 2) AS avg_latency_ms,
       sum(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors
FROM cs4603.pa4.pa4_document_analyst_client_payload
GROUP BY 1
ORDER BY 1;
