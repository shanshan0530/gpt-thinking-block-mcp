FROM python:3.12-slim

WORKDIR /app
COPY server.py server_custom.py ./

ENV PYTHONUNBUFFERED=1
ENV THINKING_PROMPT_LANGUAGE=zh-CN
ENV MCP_BIND=0.0.0.0
ENV CAPTURE_ENABLED=0
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=3s --retries=3 \
  CMD ["python3", "-c", "import os, urllib.request; port=os.environ.get('PORT','8787'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2)"]

CMD ["python3", "server_custom.py", "8787"]
