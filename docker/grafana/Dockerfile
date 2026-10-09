FROM debian:stretch-20171210@sha256:0a5fcee6f52d5170f557ee2447d7a10a5bdcf715dd7f0250be0b678c556a501b

ENV SNAPSHOT=http://snapshot.debian.org/archive/debian/20171231T000000Z

# The archive keys that signed this snapshot have since expired, so apt
# refuses the signature. apt still checks every package against the hashes
# in the downloaded Release file; that Release file is then verified with
# gpgv against the keys shipped in the base image, and the build fails if
# the signature does not check out.
RUN echo "deb $SNAPSHOT stretch main" > /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false \
        -o Acquire::AllowInsecureRepositories=true update \
    && apt-get -o Acquire::Check-Valid-Until=false install -y --no-install-recommends \
        --allow-unauthenticated adduser libfontconfig1 ca-certificates curl \
    && curl -fsSL --retry 3 -o /tmp/Release.gpg "$SNAPSHOT/dists/stretch/Release.gpg" \
    && cat /etc/apt/trusted.gpg.d/debian-archive-*.gpg > /tmp/debian-keys.gpg \
    && gpgv --keyring /tmp/debian-keys.gpg /tmp/Release.gpg \
        /var/lib/apt/lists/*_dists_stretch_Release \
    && rm -rf /var/lib/apt/lists/* /tmp/Release.gpg /tmp/debian-keys.gpg

RUN curl -fsSL --retry 3 -o grafana.deb \
        https://s3-us-west-2.amazonaws.com/grafana-releases/release/grafana_4.6.3_amd64.deb \
    && echo "d022fceb939e7570d74b437932bee876e306b0e21ecdd830752c61b4e89dab31  grafana.deb" \
        | sha256sum -c - \
    && dpkg -i grafana.deb \
    && rm grafana.deb

EXPOSE 3000

USER grafana

CMD ["grafana-server", "--homepath=/usr/share/grafana", "--config=/etc/grafana/grafana.ini", \
     "cfg:default.paths.data=/var/lib/grafana", "cfg:default.paths.logs=/var/log/grafana"]
