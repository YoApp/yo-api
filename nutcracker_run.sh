#!/bin/bash

OIFS=$IFS
IFS=";"

ratelimiterservers=( $TWEMPROXY_RATELIMITER_SERVER )
cacheservers=( $TWEMPROXY_CACHE_SERVER )

twemproxyconfig="$(cat <<-EndOfNutCrackerYML
ratelimiter:
  auto_eject_hosts: true
  distribution: ketama
  hash: fnv1a_64
  listen: 127.0.0.1:22121
  redis: true
  server_failure_limit: 2
  server_retry_timeout: 2000
  timeout: 1000
  servers:

EndOfNutCrackerYML
)"

for ((i=0; i<${#ratelimiterservers[@]}; ++i));
do
    twemproxyconfig="$twemproxyconfig$(cat <<-EndOfNutCrackerYML

       - ${ratelimiterservers[$i]}
EndOfNutCrackerYML
)"
done

twemproxyconfig="$twemproxyconfig$(cat <<-EndOfNutCrackerYML


cache:
  auto_eject_hosts: true
  distribution: ketama
  hash: fnv1a_64
  listen: 127.0.0.1:22122
  redis: true
  server_failure_limit: 2
  server_retry_timeout: 2000
  timeout: 1000
  servers:

EndOfNutCrackerYML
)"

for ((i=0; i<${#cacheservers[@]}; ++i));
do
    twemproxyconfig="$twemproxyconfig$(cat <<-EndOfNutCrackerYML

       - ${cacheservers[$i]}
EndOfNutCrackerYML
)"
done

IFS=$OIFS

echo "$twemproxyconfig" > nutcracker.yml

# Pass on any arguments to nutcracker
/usr/local/sbin/nutcracker -c nutcracker.yml "$@"
