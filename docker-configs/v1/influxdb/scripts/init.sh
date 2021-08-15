#!/bin/sh
export INFLUX_BUCKET_TELEGRAF=telegraf
export INFLUX_BUCKET_TRAEFIK=traefik
export INFLUX_BUCKET_OPENHAB=openhab

set -e
influx bucket create -n $INFLUX_BUCKET_TELEGRAF -r 800d
influx bucket create -n $INFLUX_BUCKET_TRAEFIK -r 800d
influx bucket create -n $INFLUX_BUCKET_OPENHAB