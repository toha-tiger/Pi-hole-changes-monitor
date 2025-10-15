FROM alpine

RUN apk update
RUN apk add inotify-tools docker
RUN mkdir -p /app
COPY ./monitor.sh /app
RUN chmod +x /app/monitor.sh

WORKDIR /app

ENTRYPOINT ["/app/monitor.sh"]
