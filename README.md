## Description

Monitors Pi-hole config changes and restarts Nebula Sync to trigger a sync

The tool is intended for a Docker project that consists of Pi-hole and Nebula Sync. By default Nebula Sync cannot detect when exactly the configuration of Pi-hole changes. So usually a cron sync is configured for reasonable time period.

The tool uses `inotifywait` to watch the Pi-hole configuration and restart the Nebula Sync container, which triggers a sync

Since a single change in config can trigger multiple changes in files there is a debouncing time of 3 seconds before restarting nebula sync. This means a change in Pi-hole configuration will be applied to other hosts after 3 seconds.

## Configuration/usage

To use the tool, just add the `monitor` directory and a service to your docker-compose.yml

```
  # Add this service to pihole + nebula sync project to issue the sync on pihole config change
  # put it inside services: section
  monitor:
    build: ./monitor/
    environment:
      WATCH_DIR: /etc/pihole
      ONCHANGE_CMD: docker restart nebula-sync
      EXCLUDE: '.db-journal|.db-shm|.db-wal|gravity.db|_old.db|listsCache|versions|cli_pw|logrotate|.log$$|.bak$$|.tmp$$|.temp$$|.swp$$'
    volumes:
      - ./etc-pihole:/etc/pihole:ro
      - /var/run/docker.sock:/var/run/docker.sock
    depends_on:
      - nebula-sync
    restart: unless-stopped
```

## Configuration

- Watch directory
  ```
  WATCH_DIR: /etc/pihole
  ```

  and 
  ```
  volumes:
    - ./etc-pihole:/etc/pihole:ro
  ```

  Make sure ./etc-pihole points to the directory where the Pi-hole files are stored

- Docker command to run on changes detected

  ```
  ONCHANGE_CMD: docker restart nebula-sync
  ```

  This command simply restarts Nebula Sync. Ensure the container name matches the one defined in your docker-compose file.

- Exclude files that change frequently during normal operation

  ```
  EXCLUDE: '.db-journal|.db-shm|.db-wal|gravity.db|_old.db|listsCache|versions|cli_pw|logrotate|.log$$|.bak$$|.tmp$$|.temp$$|.swp$$'
  ```
