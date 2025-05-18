# Use a Python image with uv
FROM docker.io/library/python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Setting env
ENV TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive \
    # Enable bytecode compilation
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
    
# use mirrors
# ENV UV_DEFAULT_INDEX="https://mirrors.aliyun.com/pypi/simple"

# use mirrors
# RUN echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib" >> /etc/apt/sources.list\
#   && echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib" >> /etc/apt/sources.list\
#   && echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib" >> /etc/apt/sources.list\
#   && echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib" >> /etc/apt/sources.list

# install nb-cli & playwright
RUN uv pip install --system nb-cli playwright

# install font fonts-noto-color-emoji
RUN apt-get update \
    && apt-get install -y --no-install-recommends fontconfig \
    && rm -rf /tmp/sarasa /tmp/sarasa.7z /var/lib/apt/lists/*

# RUN playwright install --only-shell --with-deps chromium \
#     && rm -rf /var/lib/apt/lists/*


# Set workdir `/app`
WORKDIR /app

# Clean uv entrypoint
ENTRYPOINT [""]

CMD ["sh","-c", "./entrypoint.sh"]
