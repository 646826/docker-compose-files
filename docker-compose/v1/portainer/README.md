# Example generate strings hash
> docker run --rm httpd:2.4-alpine htpasswd -nbB admin bc183SEgTbuNqxLyuGTd2s | cut -d ":" -f 2 | sed -e s/\\$/\\$\\$/g
