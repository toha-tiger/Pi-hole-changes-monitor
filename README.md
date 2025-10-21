## Description

Monitors Pi-hole config changes and starts Nebula Sync to trigger a sync with other Pi-hole instances.

The tool is intended for a Docker project that consists of Pi-hole. To perform a sync the Nebula Sync is used. By default Nebula Sync cannot detect when exactly the configuration of Pi-hole changes. So usually a cron sync is configured for reasonable time period.

The tool uses `watchdog.observers` to watch the Pi-hole configuration and start the Nebula Sync, which triggers a sync.

Since a single change in config can trigger multiple changes in files, there is a debouncing time of 3 seconds before starting Nebula Sync. This means a change in Pi-hole configuration will be applied to other hosts after 3 seconds.

## Configuration/usage

To use the tool, just add a config for Nebula Sync `nebula-sync.env` and a service to your `docker-compose.yml`

See also `docker-compose.example.yml` for a complete example.

Below is a list of options to add to an existing Pi-hole docker-compose.yml
```
networks:
  pihole-net:
    name: pihole-net

services:
  pihole:
    # ... standard configuration ...
    networks: [pihole-net]
  monitor:
    image: ghcr.io/toha-tiger/pi-hole-changes-monitor:main
    environment:
      WATCH_DIR: /etc/pihole
      WATCH_INCLUDE: '.db$$|.conf$$|.leases$$|.list$$|.toml$$'
      WATCH_EXCLUDE: '_backup|_old.db'
      DEBOUNCE_TIME: 3
      ONCHANGE_CMD: /app/nebula-sync/nebula-sync run --env-file /app/nebula-sync/.env
      PIHOLE_API_URL: http://pihole
      PIHOLE_PASSWORD: 'correct horse battery staple'
      TZ: 'Europe/London'
    volumes:
      - ./etc-pihole:/etc/pihole:ro
      - ./nebula-sync.env:/app/nebula-sync/.env:ro
    depends_on:
      - pihole
    restart: unless-stopped
    networks: [pihole-net]
```

`nebula-sync.env` should contain the configuration for Nebula Sync. Be sure not to enable the CRON option so Nebula Sync runs once and exits.

```
PRIMARY=http://ph1.example.com|password
REPLICAS=http://ph2.example.com|password,http://ph3.example.com|password
FULL_SYNC=true
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

- Include files to monitor changes

  ```
  WATCH_INCLUDE: '.db$$|.conf$$|.leases$$|.list$$|.toml$$'
  ```

- Exclude temparary or backup files

  ```
  WATCH_EXCLUDE: '_backup|_old.db'
  ```

- Debounce time. A time in seconds to ignore multiple changes in Pi-hole configuration files. Lower values make the sync run earlier but can trigger duplicate updates.
  ```
  DEBOUNCE_TIME: 3
  ```

- A command to run on changes detected

  ```
  ONCHANGE_CMD: /app/nebula-sync/nebula-sync run --env-file /app/nebula-sync/.env
  ```

  This command simply starts Nebula Sync with env file passed.

- Pi-hole primary instance url (in docker network) and a password. If your docker service Pi-hole named pihole then url is `http://pihole`. The password should match `FTLCONF_webserver_api_password` config
  ```
  PIHOLE_API_URL: http://pihole
  PIHOLE_PASSWORD: 'correct horse battery staple'
  ```
