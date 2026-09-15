FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system stockpm && adduser --system --ingroup stockpm stockpm

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

USER stockpm
EXPOSE 8000

# Two workers: a hung/slow desk assemble in one process must not 502 the whole site.
# Per-request discovery still has a hard 5–8s budget; workers are belt-and-suspenders.
CMD ["uvicorn", "stock_pm.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "2"]
