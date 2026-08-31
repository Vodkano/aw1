FROM gitpod/workspace-full:latest

RUN sudo apt-get update \
    && sudo apt-get install -y --no-install-recommends \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 \
        libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
        libasound2 \
    && sudo rm -rf /var/lib/apt/lists/*
