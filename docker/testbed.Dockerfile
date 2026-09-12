# Minimal image for scripts/docker_testbed.py: python:3.11-slim plus git,
# which the base image doesn't ship with. Built once and cached locally;
# rebuilt only when this file changes.
FROM python:3.11-slim

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
