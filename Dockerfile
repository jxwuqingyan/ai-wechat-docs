# 公众号排版工作台 · 容器镜像
#
# 本项目零第三方依赖（纯 Python 标准库），所以镜像里不需要 pip install，
# alpine + python3 就够，构建后大约 50MB。
#
#   docker build -t wx-mp-studio .
#   docker run -d --name wx-mp-studio -p 127.0.0.1:8765:8765 --restart unless-stopped wx-mp-studio
#
# 注意 -p 前务必带上 127.0.0.1:，否则服务会直接暴露到公网（详见 README.md 的「部署到服务器」）。

FROM python:3.12-alpine

LABEL org.opencontainers.image.title="wx-mp-studio" \
      org.opencontainers.image.description="Markdown / Word -> 微信公众号排版工作台" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8765

WORKDIR /app

# 只需要技能本体这一份代码
COPY wechat-mp-formatter/ /app/wechat-mp-formatter/

# 用非 root 用户跑
RUN adduser -D -u 10001 appuser
USER appuser

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2).status==200 else 1)"

# 容器内必须监听 0.0.0.0 才能被端口映射访问；
# 真正的访问控制靠宿主机侧的 -p 127.0.0.1:8765:8765 或 Nginx 反向代理。
CMD ["python3", "/app/wechat-mp-formatter/scripts/server.py", "--host", "0.0.0.0", "--port", "8765", "--no-open"]
