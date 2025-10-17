FROM alpine

RUN apk update
RUN apk add tzdata inotify-tools docker 
RUN apk add python3 py3-requests py3-watchdog
RUN mkdir -p /app
COPY ./* /app

WORKDIR /app

ENTRYPOINT ["python", "/app/monitor.py"]
