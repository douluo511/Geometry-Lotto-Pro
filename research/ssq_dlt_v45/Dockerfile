FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY research/ssq_dlt_v45 /app/research/ssq_dlt_v45
COPY research/ssq_dlt_d2_v44 /app/research/ssq_dlt_d2_v44
# The runtime uses the standard library. No source discovery service or cloud
# credential is installed in this optional local container.
USER 10001:10001
STOPSIGNAL SIGTERM
CMD ["python", "-m", "research.ssq_dlt_v45.windows.container_loop", "--config", "/config/runtime.json"]
