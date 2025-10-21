FROM alpine

RUN apk update
RUN apk add tzdata
RUN apk add python3 py3-requests py3-watchdog
RUN mkdir -p /app/nebula-sync
COPY ./*.py /app
RUN wget -O - https://github.com/lovelaze/nebula-sync/releases/download/v0.11.1/nebula-sync_0.11.1_linux_amd64.tar.gz | tar -xzf - -C /app/nebula-sync

WORKDIR /app

ENTRYPOINT ["python", "/app/monitor.py"]
