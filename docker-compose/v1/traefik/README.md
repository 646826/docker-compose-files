# Example generate strings hash
> echo $(docker run --rm httpd:2.4-alpine htpasswd -nb admin bc183SEgTbuNqxLyuGTd2s) | sed -e s/\\$/\\$\\$/g
