# Python Library for building Oversight Probes

> This library must be used for building version 3.x probe versions only.


## Environment variable

Variable         | Default                       | Description
---------------- | ----------------------------- | ------------
`AGENTCORE_HOST` | `127.0.0.1`                   | Hostname or Ip address of the AgentCore.
`AGENTCORE_PORT` | `8750`                        | AgentCore port to connect to.
`OVERSIGHT_CONF` | `/data/config/oversight.conf` | File with probe and asset configuration like credentials.
`LOG_LEVEL`      | `warning`                     | Log level (`debug`, `info`, `warning`, `error` or `critical`).
`LOG_COLORIZED`  | `0`                           | Log using colors (`0`=disabled, `1`=enabled).
`LOG_FTM`        | `%y%m%d %H:%M:%S`             | Log format prefix.

