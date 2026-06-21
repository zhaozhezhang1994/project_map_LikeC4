# 项目导航地图 sidecar API (只读状态聚合)
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
# 国内/弱网可: docker build --build-arg PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX=https://pypi.org/simple
RUN pip install --no-cache-dir -r requirements.txt -i $PIP_INDEX
COPY main.py .
EXPOSE 7004
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7004"]
