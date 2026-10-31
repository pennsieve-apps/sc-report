FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /processor

# Pinned Python dependencies (wheels only: pandas, matplotlib, jinja2) and the Lambda runtime
# interface client, so the same image runs as a container (ECS) or as a Lambda function.
COPY requirements.txt /processor/requirements.txt
RUN pip install --only-binary=:all: -r /processor/requirements.txt

COPY processor/ /processor/processor/
COPY VERSION /processor/VERSION

ENV PYTHONPATH="/processor" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib

# Check that the stack imports; matplotlib caches in /tmp at run time (MPLCONFIGDIR).
RUN python -c "import pandas, jinja2, awslambdaric"

# Runs as uid 1000 on the platform; nothing here needs root.
USER 1000

# Runs main() once as a container, or serves processor.handler as a Lambda
# function (see processor/entry.py).
ENTRYPOINT ["python3", "-m", "processor.entry"]
