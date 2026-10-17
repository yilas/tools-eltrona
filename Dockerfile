FROM python:3.13-alpine
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY monitor.py /app/monitor.py
RUN addgroup -S monitor && adduser -S -G monitor monitor && mkdir /data && chown monitor:monitor /data
USER monitor
CMD ["python", "/app/monitor.py"]
