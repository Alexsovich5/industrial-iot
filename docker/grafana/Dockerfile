# Grafana 4.6.3 from its official .deb on debian:stretch-20171210.
# The builder stage is build tooling only: it downloads and verifies the
# stretch packages and the Grafana .deb, and the final stage installs those
# files with dpkg without contacting any package archive. The builder runs
# on the build host's platform; everything it produces is plain files.

FROM --platform=$BUILDPLATFORM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS builder
RUN ok=; for i in 1 2 3; do \
      if apt-get update && apt-get install -y --no-install-recommends \
           ca-certificates curl debian-archive-keyring dpkg faketime gpgv python3; \
      then ok=1; break; fi; \
      sleep 10; \
    done; [ -n "$ok" ] && rm -rf /var/lib/apt/lists/*
# Debian archive keys, current and removed: the stretch keys have expired,
# and signatures made while they were valid are still checked against them.
RUN cat /usr/share/keyrings/debian-archive-keyring.gpg \
        /usr/share/keyrings/debian-archive-removed-keys.gpg > /apt-keyring.gpg
# Packages already in the target image count as installed.
COPY --from=debian:stretch-20171210@sha256:0a5fcee6f52d5170f557ee2447d7a10a5bdcf715dd7f0250be0b678c556a501b \
     /var/lib/dpkg/status /apt/target-status
# Release signature, Packages checksum and every .deb checksum are checked
# before a file is kept; all downloads use HTTPS.
COPY docker/apt/packages.lock docker/apt/fetch_debs.py /apt/
RUN python3 /apt/fetch_debs.py /apt/packages.lock /apt/target-status /apt-keyring.gpg /debs
RUN ok=; for i in 1 2 3; do \
      if curl -fsSL -o /debs/grafana_4.6.3_amd64.deb \
           https://s3-us-west-2.amazonaws.com/grafana-releases/release/grafana_4.6.3_amd64.deb; \
      then ok=1; break; fi; \
      sleep 10; \
    done; [ -n "$ok" ] \
    && echo "d022fceb939e7570d74b437932bee876e306b0e21ecdd830752c61b4e89dab31  /debs/grafana_4.6.3_amd64.deb" \
        | sha256sum -c -

FROM debian:stretch-20171210@sha256:0a5fcee6f52d5170f557ee2447d7a10a5bdcf715dd7f0250be0b678c556a501b

COPY --from=builder /debs /tmp/debs

# The image keeps no apt sources: its packages were verified in the builder
# stage and are installed here from files, Grafana last.
RUN rm -f /etc/apt/sources.list \
    && cd /tmp/debs \
    && dpkg -i $(cat ORDER) \
    && dpkg -i grafana_4.6.3_amd64.deb \
    && [ -z "$(dpkg --audit)" ] \
    && cd / && rm -rf /tmp/debs

EXPOSE 3000

USER grafana

CMD ["grafana-server", "--homepath=/usr/share/grafana", "--config=/etc/grafana/grafana.ini", \
     "cfg:default.paths.data=/var/lib/grafana", "cfg:default.paths.logs=/var/log/grafana"]
